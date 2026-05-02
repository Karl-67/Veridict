$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath    = [System.Environment]::GetEnvironmentVariable("Path", "User")
$env:PATH    = "$machinePath;$userPath"

Write-Host "=== Querying allowed regions from sys.regionrestriction policy ==="
Write-Host ""

# Show the full policy assignment JSON
$raw = az policy assignment show --name "sys.regionrestriction" -o json
Write-Host "Raw policy assignment:"
Write-Host $raw
Write-Host ""

# Parse and show parameters
$policy = $raw | ConvertFrom-Json
Write-Host "Parameters object:"
$policy.parameters | ConvertTo-Json -Depth 5
