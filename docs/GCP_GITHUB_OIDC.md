# GCP Workload Identity Federation for GitHub Actions

This guide sets up keyless authentication between GitHub Actions and GCP using
Workload Identity Federation (OIDC). No long-lived service account keys are stored
in GitHub secrets.

---

## Prerequisites

- GCP project `veridict-dev` exists and billing is enabled.
- You have Owner or IAM Admin permissions on the project.
- `gcloud` CLI is authenticated: `gcloud auth login`.

---

## Step 1 — Enable required APIs

```bash
gcloud config set project veridict-dev

gcloud services enable \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  cloudresourcemanager.googleapis.com
```

---

## Step 2 — Create a Workload Identity Pool

```bash
gcloud iam workload-identity-pools create "github-pool" \
  --project="veridict-dev" \
  --location="global" \
  --display-name="GitHub Actions pool"
```

Get the pool name (you will need it later):

```bash
gcloud iam workload-identity-pools describe "github-pool" \
  --project="veridict-dev" \
  --location="global" \
  --format="value(name)"
# → projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool
```

---

## Step 3 — Create a Workload Identity Provider

Replace `YOUR_GITHUB_ORG_OR_USER` with your GitHub username or organisation.

```bash
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project="veridict-dev" \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub OIDC provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.actor=assertion.actor" \
  --attribute-condition="assertion.repository == 'YOUR_GITHUB_ORG_OR_USER/Veridict'"
```

Get the full provider resource name:

```bash
gcloud iam workload-identity-pools providers describe "github-provider" \
  --project="veridict-dev" \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --format="value(name)"
# → projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider
```

This is the value you set as `GCP_WORKLOAD_IDENTITY_PROVIDER` in GitHub secrets.

---

## Step 4 — Create a GitHub Actions Service Account

```bash
gcloud iam service-accounts create "github-actions" \
  --project="veridict-dev" \
  --display-name="GitHub Actions CI/CD SA"
```

Grant it the roles needed for CI/CD:

```bash
PROJECT_ID="veridict-dev"
SA="github-actions@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/container.developer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/storage.objectAdmin"
```

---

## Step 5 — Allow the Workload Identity Pool to impersonate the SA

Replace `PROJECT_NUMBER` with your GCP project number
(`gcloud projects describe veridict-dev --format="value(projectNumber)"`).

```bash
PROJECT_NUMBER=$(gcloud projects describe veridict-dev --format="value(projectNumber)")
SA="github-actions@veridict-dev.iam.gserviceaccount.com"

gcloud iam service-accounts add-iam-policy-binding $SA \
  --project="veridict-dev" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/YOUR_GITHUB_ORG_OR_USER/Veridict"
```

---

## Step 6 — Set GitHub Secrets and Variables

In your GitHub repository → Settings → Secrets and variables → Actions:

### Secrets

| Name | Value |
|------|-------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full provider resource name from Step 3 |
| `GCP_SERVICE_ACCOUNT` | `github-actions@veridict-dev.iam.gserviceaccount.com` |
| `MLFLOW_TRACKING_URI` | Your MLflow server URI |
| `EVAL_ENDPOINT` | Staging inference endpoint (or leave empty to skip eval gate) |
| `EVAL_MODEL` | Model name for eval gate |

### Variables

| Name | Value |
|------|-------|
| `GCP_PROJECT_ID` | `veridict-dev` |
| `GAR_REGISTRY` | `europe-west1-docker.pkg.dev/veridict-dev/veridict` |
| `GKE_CLUSTER_NAME` | `veridict-dev-gke` |
| `GKE_REGION` | `europe-west1` |
| `DEPLOY_VLLM` | `false` |

---

## Step 7 — Test the integration

Push a commit to `main` and watch the **Build and Deploy to GKE** workflow.
The `Authenticate to GCP` step should complete without errors.

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `iam.workloadIdentityPools is not enabled` | Run Step 1 (enable APIs) |
| `attribute.repository` mismatch | Ensure attribute condition matches `YOUR_GITHUB_ORG_OR_USER/Veridict` exactly |
| `Permission denied on resource project` | Check SA roles in Step 4 |
| `The caller does not have permission` | Re-run Step 5 with the correct `PROJECT_NUMBER` |
