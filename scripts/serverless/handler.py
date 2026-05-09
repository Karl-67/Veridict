"""
RunPod Serverless worker for llama.cpp (Harvey and Kira).

Configured entirely via environment variables set in the RunPod endpoint UI:
  MODEL_PATH   - path to the GGUF model on the network volume
  VOLUME_PATH  - network volume mount point (default: /runpod-volume)
  PARALLEL     - number of parallel request slots (default: 4 for Harvey, 1 for Kira)
  CTX_SIZE     - context window size (default: 32768)
  PORT         - llama-server port (default: 8000)

The worker starts llama-server once on container init (cold start), then stays warm
to serve subsequent requests. RunPod's idle timeout controls how long it stays warm.
"""
import os
import subprocess
import time
import requests
import runpod

VOLUME   = os.environ.get("VOLUME_PATH", "/runpod-volume")
MODEL    = os.environ.get("MODEL_PATH",  f"{VOLUME}/harvey_q4km.gguf")
NO_THINK = f"{VOLUME}/no_think.jinja"
LLAMA    = f"{VOLUME}/llama.cpp/build/bin/llama-server"
PORT     = int(os.environ.get("PORT",     "8000"))
PARALLEL = int(os.environ.get("PARALLEL", "4"))
CTX      = int(os.environ.get("CTX_SIZE", "32768"))
LOG      = f"{VOLUME}/llama_worker.log"

# ---------------------------------------------------------------------------
# Cold start: launch llama-server and wait for it to be healthy.
# This runs once per worker lifetime; RunPod keeps the worker alive between
# requests up to the configured idle timeout.
# ---------------------------------------------------------------------------
def _start():
    print(f"[worker] Starting llama-server — model={MODEL} port={PORT} parallel={PARALLEL}")
    log_fh = open(LOG, "a")
    proc = subprocess.Popen(
        [
            LLAMA,
            "--model",              MODEL,
            "--port",               str(PORT),
            "--host",               "0.0.0.0",
            "--ctx-size",           str(CTX),
            "--n-predict",          "-1",
            "--parallel",           str(PARALLEL),
            "--chat-template-file", NO_THINK,
        ],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    print(f"[worker] llama-server pid={proc.pid}, polling /health ...")

    for i in range(180):  # max 15 min
        if proc.poll() is not None:
            log_fh.flush()
            with open(LOG) as f:
                tail = "".join(f.readlines()[-40:])
            raise RuntimeError(
                f"llama-server exited early (code={proc.returncode}).\n"
                f"Last 40 log lines:\n{tail}"
            )
        try:
            if requests.get(f"http://localhost:{PORT}/health", timeout=2).ok:
                print(f"[worker] llama-server healthy after {i * 5}s")
                return proc
        except Exception:
            pass
        if i % 12 == 11:
            print(f"[worker] still waiting... ({(i+1)*5}s elapsed)")
        time.sleep(5)

    raise RuntimeError("llama-server failed to become healthy within 15 minutes")


_server = _start()


# ---------------------------------------------------------------------------
# Request handler — called for every job by RunPod.
# Proxies the OpenAI-compatible payload to the local llama-server.
# ---------------------------------------------------------------------------
def handler(job):
    payload = job["input"]

    if _server.poll() is not None:
        return {"error": "llama-server process has exited — worker needs restart"}

    try:
        resp = requests.post(
            f"http://localhost:{PORT}/v1/chat/completions",
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        return {"error": f"llama-server HTTP error {e.response.status_code}: {e.response.text[:500]}"}
    except Exception as e:
        return {"error": str(e)}


runpod.serverless.start({"handler": handler})
