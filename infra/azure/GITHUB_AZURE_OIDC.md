# GitHub Actions Azure OIDC Setup

Use federated identity instead of long-lived Azure credentials or ACR passwords.

## Required GitHub Secrets

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `MLFLOW_TRACKING_URI`
- `EVAL_ENDPOINT`
- `EVAL_MODEL`
- `VLLM_ENDPOINT`

## Required GitHub Variables

Populate these from `infra/main.bicep` deployment outputs:

- `AZURE_RESOURCE_GROUP`
- `AKS_CLUSTER_NAME`
- `ACR_NAME`
- `ACR_LOGIN_SERVER`
- `DEPLOY_VLLM`

Set `DEPLOY_VLLM=false` until a real vLLM image build exists and the GPU pool is ready.

## Create Federated Azure App

Replace placeholders before running:

```bash
SUBSCRIPTION_ID="<subscription-id>"
RESOURCE_GROUP="veridict-dev-rg"
GITHUB_ORG="<github-org-or-user>"
GITHUB_REPO="<repo-name>"
APP_NAME="veridict-github-actions"

az account set --subscription "$SUBSCRIPTION_ID"

APP_ID=$(az ad app create \
  --display-name "$APP_NAME" \
  --query appId \
  -o tsv)

OBJECT_ID=$(az ad app show \
  --id "$APP_ID" \
  --query id \
  -o tsv)

az ad sp create --id "$APP_ID"

TENANT_ID=$(az account show --query tenantId -o tsv)
```

## Add Federated Credential

This credential allows pushes to `main` to authenticate to Azure.

```bash
cat > federated-credential.json <<EOF
{
  "name": "github-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:${GITHUB_ORG}/${GITHUB_REPO}:ref:refs/heads/main",
  "description": "GitHub Actions main branch deploys",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF

az ad app federated-credential create \
  --id "$OBJECT_ID" \
  --parameters federated-credential.json
```

If you deploy from GitHub Environments instead of directly from `main`, use a subject like:

```text
repo:<org>/<repo>:environment:production
```

## Assign Azure Roles

Grant only the scopes the workflow needs.

```bash
ACR_ID=$(az acr show \
  --resource-group "$RESOURCE_GROUP" \
  --name "<acr-name>" \
  --query id \
  -o tsv)

AKS_ID=$(az aks show \
  --resource-group "$RESOURCE_GROUP" \
  --name "<aks-name>" \
  --query id \
  -o tsv)

RG_ID=$(az group show \
  --name "$RESOURCE_GROUP" \
  --query id \
  -o tsv)

az role assignment create \
  --assignee "$APP_ID" \
  --role AcrPush \
  --scope "$ACR_ID"

az role assignment create \
  --assignee "$APP_ID" \
  --role "Azure Kubernetes Service Cluster User Role" \
  --scope "$AKS_ID"

az role assignment create \
  --assignee "$APP_ID" \
  --role Reader \
  --scope "$RG_ID"
```

Depending on AKS RBAC configuration, you may also need Kubernetes RBAC bindings inside the cluster for the identity that fetches credentials.

## Store Values in GitHub

Secrets:

```text
AZURE_CLIENT_ID=$APP_ID
AZURE_TENANT_ID=$TENANT_ID
AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID
```

Variables:

```text
AZURE_RESOURCE_GROUP=veridict-dev-rg
AKS_CLUSTER_NAME=<aksName output>
ACR_NAME=<acrName output>
ACR_LOGIN_SERVER=<acrLoginServer output>
DEPLOY_VLLM=false
```

## Validate

Push to `main` or run the workflow manually after adding a manual trigger. The build job should:

1. Use `azure/login@v2`.
2. Run `az acr login --name "$ACR_NAME"`.
3. Build and push app images.
4. Run eval gate with required MLflow/eval secrets.
5. Deploy to AKS with `azure/aks-set-context@v3`.
