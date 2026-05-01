# DeepSeek Distillation Setup

Use this when labeling Kira distillation data with DeepSeek as the teacher model.

## Model

Set the model to:

```env
DEEPSEEK_MODEL=deepseek-v4-pro
```

DeepSeek's OpenAI-compatible API base URL is `https://api.deepseek.com`. The active labeler uses the OpenAI Python SDK and reads `DEEPSEEK_API_KEY` and `DEEPSEEK_MODEL` from the process environment.

## API Key

Put the key in the repo-root `.env` file:

```env
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-v4-pro
```

Do not put the key in `.gitignore` itself. `.gitignore` should only list file patterns that Git must ignore. This repo ignores `.env`, `.env.*`, `app/backend/.env`, and `app/backend/.env.*`, so the secret belongs in `.env`.

Use `.env.example` as the committed template. It must never contain a real key.

## Load Environment Variables

PowerShell:

```powershell
Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } |
  ForEach-Object { $k,$v = $_ -split '=',2; [System.Environment]::SetEnvironmentVariable($k,$v) }
```

Linux/macOS:

```bash
export $(grep -v '^#' .env | xargs)
```

## Run Labeling

Always start with a small billable smoke test:

```bash
python -m scripts.distill.label_with_deepseek --dry-run
```

Then run the full split labeling:

```bash
python -m scripts.distill.label_with_deepseek --split all
```

Outputs are written to `data/kira/labeled/{train,val,test}.jsonl`. The labeler is resume-safe and skips row IDs already present in the output file.

## Billing

DeepSeek API usage is balance-based. Costs are deducted from granted balance first, then topped-up balance. You should top up before running the full distillation job unless your granted balance is already enough.

Check the current pricing before a full run:

- https://api-docs.deepseek.com/quick_start/pricing
- https://api-docs.deepseek.com/faq/

As of 2026-04-26, the DeepSeek docs list `deepseek-v4-pro` at a limited-time 75% discount until 2026-05-05 15:59 UTC. Prices can change, so verify before starting a large batch.
