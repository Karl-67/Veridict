# Azure LLMOps Checklist

## 1. Provision Azure Baseline

- Deploy `infra/main.bicep`.
- Capture deployment outputs.
- Confirm resources exist:
  - ACR
  - AKS
  - Azure ML workspace
  - Storage account
  - Key Vault
  - Log Analytics
  - Application Insights

## 2. Configure MLflow

- Get Azure ML `mlflow_tracking_uri`.
- Set local environment:

```bash
export MLFLOW_TRACKING_URI="<azure-mlflow-uri>"
export MLFLOW_EXPERIMENT="veridict-training"
```

- Add GitHub secret:
  - `MLFLOW_TRACKING_URI`

- Treat the first/manual RunPod training as the legacy baseline.
- Future training/eval runs should log to Azure MLflow.

## 3. Configure GitHub to Azure

Target state:

- GitHub OIDC login to Azure.
- No long-lived ACR username/password.
- GitHub Actions can:
  - build images
  - push to ACR
  - set AKS context
  - deploy Kustomize manifests

Setup guide: `docs/GITHUB_AZURE_OIDC.md`.

Current workflow expects OIDC secrets:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

And repo variables:

- `AZURE_RESOURCE_GROUP`
- `AKS_CLUSTER_NAME`
- `ACR_NAME`
- `ACR_LOGIN_SERVER`
- `DEPLOY_VLLM`

Deployment/eval secrets:

- `MLFLOW_TRACKING_URI`
- `EVAL_ENDPOINT`
- `EVAL_MODEL`
- `VLLM_ENDPOINT`

## 4. Make Eval Gate Strict for Production

Production deployment should fail if any are missing:

- `MLFLOW_TRACKING_URI`
- `EVAL_ENDPOINT`
- `EVAL_MODEL`
- golden dataset

The current local/dev behavior may keep optional live eval, but production deploy should not.

Required metrics:

- Kira issue-type F1 or accuracy threshold
- Validator score threshold
- JSON validity / failure rate
- hallucination / citation failure rate
- p95 latency
- token usage
- estimated cost

## 5. Deploy App Manifests

- Build/push images to ACR.
- `kubectl apply -k k8s/`.
- Run migration job.
- Verify API/worker/frontend.
- Keep vLLM replicas at 0 until GPU pool and adapter are ready.

## 6. Activate GPU + vLLM

- Scale AKS GPU node pool from 0 to 1 or 2.
- Confirm NVIDIA device plugin availability.
- Scale `verdict-vllm-base`.
- Enable Kira LoRA args only after adapter is present:
  - `--enable-lora`
  - `--lora-modules`
  - `kira=/mnt/kira-adapter`
- Scale/promote Kira through blue-green script.

## 7. Azure Observability

- Keep app `/metrics` endpoints.
- Prefer Azure Monitor managed Prometheus for long-term AKS metrics.
- Add Application Insights OpenTelemetry instrumentation for:
  - API request traces
  - worker stage spans
  - LLM provider calls
  - RAG retrieval spans
  - eval/promotion events

## 8. Policy Versioning + Re-index Gate

- Store policy/version metadata in Git and DB.
- Store raw policy/RAG artifacts in Azure Storage.
- On policy change:
  - create new version
  - run indexing
  - evaluate golden set
  - log results to MLflow
  - deploy only if gate passes
