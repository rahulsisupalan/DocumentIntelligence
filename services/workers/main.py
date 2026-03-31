"""
Worker Service (Domain Extraction)
===================================
This is the SECOND STEP in the pipeline.

What it does:
  1. Receives a classified document from the Dispatcher (via Pub/Sub).
  2. Uses a powerful AI model (Gemini Pro) to extract key fields from the document.
  3. Scores its own confidence in each extracted field.
  4. Decides what to do next based on the overall confidence score:
       - Low confidence (< 80%)  -> Sends to Firestore for a HUMAN to review.
       - High confidence (>= 80%) -> Sends to the Compliance Agent for automated auditing.
"""

import base64
import json
import os
import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from google.cloud import pubsub_v1, firestore
import vertexai
from vertexai.generative_models import GenerativeModel, Part

# ── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App Initialization ───────────────────────────────────────────────────────
app = FastAPI(title="Domain Extraction Worker Service")

# ── Configuration ────────────────────────────────────────────────────────────
PROJECT_ID            = os.getenv("PROJECT_ID",            "your-project-id")
LOCATION              = os.getenv("LOCATION",              "us-central1")
COMPLIANCE_TOPIC      = os.getenv("COMPLIANCE_TOPIC",      "process-compliance")
FIRESTORE_COLLECTION  = os.getenv("FIRESTORE_COLLECTION",  "review-queue")

# If confidence is below this number (0.0 to 1.0), a human must review the document.
CONFIDENCE_THRESHOLD  = float(os.getenv("CONFIDENCE_THRESHOLD", "0.80"))

# ── GCP Client Setup ─────────────────────────────────────────────────────────
publisher = pubsub_v1.PublisherClient()
vertexai.init(project=PROJECT_ID, location=LOCATION)

# We use Gemini Pro here because data extraction needs deeper understanding than classification.
extraction_model = GenerativeModel("gemini-1.5-pro-001")

# Firestore is the HITL (Human-in-the-Loop) database. We try to connect but won't crash if it's unavailable locally.
try:
    db = firestore.Client(project=PROJECT_ID)
except Exception:
    logger.warning("Could not connect to Firestore. Running in local/dry-run mode.")
    db = None

# ── AI Prompt ────────────────────────────────────────────────────────────────
# This tells Gemini Pro exactly what fields to extract and how to format the response.
EXTRACTION_PROMPT = """
You are an expert document data extraction engine.
Extract all important information from the provided document.

You MUST respond ONLY with a valid JSON object in this exact format:
{
  "extracted_data": {
    "Vendor Name": "value or null",
    "Total Amount": "value or null",
    "Date": "value or null",
    "Tax ID (TIN)": "value or null",
    "Contract Type": "value or null",
    "Signatures Present": true or false
  },
  "confidence_scores": {
    "Vendor Name": 0.98,
    "Total Amount": 0.75,
    "Date": 0.90,
    "Tax ID (TIN)": 0.50,
    "Contract Type": 0.80,
    "Signatures Present": 0.99
  }
}

The confidence score should be between 0.0 (not sure at all) and 1.0 (completely certain).
"""


# ── Helper Functions ─────────────────────────────────────────────────────────

def calculate_average_confidence(scores: dict) -> float:
    """Returns the average of all per-field confidence scores as an overall score."""
    if not scores:
        return 0.0
    return sum(scores.values()) / len(scores)


def publish_to_topic(topic_id: str, payload: dict):
    """Sends a JSON payload to a Google Cloud Pub/Sub topic."""
    if PROJECT_ID == "your-project-id":
        logger.warning(f"[DRY RUN] Would publish to '{topic_id}'.")
        return
    topic_path = publisher.topic_path(PROJECT_ID, topic_id)
    future = publisher.publish(topic_path, json.dumps(payload).encode("utf-8"))
    future.result()
    logger.info(f"Published message to topic: {topic_id}")


