#!/bin/bash

# ==============================================================================
# GCP Document Intelligence - Initialization Script
# ==============================================================================
# This script provisions the required GCP resources:
# - Cloud Storage Buckets
# - Pub/Sub Topics and Event bindings
# - Firestore Database (Native Mode)
# - BigQuery Datasets and Tables
# ==============================================================================

# Exit immediately if a pipeline command fails
set -e

# Configuration Variables — loaded from .env if present, else from environment
if [ -f "$(dirname "$0")/../.env" ]; then
    set -a
    source "$(dirname "$0")/../.env"
    set +a
fi

PROJECT_ID=${PROJECT_ID:-"your-gcp-project-id"}
REGION=${REGION:-"us-central1"}
ENV=${ENV:-"dev"}

if [ "$PROJECT_ID" = "your-gcp-project-id" ]; then
    echo -e "\033[0;31m[ERROR]\033[0m PROJECT_ID is not set. Copy .env.example to .env and fill in your values."
    exit 1
fi

# Color codes for readable terminal output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions for logging
function log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

function log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

function log_warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_info "Initializing GCP Resources for Project: $PROJECT_ID ($REGION) in Environment: $ENV..."

# ------------------------------------------------------------------------------
# 1. Enable Required APIs
# ------------------------------------------------------------------------------
log_info "Enabling required GCP APIs..."
gcloud services enable \
    storage.googleapis.com \
    pubsub.googleapis.com \
    firestore.googleapis.com \
    bigquery.googleapis.com \
    aiplatform.googleapis.com \
    documentai.googleapis.com \
    --project "$PROJECT_ID"
log_success "APIs enabled."

# ------------------------------------------------------------------------------
# 2. Create Storage Buckets
# ------------------------------------------------------------------------------
log_info "Creating Google Cloud Storage Buckets..."

# Create raw documents bucket (gcloud storage avoids gsutil permission issues on Windows)
if ! gcloud storage ls "gs://raw-documents-$PROJECT_ID-$ENV" --project="$PROJECT_ID" &> /dev/null; then
  gcloud storage buckets create "gs://raw-documents-$PROJECT_ID-$ENV" \
      --location="$REGION" \
      --uniform-bucket-level-access \
      --project="$PROJECT_ID"
else
  log_warn "Bucket gs://raw-documents-$PROJECT_ID-$ENV already exists."
fi

# Create dead letter bucket for failed processing
if ! gcloud storage ls "gs://dead-letter-$PROJECT_ID-$ENV" --project="$PROJECT_ID" &> /dev/null; then
  gcloud storage buckets create "gs://dead-letter-$PROJECT_ID-$ENV" \
      --location="$REGION" \
      --uniform-bucket-level-access \
      --project="$PROJECT_ID"
else
  log_warn "Bucket gs://dead-letter-$PROJECT_ID-$ENV already exists."
fi

log_success "Storage Buckets configured."

# ------------------------------------------------------------------------------
# 3. Create Pub/Sub Topics
# ------------------------------------------------------------------------------
log_info "Creating Pub/Sub Topics for event-driven architecture..."
TOPICS=(
    "doc-uploaded"
    "process-invoice"
    "process-contract"
    "process-compliance"
    "route-to-storage"
    "dead-letter-topic"
)

for TOPIC in "${TOPICS[@]}"; do
    # Create topic unless it already exists (suppress error if it does)
    gcloud pubsub topics create "$TOPIC" --project "$PROJECT_ID" 2>/dev/null || log_warn "Topic $TOPIC may already exist."
done
log_success "Pub/Sub Topics created."

# ------------------------------------------------------------------------------
# 4. Create Pub/Sub Push Subscriptions (wired to Cloud Run service URLs)
# ------------------------------------------------------------------------------
log_info "Creating Pub/Sub push subscriptions linked to Cloud Run services..."

# Helper: get a Cloud Run service URL
get_service_url() {
    local SERVICE_NAME=$1
    gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format="value(status.url)" 2>/dev/null
}

