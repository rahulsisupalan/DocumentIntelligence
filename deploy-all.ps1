# ==============================================================================
# deploy-all.ps1 - GCP Document Intelligence Full Deployment Script
# ==============================================================================
# Usage:
#   .\deploy-all.ps1
#
# Requirements:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - Docker Desktop running
#   - gcloud auth configure-docker us-central1-docker.pkg.dev (run once)
# ==============================================================================

# ------------------------------------------
# Configuration — loaded from .env file
# ------------------------------------------
$ENV_FILE = "$PSScriptRoot\.env"
if (-Not (Test-Path $ENV_FILE)) {
    Write-Host "[ERROR] .env file not found at $ENV_FILE" -ForegroundColor Red
    Write-Host "        Copy .env.example to .env and fill in your values." -ForegroundColor Yellow
    exit 1
}

# Parse the .env file into PowerShell variables
Get-Content $ENV_FILE | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
    }
}

$PROJECT_ID = $env:PROJECT_ID
$REGION     = if ($env:REGION)  { $env:REGION }  else { "us-central1" }
$REPO       = if ($env:REPO)    { $env:REPO }    else { "services" }
$ENV        = if ($env:ENV)     { $env:ENV }     else { "dev" }
$REGISTRY   = "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO"

if (-Not $PROJECT_ID) {
    Write-Host "[ERROR] PROJECT_ID is not set in your .env file." -ForegroundColor Red
    exit 1
}

# Services to build & deploy (folder name = Cloud Run service name)
$SERVICES = @("dispatcher", "workers", "compliance_agent", "storage_router")

$SERVICES_DIR = "$PSScriptRoot\services"

# ------------------------------------------
# Helper: colored output
# ------------------------------------------
function Log-Info    { param($msg) Write-Host "[INFO]    $msg" -ForegroundColor Cyan }
function Log-Success { param($msg) Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Log-Error   { param($msg) Write-Host "[ERROR]   $msg" -ForegroundColor Red }
function Log-Warn    { param($msg) Write-Host "[WARN]    $msg" -ForegroundColor Yellow }

# ------------------------------------------
# Step 1: Authenticate & set project
# ------------------------------------------
Log-Info "Setting active GCP project to $PROJECT_ID..."
gcloud config set project $PROJECT_ID
if ($LASTEXITCODE -ne 0) { Log-Error "Failed to set project. Is gcloud installed?"; exit 1 }

# ------------------------------------------
# Step 2: Enable required APIs
# ------------------------------------------
Log-Info "Enabling required GCP APIs..."
gcloud services enable `
    run.googleapis.com `
    artifactregistry.googleapis.com `
    cloudbuild.googleapis.com `
    storage.googleapis.com `
    pubsub.googleapis.com `
    firestore.googleapis.com `
    bigquery.googleapis.com `
    aiplatform.googleapis.com `
    documentai.googleapis.com `
    --project $PROJECT_ID

Log-Success "APIs enabled."

# ------------------------------------------
# Step 3: Create Artifact Registry repo (if not exists)
# ------------------------------------------
Log-Info "Ensuring Artifact Registry repository '$REPO' exists..."
$repoExists = gcloud artifacts repositories describe $REPO --location=$REGION --project=$PROJECT_ID 2>&1
if ($LASTEXITCODE -ne 0) {
    Log-Info "Creating Artifact Registry repository '$REPO'..."
    gcloud artifacts repositories create $REPO `
        --repository-format=docker `
        --location=$REGION `
        --project=$PROJECT_ID
    Log-Success "Artifact Registry repository created."
} else {
    Log-Warn "Artifact Registry repository '$REPO' already exists. Skipping."
}

# Configure Docker to authenticate with Artifact Registry
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

# ------------------------------------------
# Step 4: Build (via Cloud Build) & Deploy each service
# NOTE: No local Docker required — gcloud builds submit sends source to GCP
# ------------------------------------------
foreach ($SERVICE in $SERVICES) {
    $SERVICE_DIR = "$SERVICES_DIR\$SERVICE"
    $IMAGE = "$REGISTRY/${SERVICE}:latest"
    # Cloud Run service names use hyphens (compliance_agent -> compliance-agent)
    $RUN_NAME = $SERVICE -replace "_", "-"

    Write-Host ""
    Log-Info "========================================================"
    Log-Info " Processing service: $SERVICE"
    Log-Info "========================================================"

    # Build & push using Google Cloud Build (no local Docker needed)
    Log-Info "Submitting build to Cloud Build: $IMAGE"
    gcloud builds submit $SERVICE_DIR `
        --tag $IMAGE `
        --project $PROJECT_ID
    if ($LASTEXITCODE -ne 0) { Log-Error "Cloud Build failed for $SERVICE. Skipping."; continue }

    # Deploy to Cloud Run
    Log-Info "Deploying $RUN_NAME to Cloud Run ($REGION)..."
    gcloud run deploy $RUN_NAME `
        --image $IMAGE `
        --region $REGION `
        --platform managed `
        --allow-unauthenticated `
        --set-env-vars "PROJECT_ID=$PROJECT_ID,REGION=$REGION,ENV=$ENV" `
        --project $PROJECT_ID

    if ($LASTEXITCODE -ne 0) {
        Log-Error "Cloud Run deployment failed for $SERVICE."
    } else {
        Log-Success "$RUN_NAME deployed successfully!"
        $URL = gcloud run services describe $RUN_NAME --region=$REGION --project=$PROJECT_ID --format="value(status.url)"
        Log-Success "  URL: $URL"
    }
}

# ------------------------------------------
# Step 5: Summary
# ------------------------------------------
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Log-Success "All services deployed!"
Write-Host "================================================================================" -ForegroundColor Cyan

Log-Info "Listing all Cloud Run services in project:"
gcloud run services list --project $PROJECT_ID --region $REGION --format="table(SERVICE,URL,LAST_DEPLOYED_BY,LAST_DEPLOYED_AT)"

Write-Host ""
Log-Info "Next step -> run the infrastructure init script:"
Log-Info "  bash scripts/init-gcp.sh"
