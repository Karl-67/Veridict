$ErrorActionPreference = "Stop"
$outFile = "$env:TEMP\veridict_deploy_images.log"
$projectRoot = $PSScriptRoot

# Refresh PATH from registry
$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath    = [System.Environment]::GetEnvironmentVariable("Path", "User")
$env:PATH    = "$machinePath;$userPath"

function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $outFile -Value $line
}

# Load outputs from Phase 1 infra
$outputs = Get-Content "$env:TEMP\veridict_outputs.json" | ConvertFrom-Json
$acrLoginServer = $outputs.acrLoginServer
$acrName        = $outputs.acrName
$aksName        = $outputs.aksName

Log "=== Veridict Phase 1 — Docker Images + K8s ==="
Log "ACR: $acrLoginServer"
Log "AKS: $aksName"

# ── Step 1: Login to ACR ────────────────────────────────────────────────────
Log "Logging in to ACR..."
az acr login --name $acrName
Log "ACR login OK"

# ── Step 2: Build and push images ───────────────────────────────────────────
$images = @(
    @{ tag = "verdict-api";      dockerfile = "Dockerfile.api" },
    @{ tag = "verdict-worker";   dockerfile = "Dockerfile.worker" },
    @{ tag = "verdict-frontend"; dockerfile = "Dockerfile.frontend" }
)

foreach ($img in $images) {
    $fullTag = "${acrLoginServer}/$($img.tag):latest"
    Log "Building $fullTag from $($img.dockerfile)..."
    docker build -f $img.dockerfile -t $fullTag .
    Log "Pushing $fullTag..."
    docker push $fullTag
    Log "$($img.tag) pushed OK"
}

# ── Step 3: Update k8s manifests with real ACR name ─────────────────────────
Log "Patching k8s manifests: replacing verdictacr.azurecr.io with $acrLoginServer..."
$manifestFiles = Get-ChildItem -Path "$projectRoot\k8s" -Filter "*.yaml"
foreach ($f in $manifestFiles) {
    $content = Get-Content $f.FullName -Raw
    if ($content -match "verdictacr\.azurecr\.io") {
        $updated = $content -replace "verdictacr\.azurecr\.io", $acrLoginServer
        Set-Content -Path $f.FullName -Value $updated -NoNewline
        Log "  Patched: $($f.Name)"
    }
}

# ── Step 4: Get AKS credentials ─────────────────────────────────────────────
Log "Getting AKS credentials..."
az aks get-credentials --resource-group veridict-dev-rg --name $aksName --overwrite-existing
Log "kubectl configured for $aksName"

# ── Step 5: Create Kubernetes secret with real values ───────────────────────
Log "Creating Kubernetes namespace (if not exists)..."
kubectl apply -f "$projectRoot\k8s\namespace.yaml"

$pgPass  = -join ((1..32) | ForEach-Object { "{0:x}" -f (Get-Random -Max 16) })
$secretKey = -join ((1..64) | ForEach-Object { "{0:x}" -f (Get-Random -Max 16) })
$grafanaPass = -join ((1..24) | ForEach-Object { "{0:x}" -f (Get-Random -Max 16) })

Log "Postgres password (SAVE THIS): $pgPass"
Log "Grafana password (SAVE THIS):  $grafanaPass"

# Save credentials to a local file (never commit this)
@"
POSTGRES_PASSWORD=$pgPass
POSTGRES_DSN=postgresql://verdict:${pgPass}@verdict-postgres:5432/verdict
SECRET_KEY=$secretKey
GRAFANA_ADMIN_PASSWORD=$grafanaPass
HF_TOKEN=placeholder-set-after-fine-tuning
"@ | Set-Content "$projectRoot\.deployment_secrets.txt"
Log "Credentials saved to .deployment_secrets.txt — DO NOT commit this file"

kubectl create secret generic verdict-secrets -n verdict `
    --from-literal="POSTGRES_PASSWORD=$pgPass" `
    --from-literal="POSTGRES_DSN=postgresql://verdict:${pgPass}@verdict-postgres:5432/verdict" `
    --from-literal="SECRET_KEY=$secretKey" `
    --from-literal="HF_TOKEN=placeholder-set-after-fine-tuning" `
    --from-literal="GRAFANA_ADMIN_PASSWORD=$grafanaPass" `
    --dry-run=client -o yaml | kubectl apply -f -

Log "Secret created"

# ── Step 6: Apply all manifests ─────────────────────────────────────────────
Log "Applying all k8s manifests via kustomize..."
kubectl apply -k "$projectRoot\k8s\"
Log "Manifests applied"

# ── Step 7: Scale vLLM to 0 (no GPU nodes yet) ──────────────────────────────
Log "Scaling vLLM deployments to 0 (dormant — no GPU yet)..."
kubectl scale deployment/verdict-vllm-base  --replicas=0 -n verdict
kubectl scale deployment/verdict-vllm-kira  --replicas=0 -n verdict
kubectl scale deployment/verdict-vllm-kira-green --replicas=0 -n verdict 2>$null
Log "vLLM deployments scaled to 0"

# ── Step 8: Run database migration ──────────────────────────────────────────
Log "Waiting for API pods to be ready (up to 3 min)..."
kubectl rollout status deployment/verdict-api -n verdict --timeout=180s

Log "Running database migration job..."
kubectl apply -f "$projectRoot\k8s\migration-job.yaml" -n verdict
kubectl wait --for=condition=complete job/verdict-migrate -n verdict --timeout=180s
Log "Migration complete"

# ── Step 9: Get public IP ────────────────────────────────────────────────────
Log "Getting ingress public IP (may take a minute to provision)..."
Start-Sleep -Seconds 30
$ip = kubectl get ingress verdict -n verdict -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>$null
if ($ip) {
    Log "Public IP: $ip"
    Log "Frontend:  http://$ip"
    Log "API health: http://$ip/api/health"
} else {
    Log "Ingress IP not yet assigned — run: kubectl get ingress verdict -n verdict"
}

# ── Final status ─────────────────────────────────────────────────────────────
Log ""
Log "=== Pod status ==="
kubectl get pods -n verdict

Log ""
Log "=== Phase 1 COMPLETE ==="
Log "All CPU workloads are running. vLLM pods are dormant (0 replicas) — expected."
Log "LLM pipeline stages will fail until Phase 2 (GPU nodes + fine-tuned model)."