# Map: subscription-name | topic | cloud-run-service-name
declare -A SUBSCRIPTIONS=(
    ["dispatcher-sub"]="doc-uploaded|dispatcher"
    ["worker-invoice-sub"]="process-invoice|workers"
    ["worker-contract-sub"]="process-contract|workers"
    ["compliance-sub"]="process-compliance|compliance-agent"
    ["storage-sub"]="route-to-storage|storage-router"
)

for SUB_NAME in "${!SUBSCRIPTIONS[@]}"; do
    IFS='|' read -r TOPIC SERVICE_NAME <<< "${SUBSCRIPTIONS[$SUB_NAME]}"
    SERVICE_URL=$(get_service_url "$SERVICE_NAME")

    if [ -z "$SERVICE_URL" ]; then
        log_warn "Could not get URL for '$SERVICE_NAME'. Run deploy-all.ps1 first, then re-run this script to create '$SUB_NAME'."
        continue
    fi

    PUSH_ENDPOINT="$SERVICE_URL/"
    gcloud pubsub subscriptions create "$SUB_NAME" \
        --topic="$TOPIC" \
        --push-endpoint="$PUSH_ENDPOINT" \
        --ack-deadline=300 \
        --expiration-period=never \
        --project="$PROJECT_ID" 2>/dev/null || \
        gcloud pubsub subscriptions modify-push-config "$SUB_NAME" \
            --push-endpoint="$PUSH_ENDPOINT" \
            --project="$PROJECT_ID" 2>/dev/null || \
        log_warn "Subscription '$SUB_NAME' could not be created or updated."

    log_success "  $SUB_NAME → $TOPIC → $PUSH_ENDPOINT"
done

log_success "Pub/Sub push subscriptions configured."

# ------------------------------------------------------------------------------
# 5. Configure GCS to trigger Pub/Sub
# ------------------------------------------------------------------------------
log_info "Binding Google Cloud Storage events to Pub/Sub topic 'doc-uploaded'..."
SERVICE_ACCOUNT=$(gcloud storage service-agent --project="$PROJECT_ID")

# Grant Pub/Sub Publisher role to the Cloud Storage service account
gcloud pubsub topics add-iam-policy-binding doc-uploaded \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/pubsub.publisher" \
    --project "$PROJECT_ID" > /dev/null

# Create a GCS notification using gcloud storage (avoids gsutil on Windows)
gcloud storage buckets notifications create "gs://raw-documents-$PROJECT_ID-$ENV" \
    --topic=doc-uploaded \
    --event-types=OBJECT_FINALIZE \
    --payload-format=json \
    --project="$PROJECT_ID" 2>/dev/null || log_warn "Notification binding may already exist."

log_success "GCS to Pub/Sub binding completed."

# ------------------------------------------------------------------------------
# 6. Initialize Firestore Base
# ------------------------------------------------------------------------------
log_info "Creating Firestore Database (Native Mode) for state management..."
# In some Organizations this requires App Engine creation first.
# The '||' handles the error gracefully if the DB already exists.
gcloud firestore databases create \
    --location="$REGION" \
    --type=firestore-native \
    --project="$PROJECT_ID" 2>/dev/null || log_warn "Firestore database might already exist. Continuing."

log_success "Firestore initialization handled."

# ------------------------------------------------------------------------------
# 7. Initialize BigQuery Dataset and Table
# ------------------------------------------------------------------------------
log_info "Creating BigQuery Dataset 'document_intelligence'..."
bq --project_id="$PROJECT_ID" mk --dataset document_intelligence 2>/dev/null || log_warn "Dataset may already exist."

log_info "Creating BigQuery Extractions Table..."
bq mk --table --project_id="$PROJECT_ID" \
  --description "Stores structured data extracted from documents" \
  "document_intelligence.extractions_$ENV" \
  document_id:STRING,document_type:STRING,extracted_fields:JSON,confidence_score:FLOAT,created_at:TIMESTAMP 2>/dev/null || log_warn "Table may already exist."

log_success "BigQuery configuration completed."

# ------------------------------------------------------------------------------
# Completion Message
# ------------------------------------------------------------------------------
echo "=============================================================================="
log_success "Initialization Complete!"
log_info "Raw Upload Bucket: gs://raw-documents-$PROJECT_ID-$ENV"
echo "=============================================================================="
