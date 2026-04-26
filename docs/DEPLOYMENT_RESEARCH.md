# Deployment Research

## Options

| Platform | Fit | Notes |
| --- | --- | --- |
| Modal | Strong | CPU API/worker plus H100/H200 vLLM endpoints; good secrets and scale-to-zero story. |
| RunPod Serverless | Good | GPU availability is strong, but public API and operational polish need more glue. |
| HF Inference Endpoints | Good | Simple model hosting; less flexible for custom multi-role orchestration. |
| Koyeb | Moderate | Good app hosting, less ideal for ≥48GB VRAM inference. |

Gemma 26B generally needs at least 48GB VRAM for comfortable serving, which points to H100/H200 or multi-A100 setups depending on quantization and throughput.

## Recommendation

Use Vercel for the frontend, Modal CPU for FastAPI and worker, Neon Postgres with pgvector, and Modal vLLM on H200 for inference. This keeps the demo cost low while leaving a clean production path.
