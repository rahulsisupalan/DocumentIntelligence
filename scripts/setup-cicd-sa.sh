#!/bin/bash

# ==============================================================================
# setup-cicd-sa.sh — Configure Workload Identity Federation for GitHub Actions
# ==============================================================================
# Run this ONCE manually. No JSON keys needed — uses keyless auth instead.
# GitHub Actions authenticates to GCP via OIDC (OpenID Connect).
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login)
#   - Your GitHub repo already created (e.g. github.com/rahulsisupalan/DocumentIntelligence)
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

# ── Configuration ─────────────────────────────────────────────────────────────
SA_NAME="github-actions-cicd"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
POOL_NAME="github-pool"
PROVIDER_NAME="github-provider"
GITHUB_ORG_OR_USER="rahulsisupalan"         # your GitHub username or org
GITHUB_REPO="DocumentIntelligence"           # your GitHub repo name
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")

echo "[INFO] Project: $PROJECT_ID (number: $PROJECT_NUMBER)"
echo "[INFO] Service Account: $SA_EMAIL"

# ── Step 1: Enable IAM Credentials API ────────────────────────────────────────
echo "[INFO] Enabling required APIs..."
gcloud services enable iamcredentials.googleapis.com --project="$PROJECT_ID"

# ── Step 2: Ensure Service Account exists ─────────────────────────────────────
echo "[INFO] Ensuring service account exists: $SA_NAME"
gcloud iam service-accounts create "$SA_NAME" \
    --display-name="GitHub Actions CI/CD" \
    --project="$PROJECT_ID" 2>/dev/null || echo "[WARN] Service account already exists. Continuing."

# ── Step 3: Grant IAM roles to the service account ───────────────────────────
echo "[INFO] Granting IAM roles..."
for ROLE in \
    "roles/run.admin" \
    "roles/artifactregistry.writer" \
    "roles/cloudbuild.builds.editor" \
    "roles/iam.serviceAccountUser" \
    "roles/storage.admin"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="$ROLE" > /dev/null
    echo "  ✓ $ROLE"
done

# ── Step 4: Create Workload Identity Pool ─────────────────────────────────────
echo "[INFO] Creating Workload Identity Pool: $POOL_NAME"
gcloud iam workload-identity-pools create "$POOL_NAME" \
    --location="global" \
    --display-name="GitHub Actions Pool" \
    --project="$PROJECT_ID" 2>/dev/null || echo "[WARN] Pool may already exist. Continuing."

# ── Step 5: Create Workload Identity Provider (GitHub OIDC) ──────────────────
echo "[INFO] Creating Workload Identity Provider: $PROVIDER_NAME"
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_NAME" \
    --location="global" \
    --workload-identity-pool="$POOL_NAME" \
    --display-name="GitHub Provider" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository_owner == '${GITHUB_ORG_OR_USER}'" \
    --project="$PROJECT_ID" 2>/dev/null || echo "[WARN] Provider may already exist. Continuing."

# ── Step 6: Allow GitHub repo to impersonate the service account ──────────────
echo "[INFO] Binding GitHub repo to service account impersonation..."
POOL_RESOURCE="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_NAME"

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/$POOL_RESOURCE/attribute.repository/$GITHUB_ORG_OR_USER/$GITHUB_REPO" \
    --project="$PROJECT_ID" > /dev/null

# ── Step 7: Print the values needed for GitHub Secrets ───────────────────────
PROVIDER_RESOURCE="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_NAME/providers/$PROVIDER_NAME"

echo ""
echo "============================================================"
echo "[SUCCESS] Workload Identity Federation configured!"
echo ""
echo "Add these 3 secrets to GitHub:"
echo "  GitHub repo → Settings → Secrets → Actions → New repository secret"
echo ""
echo "  GCP_PROJECT_ID              = $PROJECT_ID"
echo "  GCP_REGION                  = $REGION"
echo "  GCP_WORKLOAD_IDENTITY_PROVIDER = $PROVIDER_RESOURCE"
echo "  GCP_SERVICE_ACCOUNT         = $SA_EMAIL"
echo ""
echo "No JSON key needed — keyless auth via OIDC ✅"
echo "============================================================"
