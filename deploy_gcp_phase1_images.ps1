Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Require-Command([string]$cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "Required tool not found: $cmd"
    }
}

# preflight
Write-Step "Checking prerequisites"
Require-Command "gcloud"
Require-Command "docker"
Require-Command "kubectl"

$OUTPUT_FILE = Join-Path $env:TEMP "veridict_gcp_outputs.json"
if (-not (Test-Path $OUTPUT_FILE)) {
    Write-Error "Terraform outputs not found at $OUTPUT_FILE. Run deploy_gcp_phase1.ps1 first."
}

$outputs      = Get-Content $OUTPUT_FILE | ConvertFrom-Json
$PROJECT_ID   = $outputs.project_id.value
$GAR_URL      = $outputs.gar_url.value
$CLUSTER_NAME = $outputs.gke_cluster_name.value
$REGION       = $outputs.region.value

Write-Host "  Project   : $PROJECT_ID"
Write-Host "  GAR URL   : $GAR_URL"
Write-Host "  GKE       : $CLUSTER_NAME ($REGION)"

# configure Docker auth for GAR
Write-Step "Configuring Docker to authenticate with Artifact Registry"
gcloud auth configure-docker europe-west1-docker.pkg.dev --quiet

# build and push images
$REPO_ROOT = $PSScriptRoot

foreach ($service in @("api", "worker", "frontend")) {
    Write-Step "Building and pushing verdict-$service"
    $imageRef = "$GAR_URL/verdict-${service}:latest"
    docker build -t $imageRef -f "$REPO_ROOT\Dockerfile.$service" "$REPO_ROOT"
    if ($LASTEXITCODE -ne 0) { Write-Error "Docker build failed for $service. Is Docker Desktop running?" }
    docker push $imageRef
    if ($LASTEXITCODE -ne 0) { Write-Error "Docker push failed for $service." }
}

# patch k8s manifests with real project ID
Write-Step "Patching k8s manifests (replacing GCP_PROJECT_ID with $PROJECT_ID)"
$k8sDir = Join-Path $REPO_ROOT "k8s"
foreach ($file in @("api.yaml", "worker.yaml", "frontend.yaml", "migration-job.yaml")) {
    $path = Join-Path $k8sDir $file
    (Get-Content $path) -replace "GCP_PROJECT_ID", $PROJECT_ID | Set-Content $path
}

# get GKE credentials
Write-Step "Getting GKE credentials for $CLUSTER_NAME"
gcloud container clusters get-credentials $CLUSTER_NAME --region $REGION --project $PROJECT_ID

# apply base manifests
Write-Step "Creating namespace"
kubectl apply -f "$k8sDir\namespace.yaml"

# create secrets (interactive)
Write-Step "Creating verdict-secrets"
Write-Host "  You will be prompted for secret values."
Write-Host "  Press ENTER to skip optional ones."
Write-Host ""

$pgPass = Read-Host "  POSTGRES_PASSWORD"
$secret = Read-Host "  SECRET_KEY (FastAPI JWT secret)"
$hfToken = Read-Host "  HF_TOKEN (HuggingFace -- optional, press ENTER to skip)"

$literalArgs = @("--from-literal=POSTGRES_PASSWORD=$pgPass", "--from-literal=SECRET_KEY=$secret")
if ($hfToken -ne "") {
    $literalArgs += "--from-literal=HF_TOKEN=$hfToken"
}

kubectl create secret generic verdict-secrets `
    -n verdict `
    --save-config `
    --dry-run=client `
    -o yaml `
    @literalArgs | kubectl apply -f -

# apply all manifests
Write-Step "Applying all k8s manifests via kustomize"
kubectl apply -k "$k8sDir\"

# install nginx-ingress controller
Write-Step "Installing nginx-ingress controller"
kubectl apply -f "https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/cloud/deploy.yaml"
Write-Host "Waiting for ingress controller to be ready..."
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=3m

# scale vLLM to 0
Write-Step "Scaling vLLM deployments to 0 replicas (GPU nodes are inactive)"
foreach ($dep in @("verdict-vllm-base", "verdict-vllm-kira-blue", "verdict-vllm-kira-green")) {
    kubectl scale deployment $dep -n verdict --replicas=0 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  (skipping $dep -- not found, that's OK)"
    }
}

# run migration job
Write-Step "Running database migration job"
kubectl delete job verdict-migrate -n verdict --ignore-not-found
kubectl apply -f "$k8sDir\migration-job.yaml" -n verdict
kubectl wait --for=condition=complete job/verdict-migrate -n verdict --timeout=3m
Write-Host "Migration complete."

# wait for rollout
Write-Step "Waiting for rollouts"
kubectl rollout status deployment/verdict-api      -n verdict --timeout=5m
kubectl rollout status deployment/verdict-worker   -n verdict --timeout=3m
kubectl rollout status deployment/verdict-frontend -n verdict --timeout=3m

# print ingress IP
Write-Step "Fetching Ingress external IP (may take up to 60s)"
$ip = $null
for ($i = 0; $i -lt 12; $i++) {
    $ip = kubectl get ingress verdict -n verdict -o jsonpath="{.status.loadBalancer.ingress[0].ip}" 2>$null
    if ($ip) { break }
    Write-Host "  Waiting... ($($i * 5)s)"
    Start-Sleep -Seconds 5
}

Write-Host ""
Write-Host "=== Veridict is live on GKE! ===" -ForegroundColor Green
Write-Host ""
if ($ip) {
    Write-Host "  Ingress IP : $ip"
    Write-Host "  Health     : http://$ip/api/health"
    Write-Host "  Frontend   : http://$ip/"
} else {
    Write-Host "  Could not resolve Ingress IP yet."
    Write-Host "  Run: kubectl get ingress verdict -n verdict"
}
Write-Host ""
Write-Host "All pods:"
kubectl get pods -n verdict