def save_to_hitl_queue(payload: dict):
    """
    Saves a document to the Firestore 'review-queue' collection.
    A human operator will inspect this document using the HITL Dashboard.
    """
    if not db:
        logger.warning(f"[DRY RUN] Would save document to Firestore HITL queue.")
        return

    # Add metadata fields before saving
    payload["status"]    = "PENDING_REVIEW"
    payload["timestamp"] = datetime.utcnow().isoformat()

    doc_ref = db.collection(FIRESTORE_COLLECTION).document()
    doc_ref.set(payload)
    logger.info(f"Saved to Human Review Queue. Firestore Document ID: {doc_ref.id}")


# ── Main API Endpoint ─────────────────────────────────────────────────────────

@app.post("/")
async def handle_document_extraction(request: Request):
    """
    This endpoint is called by Pub/Sub when a classified document is ready for data extraction.

    The flow is:
      1. Decode the Pub/Sub message to get the document URI and type.
      2. Send the document to Gemini Pro to extract structured fields.
      3. Calculate an overall confidence score from the per-field scores.
      4. Route: low confidence -> Human Review, high confidence -> Compliance Agent.
    """
    # ── Step 1: Decode the Pub/Sub Message ───────────────────────────────────
    envelope = await request.json()
    if not envelope or "message" not in envelope:
        raise HTTPException(status_code=400, detail="Invalid or empty Pub/Sub message.")

    raw_data = base64.b64decode(envelope["message"]["data"]).decode("utf-8")
    data     = json.loads(raw_data)

    gcs_uri  = data.get("gcs_uri")
    doc_type = data.get("document_type", "UNKNOWN")

    if not gcs_uri:
        logger.error(f"Message received with no 'gcs_uri'. Data: {data}")
        return {"status": "error", "detail": "Missing gcs_uri field."}

    logger.info(f"Starting extraction for a '{doc_type}' document at: {gcs_uri}")

    # ── Step 2: Extract Data with Gemini Pro ─────────────────────────────────
    try:
        document = Part.from_uri(mime_type="application/pdf", uri=gcs_uri)
        response = extraction_model.generate_content(
            [EXTRACTION_PROMPT, document],
            generation_config={"response_mime_type": "application/json"}
        )

        # Clean and parse the JSON response from Gemini
        clean_json    = response.text.replace("```json", "").replace("```", "").strip()
        result        = json.loads(clean_json)
        extracted     = result.get("extracted_data", {})
        field_scores  = result.get("confidence_scores", {})

    except Exception as e:
        logger.error(f"Gemini extraction failed for {gcs_uri}: {e}")
        raise HTTPException(status_code=500, detail="Document extraction failed.")

    # ── Step 3: Calculate Overall Confidence Score ────────────────────────────
    overall_score = calculate_average_confidence(field_scores)
    logger.info(f"Extraction complete. Overall confidence score: {overall_score:.2%}")

    # Build the payload we'll pass to the next service
    result_payload = {
        "gcs_uri":          gcs_uri,
        "document_type":    doc_type,
        "extracted_data":   extracted,
        "confidence_scores": field_scores,
        "overall_score":    overall_score,
    }

    # ── Step 4: Route Based on Confidence ────────────────────────────────────
    if overall_score < CONFIDENCE_THRESHOLD:
        # The AI isn't confident enough. A human needs to verify this document.
        logger.warning(f"Confidence ({overall_score:.2%}) is below the {CONFIDENCE_THRESHOLD:.0%} threshold. Routing to Human Review.")
        save_to_hitl_queue(result_payload)
        return {"status": "success", "routing": "HUMAN_REVIEW"}
    else:
        # Confidence is high enough. Send it to the automated Compliance Agent.
        logger.info(f"Confidence ({overall_score:.2%}) meets threshold. Routing to Compliance Agent.")
        publish_to_topic(COMPLIANCE_TOPIC, result_payload)
        return {"status": "success", "routing": "COMPLIANCE_AGENT"}
