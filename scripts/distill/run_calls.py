#!/usr/bin/env python3
"""
run_calls.py — Execute batch JSONL requests against the ChatGPT backend API
               using Codex OAuth (no API billing account needed).

Replaces submit_batches + poll_batches for the OAuth path.
Reads:   data/distillation/batches/{reviewer,validator,sec}_batch_*.jsonl
Writes:  data/distillation/results/{reviewer,validator,sec}_batch_*_results.jsonl

Output format is identical to the OpenAI Batch API output so parse_results.py
works unchanged.

The ChatGPT backend uses the Responses API endpoint:
  POST https://chatgpt.com/backend-api/codex/responses

Usage:
  python -m scripts.run_distill calls              # run all batches
  python -m scripts.run_distill calls --dry-run 5  # test first 5 requests
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

from .config import BATCHES_DIR, RESULTS_DIR
from .oauth import get_access_token

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
CONCURRENCY = 8      # simultaneous requests
RETRY_LIMIT = 3
RETRY_DELAY = 2.0    # seconds between retries


# ── Request conversion ────────────────────────────────────────────────────────

def chat_to_responses_body(chat_body: dict) -> dict:
    """Convert Chat Completions body → ChatGPT Codex backend Responses API body.

    Required fields discovered via probing:
      - instructions  (system prompt, separate from input)
      - input         (list of user messages only)
      - stream=True   (endpoint requires streaming)
      - store=False   (must be explicit)
    Unsupported: max_output_tokens, response_format (use instructions instead)
    """
    messages = chat_body.get("messages", [])
    system_msgs = [m["content"] for m in messages if m["role"] == "system"]
    user_msgs   = [m for m in messages if m["role"] != "system"]

    instructions = " ".join(system_msgs) if system_msgs else "You are a helpful assistant."
    # Append JSON instruction since response_format is unsupported
    instructions += " Always respond with valid JSON only. No text outside the JSON object."

    return {
        "model": chat_body["model"],
        "instructions": instructions,
        "input": user_msgs if user_msgs else [{"role": "user", "content": ""}],
        "stream": True,
        "store": False,
    }


def wrap_result(custom_id: str, content: str | None, error: str | None) -> dict:
    """Wrap into the same shape OpenAI Batch API returns."""
    if error:
        return {
            "custom_id": custom_id,
            "response": None,
            "error": {"message": error},
        }
    return {
        "custom_id": custom_id,
        "response": {
            "body": {
                "choices": [
                    {"message": {"content": content}}
                ]
            }
        },
        "error": None,
    }


# ── Async caller ──────────────────────────────────────────────────────────────

async def call_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    custom_id: str,
    body: dict,
    token: str,
) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "responses=experimental",
    }
    responses_body = chat_to_responses_body(body)

    for attempt in range(RETRY_LIMIT):
        async with sem:
            try:
                async with client.stream(
                    "POST",
                    CODEX_URL,
                    headers=headers,
                    json=responses_body,
                    timeout=60,
                ) as resp:
                    if resp.status_code == 429:
                        retry_after = float(resp.headers.get("retry-after", RETRY_DELAY * (attempt + 1)))
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status_code != 200:
                        text = await resp.aread()
                        return wrap_result(custom_id, None, f"HTTP {resp.status_code}: {text.decode()[:200]}")

                    # Collect text deltas from SSE stream
                    full_text = ""
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "response.output_text.delta":
                            full_text += event.get("delta", "")
                        elif event.get("type") == "response.failed":
                            err = event.get("response", {}).get("error", {})
                            return wrap_result(custom_id, None, str(err))

                    return wrap_result(custom_id, full_text.strip(), None)

            except httpx.TimeoutException:
                if attempt < RETRY_LIMIT - 1:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                return wrap_result(custom_id, None, "timeout after retries")
            except Exception as e:
                return wrap_result(custom_id, None, str(e))

    return wrap_result(custom_id, None, "max retries exceeded")


async def run_batch_file(
    batch_file: Path,
    out_file: Path,
    token: str,
    dry_run: int | None,
) -> dict:
    requests = []
    with open(batch_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                requests.append(json.loads(line))

    if dry_run:
        requests = requests[:dry_run]

    # Skip already-done requests
    done: dict[str, dict] = {}
    if out_file.exists():
        with open(out_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    done[obj["custom_id"]] = obj

    pending = [r for r in requests if r["custom_id"] not in done]
    print(f"  {batch_file.name}: {len(requests)} total, {len(done)} done, {len(pending)} pending")

    if not pending:
        return {"total": len(requests), "done": len(done), "new": 0, "errors": 0}

    sem = asyncio.Semaphore(CONCURRENCY)
    errors = 0
    new_results = []

    async with httpx.AsyncClient() as client:
        tasks = [
            call_one(client, sem, r["custom_id"], r["body"], token)
            for r in pending
        ]

        completed = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            new_results.append(result)
            if result["error"]:
                errors += 1
            completed += 1
            if completed % 100 == 0 or completed == len(tasks):
                print(f"    {completed}/{len(tasks)}  errors={errors}", end="\r")

    print()

    # Append new results to output file
    with open(out_file, "a", encoding="utf-8") as f:
        for r in new_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "total": len(requests),
        "done": len(done) + len(new_results),
        "new": len(new_results),
        "errors": errors,
    }


async def run_all(dry_run: int | None) -> None:
    print("Authenticating via Codex OAuth...")
    token = get_access_token()
    print("  OK\n")

    batch_files = sorted(BATCHES_DIR.glob("*_batch_*.jsonl"))
    if not batch_files:
        sys.exit(f"No batch files in {BATCHES_DIR}. Run build_batches first.")

    total_stats = {"total": 0, "new": 0, "errors": 0}

    for batch_file in batch_files:
        out_file = RESULTS_DIR / f"{batch_file.stem}_results.jsonl"
        print(f"[{batch_file.name}]")
        stats = await run_batch_file(batch_file, out_file, token, dry_run)
        print(f"  Done — new={stats['new']}  errors={stats['errors']}  → {out_file.name}\n")
        total_stats["total"]  += stats["total"]
        total_stats["new"]    += stats["new"]
        total_stats["errors"] += stats["errors"]

    print("=" * 40)
    print(f"Total: {total_stats['total']}  new={total_stats['new']}  errors={total_stats['errors']}")
    if total_stats["errors"] == 0:
        print("\nAll done. Next: python -m scripts.run_distill parse")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", type=int, metavar="N",
                        help="Only process first N requests per batch (for testing)")
    args = parser.parse_args()

    print("=" * 60)
    print("Run Calls (ChatGPT OAuth backend)")
    print("=" * 60)
    print()

    asyncio.run(run_all(args.dry_run))


if __name__ == "__main__":
    main()
