#!/bin/bash

# ==============================================================================
# setup-cicd-sa.sh — Create GCP Service Account for GitHub Actions CI/CD
# ==============================================================================
# Run this ONCE manually from your local machine to set up the service account.
# The JSON key output goes into GitHub Secrets as GCP_SA_KEY.
# ==============================================================================

set -e

# Load .env if present
if [ -f "$(dirname "$0")/../.env" ]; then
    set -a
    source "$(dirname "$0")/../.env"
    set +a
fi

PROJECT_ID=${PROJECT_ID:-"your-gcp-project-id"}
REGION=${REGION:-"us-central1"}

if [ "$PROJECT_ID" = "your-gcp-project-id" ]; then
    echo "[ERROR] PROJECT_ID is not set. Copy .env.example to .env and fill in your values."
    exit 1
fi

SA_NAME="github-actions-cicd"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
KEY_FILE="$(dirname "$0")/../github-actions-sa-key.json"

echo "[INFO] Creating service account: $SA_NAME"
gcloud iam service-accounts create "$SA_NAME" \
    --display-name="GitHub Actions CI/CD" \
    --project="$PROJECT_ID" 2>/dev/null || echo "[WARN] Service account may already exist."

echo "[INFO] Granting required IAM roles..."

# Deploy to Cloud Run
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/run.admin" > /dev/null

# Push Docker images to Artifact Registry
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/artifactregistry.writer" > /dev/null

# Submit Cloud Builds
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/cloudbuild.builds.editor" > /dev/null

# Act as service accounts (needed for Cloud Run deploy)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/iam.serviceAccountUser" > /dev/null

# Cloud Build needs Storage access for staging bucket
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/storage.admin" > /dev/null

echo "[SUCCESS] IAM roles granted to $SA_EMAIL"

echo "[INFO] Generating JSON key file: $KEY_FILE"
gcloud iam service-accounts keys create "$KEY_FILE" \
    --iam-account="$SA_EMAIL" \
    --project="$PROJECT_ID"

echo ""
echo "============================================================"
echo "[SUCCESS] Service account key saved to: $KEY_FILE"
echo ""
echo "Next steps:"
echo "  1. Copy the contents of: $KEY_FILE"
echo "  2. Go to: GitHub repo → Settings → Secrets → Actions"
echo "  3. Add these 3 secrets:"
echo "       GCP_SA_KEY    → paste the full JSON key content"
echo "       GCP_PROJECT_ID → $PROJECT_ID"
echo "       GCP_REGION    → $REGION"
echo ""
echo "  ⚠️  Then DELETE the key file from your local machine!"
echo "       rm $KEY_FILE"
echo "============================================================"
