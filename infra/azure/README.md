# Azure Infrastructure

This folder provisions the Azure baseline for Veridict:

- Azure Container Registry
- AKS with Workload Identity enabled
- Optional GPU node pool for vLLM
- Azure Machine Learning workspace for MLflow tracking/model registry
- Storage account with `datasets`, `artifacts`, and `rag` containers
- Key Vault
- Log Analytics
- Application Insights

## Prerequisites

```bash
az login
az account set --subscription "<subscription-id-or-name>"
```

Install the Azure ML extension if you want to fetch the MLflow tracking URI through the CLI:

```bash
az extension add -n ml
az extension update -n ml
```

## Deploy

```bash
az group create \
  --name veridict-dev-rg \
  --location eastus

az deployment group create \
  --resource-group veridict-dev-rg \
  --template-file infra/main.bicep \
  --parameters @infra/dev.parameters.json
```

The dev parameter file creates the GPU node pool at `0` nodes. Scale it up only when vLLM is ready to run.

## Read Outputs

```bash
az deployment group show \
  --resource-group veridict-dev-rg \
  --name main \
  --query properties.outputs
```

Important outputs:

- `acrLoginServer`
- `aksName`
- `mlWorkspaceName`
- `appInsightsConnectionString`
- `keyVaultName`
- `storageAccountName`

## Get Kubeconfig

```bash
az aks get-credentials \
  --resource-group veridict-dev-rg \
  --name <aksName>
```

## Get Azure MLflow Tracking URI

```bash
az ml workspace show \
  --resource-group veridict-dev-rg \
  --name <mlWorkspaceName> \
  --query mlflow_tracking_uri \
  -o tsv
```

Set this as:

```bash
export MLFLOW_TRACKING_URI="<the-uri-from-above>"
export MLFLOW_EXPERIMENT="veridict-training"
```

For GitHub Actions, store it as `MLFLOW_TRACKING_URI`.

## Scale GPU Pool

Scale up for vLLM:

```bash
az aks nodepool scale \
  --resource-group veridict-dev-rg \
  --cluster-name <aksName> \
  --name gpu \
  --node-count 1
```

Scale back down to stop GPU VM billing:

```bash
az aks nodepool scale \
  --resource-group veridict-dev-rg \
  --cluster-name <aksName> \
  --name gpu \
  --node-count 0
```

## GitHub Secrets / Variables

Use GitHub OIDC into Azure instead of ACR username/password. See `docs/GITHUB_AZURE_OIDC.md`.

Secrets:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `MLFLOW_TRACKING_URI`
- `EVAL_ENDPOINT`
- `EVAL_MODEL`
- `VLLM_ENDPOINT`

Variables:

- `AZURE_RESOURCE_GROUP`
- `AKS_CLUSTER_NAME`
- `ACR_NAME`
- `ACR_LOGIN_SERVER`
- `DEPLOY_VLLM`
