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
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import BATCHES_DIR, RESULTS_DIR
from .oauth import get_access_token

PROGRESS_FILE = RESULTS_DIR / "progress.json"

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
CONCURRENCY = 3      # simultaneous requests
RETRY_LIMIT = 5
RETRY_DELAY = 10.0   # base seconds; doubles each attempt (exponential backoff)
REQUEST_DELAY = 2.0  # seconds between launching each request (global throttle)


# ── Token estimation ──────────────────────────────────────────────────────────


def _estimate_avg_tokens(batch_file: Path) -> int:
    """Estimate average input tokens per call from a batch JSONL file.

    Uses the ~4 chars/token heuristic applied to the concatenated content
    of all message fields in each request body.
    """
    total_chars = 0
    count = 0
    try:
        with open(batch_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                msgs = obj.get("body", {}).get("messages", [])
                total_chars += sum(len(m.get("content", "")) for m in msgs)
                count += 1
    except (OSError, json.JSONDecodeError):
        return 0
    if count == 0:
        return 0
    return (total_chars // 4) // count


# ── Progress tracking ─────────────────────────────────────────────────────────


def _count_done_in_file(out_file: Path) -> tuple[int, int]:
    """Return (done_ok, done_err) from an existing results file."""
    ok = err = 0
    if not out_file.exists():
        return 0, 0
    with open(out_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("error"):
                    err += 1
                else:
                    ok += 1
            except json.JSONDecodeError:
                pass
    return ok, err


def write_progress(file_stats: dict[str, dict]) -> None:
    """Write overall progress summary to data/distillation/results/progress.json.

    file_stats: {batch_filename: {total, done, errors}}
    """
    total  = sum(s["total"]  for s in file_stats.values())
    done   = sum(s["done"]   for s in file_stats.values())
    errors = sum(s.get("errors", 0) for s in file_stats.values())
    pending = total - done
    out = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "files": file_stats,
        "overall": {
            "total":   total,
            "done":    done,
            "pending": pending,
            "errors":  errors,
            "pct_done": f"{done / max(total, 1) * 100:.1f}%",
        },
    }
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


def print_status() -> None:
    """Print progress summary without running any calls."""
    if not PROGRESS_FILE.exists():
        # Build from scratch by scanning batch + result files
        all_files = sorted(BATCHES_DIR.glob("*_batch_*.jsonl"))
        if not all_files:
            print("No batch files found. Run 'build' first.")
            return
        file_stats: dict[str, dict] = {}
        for bf in all_files:
            total = sum(1 for line in open(bf, encoding="utf-8") if line.strip())
            out_file = RESULTS_DIR / f"{bf.stem}_results.jsonl"
            done_ok, done_err = _count_done_in_file(out_file)
            file_stats[bf.name] = {"total": total, "done": done_ok, "errors": done_err}
        write_progress(file_stats)

    with open(PROGRESS_FILE, encoding="utf-8") as f:
        p = json.load(f)

    ov = p.get("overall", {})
    print(f"  Last updated : {p.get('last_updated', 'unknown')}")
    print(f"  Overall      : {ov.get('done',0):>6,} / {ov.get('total',0):>6,} done"
          f"  ({ov.get('pct_done','?')})  pending={ov.get('pending',0):,}"
          f"  errors={ov.get('errors',0)}")
    print()
    # Group by type (reviewer / reviewer_large / validator / sec …)
    for fname, stats in sorted(p.get("files", {}).items()):
        pct = stats["done"] / max(stats["total"], 1) * 100
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"  {fname:<42}  [{bar}] {pct:5.1f}%"
              f"  {stats['done']:>5,}/{stats['total']:>5,}  err={stats.get('errors',0)}")


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

    last_err = "unknown"
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
                        backoff = float(resp.headers.get("retry-after", RETRY_DELAY * (2 ** attempt)))
                        last_err = f"HTTP 429 (rate limited, backing off {backoff:.0f}s)"
                        print(f"\n  [rate limit] {custom_id} attempt {attempt+1}/{RETRY_LIMIT}, sleeping {backoff:.0f}s", flush=True)
                        await asyncio.sleep(backoff)
                        continue

                    if resp.status_code != 200:
                        text = await resp.aread()
                        last_err = f"HTTP {resp.status_code}: {text.decode()[:300]}"
                        if resp.status_code < 500:
                            return wrap_result(custom_id, None, last_err)
                        await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
                        continue

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
                last_err = "timeout"
                if attempt < RETRY_LIMIT - 1:
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
                    continue
                return wrap_result(custom_id, None, "timeout after retries")
            except Exception as e:
                last_err = str(e)
                return wrap_result(custom_id, None, last_err)

    return wrap_result(custom_id, None, f"max retries exceeded — last error: {last_err}")


async def run_batch_file(
    batch_file: Path,
    out_file: Path,
    token: str,
    max_new: int | None,
    remaining_budget: list[int],  # mutable [budget_left] shared across batch files
) -> dict:
    requests = []
    with open(batch_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                requests.append(json.loads(line))

    # Load already-successfully-completed custom_ids for resumption.
    # Errored results are NOT added to done — they get retried on next run.
    done: set[str] = set()
    if out_file.exists():
        with open(out_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        obj = json.loads(line)
                        if not obj.get("error"):
                            done.add(obj["custom_id"])
                    except (KeyError, json.JSONDecodeError):
                        pass

    # pending = not yet successfully completed (includes retries of past errors)
    pending = [r for r in requests if r["custom_id"] not in done]

    # Cap to budget if --max-new was given
    if max_new is not None:
        budget = remaining_budget[0]
        if budget <= 0:
            print(f"  {batch_file.name}: skipped (max-new budget exhausted)")
            return {"total": len(requests), "done": len(done), "new": 0, "errors": 0}
        pending = pending[:budget]

    print(f"  {batch_file.name}: {len(requests)} total, {len(done)} done, {len(pending)} pending")

    if not pending:
        return {"total": len(requests), "done": len(done), "new": 0, "errors": 0}

    sem = asyncio.Semaphore(CONCURRENCY)
    errors = 0
    new_count = 0

    # Worker pool: CONCURRENCY workers each pull from a shared queue.
    # Each worker sleeps REQUEST_DELAY between calls → global throughput ≈
    # CONCURRENCY / REQUEST_DELAY req/s, avoiding burst rate limits.
    work_q: asyncio.Queue = asyncio.Queue()
    result_q: asyncio.Queue = asyncio.Queue()

    for r in pending:
        work_q.put_nowait(r)

    async def _worker(client: httpx.AsyncClient) -> None:
        while True:
            try:
                r = work_q.get_nowait()
            except asyncio.QueueEmpty:
                break
            result = await call_one(client, sem, r["custom_id"], r["body"], token)
            result["request_body"] = r.get("body")
            result_q.put_nowait(result)
            work_q.task_done()
            await asyncio.sleep(REQUEST_DELAY)

    # Write each result to disk immediately — crash-safe per-request checkpointing.
    with open(out_file, "a", encoding="utf-8") as out_f:
        async with httpx.AsyncClient() as client:
            workers = [asyncio.ensure_future(_worker(client)) for _ in range(CONCURRENCY)]

            completed = 0
            while completed < len(pending):
                result = await result_q.get()
                out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                out_f.flush()
                if result["error"]:
                    errors += 1
                new_count += 1
                completed += 1
                if completed % 10 == 0 or completed == len(pending):
                    print(f"    {completed}/{len(pending)}  errors={errors}", end="\r")

            await asyncio.gather(*workers)

    print()

    if max_new is not None:
        remaining_budget[0] -= new_count

    return {
        "total": len(requests),
        "done": len(done) + new_count,
        "new": new_count,
        "errors": errors,
    }


async def run_all(max_new: int | None, account: int | None, auth_file: str | None) -> None:
    print("Authenticating via Codex OAuth...")
    token = get_access_token(auth_file)
    print("  OK\n")

    # Normal batch files first, then _large files (sorted within each group)
    all_files = sorted(BATCHES_DIR.glob("*_batch_*.jsonl"))
    normal_files = [f for f in all_files if "_large_" not in f.name]
    large_files  = [f for f in all_files if "_large_" in f.name]
    all_files_ordered = normal_files + large_files

    if account is not None:
        batch_files = [f for f in all_files_ordered if f.name.startswith(f"account{account}_")]
        if not batch_files:
            sys.exit(f"No batch files matching account{account}_batch_*.jsonl in {BATCHES_DIR}.")
        print(f"Account {account} mode — processing {len(batch_files)} file(s)\n")
    else:
        batch_files = [f for f in all_files_ordered if not f.name.startswith("account")]

    if not batch_files:
        sys.exit(f"No batch files in {BATCHES_DIR}. Run build_batches first.")

    # ── Build initial progress state from disk ──────────────────────────────
    file_stats: dict[str, dict] = {}
    total_pending_before = 0
    for bf in batch_files:
        total = sum(1 for line in open(bf, encoding="utf-8") if line.strip())
        out_file = RESULTS_DIR / f"{bf.stem}_results.jsonl"
        done_ok, done_err = _count_done_in_file(out_file)
        pending = total - done_ok
        file_stats[bf.name] = {"total": total, "done": done_ok, "errors": done_err}
        total_pending_before += pending

    write_progress(file_stats)

    total_done_before = sum(s["done"] for s in file_stats.values())
    total_all = sum(s["total"] for s in file_stats.values())
    print(f"Resume state: {total_done_before:,} / {total_all:,} already done"
          f"  ({total_pending_before:,} pending across {len(batch_files)} file(s))")
    if max_new is not None:
        print(f"Max-new mode: will process at most {max_new} pending requests then stop.")
    if large_files:
        print(f"Large-contract files queued last: {[f.name for f in large_files]}")
    print()

    total_stats = {"total": 0, "new": 0, "errors": 0}
    remaining_budget = [max_new if max_new is not None else 0]

    for batch_file in batch_files:
        out_file = RESULTS_DIR / f"{batch_file.stem}_results.jsonl"
        avg_tokens = _estimate_avg_tokens(batch_file)
        size_tag = " [LARGE — runs last]" if "_large_" in batch_file.name else ""
        print(f"[{batch_file.name}]{size_tag}  avg input tokens/call: ~{avg_tokens:,}")
        stats = await run_batch_file(batch_file, out_file, token, max_new, remaining_budget)
        print(
            f"  Done — new={stats['new']}  errors={stats['errors']}  → {out_file.name}\n"
        )
        total_stats["total"]  += stats["total"]
        total_stats["new"]    += stats["new"]
        total_stats["errors"] += stats["errors"]

        # Update progress file after every batch file so --status always reflects reality
        done_ok, done_err = _count_done_in_file(out_file)
        file_stats[batch_file.name] = {
            "total":  file_stats[batch_file.name]["total"],
            "done":   done_ok,
            "errors": done_err,
        }
        write_progress(file_stats)

        if max_new is not None and remaining_budget[0] <= 0:
            print("Max-new budget reached — stopping early.")
            print(f"  Run again with --max-new N when your limit resets to continue.")
            print(f"  Current progress saved to {PROGRESS_FILE}")
            break

    print("=" * 40)
    print(f"Total: {total_stats['total']}  new={total_stats['new']}  errors={total_stats['errors']}")
    if total_stats["errors"] == 0 and (max_new is None or remaining_budget[0] > 0):
        print("\nAll done. Next: python -m scripts.run_distill parse")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--max-new", type=int, metavar="N",
                        help="Process at most N pending requests this run, then stop. "
                             "Omit to process all pending. Always resumes from checkpoints.")
    parser.add_argument("--account", type=int, choices=[1, 2, 3], metavar="N",
                        help="Run only account N's batch files (account1_batch_*.jsonl etc.)")
    parser.add_argument("--auth-file", metavar="PATH",
                        help="Path to auth.json (default: ~/.codex/auth.json)")
    parser.add_argument("--status", action="store_true",
                        help="Print progress summary and exit without making any calls.")
    args, _ = parser.parse_known_args()

    print("=" * 60)
    print("Run Calls (ChatGPT OAuth backend)")
    print("=" * 60)
    print()

    if args.status:
        print_status()
        return

    asyncio.run(run_all(args.max_new, args.account, args.auth_file))


if __name__ == "__main__":
    main()
