Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

# ── config ────────────────────────────────────────────────────────────────────

$PROJECT_ID   = "veridict"
$REGION       = "europe-west1"
$CLUSTER_NAME = "veridict-dev-gke"
$GAR_REPO     = "veridict"
$GAR_URL      = "$REGION-docker.pkg.dev/$PROJECT_ID/$GAR_REPO"
$SA_NAME      = "veridict-gke-sa"
$SA_EMAIL     = "$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
$OUTPUT_FILE  = Join-Path $env:TEMP "veridict_gcp_outputs.json"

Write-Step "Active project: $PROJECT_ID"
gcloud config set project $PROJECT_ID

# ── billing reminder ──────────────────────────────────────────────────────────

Write-Step "MANUAL STEP REQUIRED -- Enable Billing"
Write-Host ""
Write-Host "  1. Go to: https://console.cloud.google.com/billing/projects"
Write-Host "  2. Find project '$PROJECT_ID' and link a billing account."
Write-Host ""
Write-Host "  Press ENTER once billing is enabled to continue..."
Read-Host | Out-Null

# ── enable APIs ───────────────────────────────────────────────────────────────

Write-Step "Enabling required GCP APIs (this takes ~2 min)"
$apis = @(
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com"
)
foreach ($api in $apis) {
    Write-Host "  Enabling $api ..."
    gcloud services enable $api --project $PROJECT_ID
}
Write-Host "  All APIs enabled."

# ── Artifact Registry ─────────────────────────────────────────────────────────

Write-Step "Creating Artifact Registry repository '$GAR_REPO'"
$ErrorActionPreference = "Continue"
gcloud artifacts repositories describe $GAR_REPO --location=$REGION --project=$PROJECT_ID 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Repository already exists -- skipping."
} else {
    gcloud artifacts repositories create $GAR_REPO `
        --repository-format=docker `
        --location=$REGION `
        --description="Veridict container images" `
        --project=$PROJECT_ID
    Write-Host "  Repository created."
}
$ErrorActionPreference = "Stop"

# ── GCS buckets ───────────────────────────────────────────────────────────────

Write-Step "Creating GCS buckets"
foreach ($bucket in @("veridict-dev-datasets", "veridict-dev-artifacts", "veridict-dev-rag")) {
    $ErrorActionPreference = "Continue"
    gcloud storage buckets describe "gs://$bucket" --project=$PROJECT_ID 2>&1 | Out-Null
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  gs://$bucket already exists -- skipping."
    } else {
        gcloud storage buckets create "gs://$bucket" `
            --location=$REGION `
            --uniform-bucket-level-access `
            --project=$PROJECT_ID
        Write-Host "  gs://$bucket created."
    }
}

# ── Service Account ───────────────────────────────────────────────────────────

Write-Step "Creating Workload Identity service account"
$ErrorActionPreference = "Continue"
gcloud iam service-accounts describe $SA_EMAIL --project=$PROJECT_ID 2>&1 | Out-Null
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Service account already exists -- skipping."
} else {
    gcloud iam service-accounts create $SA_NAME `
        --display-name="Veridict GKE Workload Identity SA" `
        --project=$PROJECT_ID
    Write-Host "  Service account created: $SA_EMAIL"
}

Write-Step "Granting IAM roles to service account"
$roles = @(
    "roles/artifactregistry.reader",
    "roles/storage.objectAdmin",
    "roles/secretmanager.secretAccessor"
)
foreach ($role in $roles) {
    gcloud projects add-iam-policy-binding $PROJECT_ID `
        --member="serviceAccount:$SA_EMAIL" `
        --role=$role `
        --quiet
    Write-Host "  Granted $role"
}

# ── GKE Cluster ───────────────────────────────────────────────────────────────

Write-Step "Creating GKE cluster '$CLUSTER_NAME' (this takes ~8-10 min)"
$ErrorActionPreference = "Continue"
gcloud container clusters describe $CLUSTER_NAME --region=$REGION --project=$PROJECT_ID 2>&1 | Out-Null
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Cluster already exists -- skipping."
} else {
    gcloud container clusters create $CLUSTER_NAME `
        --region=$REGION `
        --release-channel=regular `
        --workload-pool="$PROJECT_ID.svc.id.goog" `
        --num-nodes=1 `
        --no-enable-autoprovisioning `
        --project=$PROJECT_ID
    Write-Host "  Cluster created."

    # Delete the default node pool (we create our own)
    Write-Step "Replacing default node pool with system pool (e2-standard-4 x2)"
    gcloud container node-pools create system `
        --cluster=$CLUSTER_NAME `
        --region=$REGION `
        --machine-type=e2-standard-4 `
        --disk-type=pd-ssd `
        --disk-size=100 `
        --num-nodes=1 `
        --enable-autoupgrade `
        --enable-autorepair `
        --workload-metadata=GKE_METADATA `
        --project=$PROJECT_ID

    gcloud container node-pools delete default-pool `
        --cluster=$CLUSTER_NAME `
        --region=$REGION `
        --quiet `
        --project=$PROJECT_ID

    Write-Host "  System node pool ready."
}

# ── save outputs ──────────────────────────────────────────────────────────────

Write-Step "Saving outputs to $OUTPUT_FILE"
$outputData = @{
    project_id       = @{ value = $PROJECT_ID }
    region           = @{ value = $REGION }
    gke_cluster_name = @{ value = $CLUSTER_NAME }
    gar_url          = @{ value = $GAR_URL }
    datasets_bucket  = @{ value = "veridict-dev-datasets" }
    artifacts_bucket = @{ value = "veridict-dev-artifacts" }
}
$outputData | ConvertTo-Json -Depth 5 | Out-File -FilePath $OUTPUT_FILE -Encoding UTF8
Write-Host "Outputs saved to: $OUTPUT_FILE"

# ── summary ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "=== Phase 1 complete -- infrastructure is ready ===" -ForegroundColor Green
Write-Host ""
Write-Host "  GKE cluster : $CLUSTER_NAME"
Write-Host "  GAR URL     : $GAR_URL"
Write-Host "  Region      : $REGION"
Write-Host ""
Write-Host "Next step: run .\deploy_gcp_phase1_images.ps1"
