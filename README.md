# GCP Document Intelligence Pipeline

An event-driven, serverless pipeline for classifying, extracting, and verifying documents using Google Cloud Platform. 

This repository leverages **Gemini**, **Document AI**, **Pub/Sub**, and **LangGraph** to automate document flows with a built-in Human-in-the-Loop (HITL) dashboard.

## Architecture

1.  **Dispatcher (`/services/dispatcher`)**: Listens to Cloud Storage uploads via Pub/Sub -> Classifies using Gemini Flash -> Routes to specific worker topic.
2.  **Domain Workers (`/services/workers`)**: Receives domain-specific document (e.g. Invoice) -> Extracts fields & scores confidence -> Routes to Firestore OR Compliance loop.
3.  **HITL Dashboard (`/frontend`)**: A beautiful, React + Tailwind glassmorphic dashboard reading the Firestore queue for human verification.
4.  **Compliance Agent (`/services/compliance_agent`)**: A LangGraph state-machine that audits extracted data against corporate policies.
5.  **Storage Router (`/services/storage_router`)**: Loads structured results to BigQuery and unstructured text/fields into Vertex AI Embeddings for Hybrid Search.

## Deployment Guide

### 1. Provision Infrastructure (Shell Script)
Instead of using Terraform, you can initialize all Cloud Storage buckets, Pub/Sub topics, Firestore, and BigQuery using the provided bash script.

Make sure you are authenticated with `gcloud auth login`.

```bash
cd scripts
chmod +x init-gcp.sh
./init-gcp.sh
```
*(If running on Windows PowerShell, you can run the equivalent gcloud commands manually by reading the `init-gcp.sh` file).*

### 2. Deploy Microservices
Deploy each FastAPI application to Cloud Run.
```bash
# Example for Dispatcher
cd services/dispatcher
gcloud run deploy doc-dispatcher \
  --source . \
  --region us-central1 \
  --set-env-vars PROJECT_ID=ml-deployment-482112 \
  --no-allow-unauthenticated
```
*Note: Bind the Cloud Run URLs as push delivery endpoints for your Pub/Sub topics.*

### 3. Run the HITL Dashboard
```bash
cd frontend
npm install
npm run dev
# Visit http://localhost:5173
```
