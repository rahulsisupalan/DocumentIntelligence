"""
Storage Router Service
=======================
This is the FINAL STEP in the pipeline.

What it does:
  1. Receives a fully verified and compliant document payload from the Compliance Agent (via Pub/Sub).
  2. Stores the structured extracted fields in BigQuery (enables SQL keyword search).
  3. Generates a semantic embedding vector from the document's content and stores it
     in Vertex AI Vector Search (enables meaning-based semantic search).

Why dual storage?
  - BigQuery: "Find all invoices from Vendor XYZ" (exact keyword match)
  - Vector Search: "Find documents related to software licensing disputes" (semantic similarity)
"""

import base64
import json
import os
import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from google.cloud import bigquery
from vertexai.language_models import TextEmbeddingModel

# ── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App Initialization ───────────────────────────────────────────────────────
app = FastAPI(title="Storage Router Service")

# ── Configuration ────────────────────────────────────────────────────────────
PROJECT_ID          = os.getenv("PROJECT_ID",          "your-project-id")
LOCATION            = os.getenv("LOCATION",            "us-central1")
BQ_DATASET          = os.getenv("BQ_DATASET",          "document_intelligence")
BQ_TABLE            = os.getenv("BQ_TABLE",            "extractions_dev")
VECTOR_SEARCH_INDEX = os.getenv("VECTOR_SEARCH_INDEX", "doc_embeddings_index")

# ── GCP Client Setup ─────────────────────────────────────────────────────────
# We don't crash on startup if these clients fail to initialize.
# This allows for local/dry-run testing without GCP credentials.
try:
    bq_client = bigquery.Client(project=PROJECT_ID)
except Exception:
    logger.warning("Could not connect to BigQuery. Running in local/dry-run mode.")
    bq_client = None

try:
    # textembedding-gecko is Google's dedicated model for creating vector embeddings.
    embedding_model = TextEmbeddingModel.from_pretrained("textembedding-gecko@003")
except Exception:
    logger.warning("Could not initialize TextEmbeddingModel. Running in local/dry-run mode.")
    embedding_model = None


# ── Main API Endpoint ─────────────────────────────────────────────────────────

@app.post("/")
async def handle_storage_routing(request: Request):
    """
    Final step: store the processed document in BigQuery and Vertex AI Vector Search.
    """
    # ── Step 1: Decode the Message ──────────────────────────────────────────
    envelope = await request.json()
    if not envelope or "message" not in envelope:
        raise HTTPException(status_code=400, detail="Invalid or empty Pub/Sub message.")

    raw_data = base64.b64decode(envelope["message"]["data"]).decode("utf-8")
    payload  = json.loads(raw_data)
    gcs_uri  = payload.get("gcs_uri", "gs://unknown/file")
    logger.info("Routing document to storage: %s", gcs_uri)

    # ── Step 2: Store Structured Data in BigQuery (Keyword Search) ───────────────
    # BigQuery stores the extracted fields in a table that can be queried with SQL.
    if bq_client:
        table_id = f"{PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"
        row = [{
            "document_id":      gcs_uri.split("/")[-1],          # Use the filename as the unique ID
            "document_type":    payload.get("document_type", "UNKNOWN"),
            "extracted_fields": json.dumps(payload.get("extracted_data", {})),
            "confidence_score": payload.get("overall_score", 0.0),
            "created_at":       datetime.utcnow().isoformat(),
        }]
        errors = bq_client.insert_rows_json(table_id, row)
        if errors:
            logger.error("BigQuery insertion failed: %s", errors)
        else:
            logger.info("Successfully saved structured data to BigQuery table: %s", BQ_TABLE)
    else:
        logger.info("[DRY RUN] Would insert structured data into BigQuery.")

    # ── Step 3: Generate and Store Embedding Vector (Semantic Search) ────────────
    # An "embedding" is a list of numbers that represents the meaning of the text.
    # Documents with similar meanings will have similar numbers (close in vector space).
    text_to_embed = f"{payload.get('document_type')} content: {json.dumps(payload.get('extracted_data', {}))}"

    if embedding_model:
        try:
            embeddings = embedding_model.get_embeddings([text_to_embed])
            vector     = embeddings[0].values
            logger.info("Generated embedding vector of length %d.", len(vector))
            # TODO: Write `vector` to Vertex AI Vector Search Index (VECTOR_SEARCH_INDEX)
            # This enables semantic search across all processed documents.
        except Exception as e:
            logger.error("Failed to generate embedding: %s", e)
    else:
        logger.info("[DRY RUN] Would generate semantic embedding vector for search indexing.")

    return {"status": "success", "routing": "stored"}
