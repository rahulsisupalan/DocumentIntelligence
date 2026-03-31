"""
Dispatcher Service
==================
Entry point of the pipeline.

What it does:
  1. Receives a Pub/Sub notification when a new document is uploaded to Cloud Storage.
  2. Passes the GCS URI directly to Gemini 2.5 Pro on Vertex AI for classification.
  3. Routes the document to the correct downstream Pub/Sub topic.

Document Types:
  - INVOICE   -> 'process-invoice' topic
  - CONTRACT  -> 'process-contract' topic
  - Anything else -> 'dead-letter-topic'
"""

import base64
import json
import os
import logging
from fastapi import FastAPI, Request, HTTPException
from google.cloud import pubsub_v1
import vertexai
from vertexai.generative_models import GenerativeModel, Part

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App & Config ─────────────────────────────────────────────────────────────
app = FastAPI(title="Document Dispatcher Service")

PROJECT_ID        = os.getenv("PROJECT_ID",        "your-project-id")
REGION            = os.getenv("REGION",            "us-central1")
INVOICE_TOPIC     = os.getenv("INVOICE_TOPIC",     "process-invoice")
CONTRACT_TOPIC    = os.getenv("CONTRACT_TOPIC",    "process-contract")
DEAD_LETTER_TOPIC = os.getenv("DEAD_LETTER_TOPIC", "dead-letter-topic")

# ── GCP & Vertex AI Clients ───────────────────────────────────────────────────
# Uses the Cloud Run service account credentials automatically — no API key needed.
publisher = pubsub_v1.PublisherClient()
vertexai.init(project=PROJECT_ID, location=REGION)

# Gemini 2.5 Pro — reads PDFs directly from GCS via URI (no download needed)
model = GenerativeModel("gemini-2.5-pro")

# ── AI Prompt ─────────────────────────────────────────────────────────────────
CLASSIFICATION_PROMPT = """You are a document classifier. Analyze the document and identify its type.
Respond with ONLY one of these exact words: INVOICE, CONTRACT, TAX_FORM, UNKNOWN.
No explanation. No punctuation. Just the single word."""


# ── Helper: Publish to Pub/Sub ────────────────────────────────────────────────
def publish_to_topic(topic_id: str, payload: dict):
    """Sends a JSON payload to a Pub/Sub topic."""
    if PROJECT_ID == "your-project-id":
        logger.warning(f"[DRY RUN] Would publish to '{topic_id}': {payload}")
        return
    topic_path = publisher.topic_path(PROJECT_ID, topic_id)
    future = publisher.publish(topic_path, json.dumps(payload).encode("utf-8"))
    future.result()
    logger.info(f"Published message to topic: {topic_id}")


# ── Main Endpoint ─────────────────────────────────────────────────────────────
@app.post("/")
async def handle_new_document(request: Request):
    """
    Receives a Pub/Sub push event, classifies the PDF with Gemini 2.5 Pro
    via its GCS URI, and routes to the correct downstream Pub/Sub topic.
    """
    # Step 1: Decode the Pub/Sub envelope
    envelope = await request.json()
    if not envelope or "message" not in envelope:
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub message.")

    raw_data   = base64.b64decode(envelope["message"]["data"]).decode("utf-8")
    event_data = json.loads(raw_data)

    bucket   = event_data.get("bucket")
    filename = event_data.get("name")

    if not bucket or not filename:
        logger.error(f"Missing 'bucket' or 'name' in message: {event_data}")
        return {"status": "error", "detail": "Missing required fields."}

    gcs_uri = f"gs://{bucket}/{filename}"
    logger.info(f"New document received: {gcs_uri}")

    # Step 2: Classify with Gemini 2.5 Pro (reads directly from GCS)
    try:
        document = Part.from_uri(mime_type="application/pdf", uri=gcs_uri)
        response = model.generate_content([CLASSIFICATION_PROMPT, document])
        doc_type = response.text.strip().upper()
        logger.info(f"Gemini classified document as: '{doc_type}'")

    except Exception as e:
        logger.error(f"Gemini classification failed for {gcs_uri}: {e}")
        raise HTTPException(status_code=500, detail="AI classification failed.")

    # Step 3: Route to the correct downstream Pub/Sub topic
    downstream_payload = {
        "gcs_uri":       gcs_uri,
        "bucket":        bucket,
        "filename":      filename,
        "document_type": doc_type,
    }

    if "INVOICE" in doc_type:
        publish_to_topic(INVOICE_TOPIC, downstream_payload)
    elif "CONTRACT" in doc_type:
        publish_to_topic(CONTRACT_TOPIC, downstream_payload)
    else:
        logger.warning(f"Unsupported type '{doc_type}'. Routing to dead-letter.")
        publish_to_topic(DEAD_LETTER_TOPIC, downstream_payload)

    return {"status": "success", "classification": doc_type}
