$ErrorActionPreference = "Stop"
$outFile = "$env:TEMP\veridict_deploy.log"

# Refresh PATH from registry so az is found even in newly-opened sessions
$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath    = [System.Environment]::GetEnvironmentVariable("Path", "User")
$env:PATH    = "$machinePath;$userPath"

function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $outFile -Value $line
}

Log "=== Veridict Phase 1 Deployment ==="
Log "Checking Azure CLI..."
$azVersion = az --version 2>&1 | Select-Object -First 1
Log "AZ: $azVersion"

Log "Checking subscription..."
$sub = az account show --query "{name:name, id:id, state:state}" -o json | ConvertFrom-Json
Log "Subscription: $($sub.name) ($($sub.id)) [$($sub.state)]"

Log "Creating resource group veridict-dev-rg in eastus..."
$rg = az group create --name veridict-dev-rg --location eastus -o json | ConvertFrom-Json
Log "Resource group: $($rg.properties.provisioningState)"

Log "Starting Bicep deployment (this takes 10-15 minutes)..."
$deployment = az deployment group create `
    --resource-group veridict-dev-rg `
    --template-file infra/main.bicep `
    --parameters "@infra/dev.parameters.json" `
    --name main `
    -o json | ConvertFrom-Json

$state = $deployment.properties.provisioningState
Log "Deployment state: $state"

if ($state -ne "Succeeded") {
    Log "ERROR: Deployment failed. Check Azure portal for details."
    exit 1
}

Log "Getting deployment outputs..."
$outputs = $deployment.properties.outputs
$acrLoginServer = $outputs.acrLoginServer.value
$acrName        = $outputs.acrName.value
$aksName        = $outputs.aksName.value
$mlWorkspace    = $outputs.mlWorkspaceName.value

Log "ACR Login Server: $acrLoginServer"
Log "ACR Name:         $acrName"
Log "AKS Name:         $aksName"
Log "ML Workspace:     $mlWorkspace"

# Save outputs for next steps
@{
    acrLoginServer = $acrLoginServer
    acrName        = $acrName
    aksName        = $aksName
    mlWorkspace    = $mlWorkspace
} | ConvertTo-Json | Set-Content "$env:TEMP\veridict_outputs.json"

Log "Outputs saved to $env:TEMP\veridict_outputs.json"
Log "=== Phase 1 infra provisioning COMPLETE ==="
Log "Next step: run deploy_phase1_images.ps1 to build and push Docker images"
