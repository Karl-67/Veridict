"""
RunPod Serverless worker for llama.cpp (Harvey and Kira).

Configured via environment variables set in the RunPod endpoint UI:
  MODEL_PATH   - path to the GGUF model on the network volume
  VOLUME_PATH  - network volume mount point (auto-discovered if not set)
  PARALLEL     - number of parallel request slots (default: 4 for Harvey, 1 for Kira)
  CTX_SIZE     - context window size (default: 32768)
  N_GPU_LAYERS - GPU layers to offload (-1 = all, default: -1)
  PORT         - llama-server port (default: 8000)

Eager-start design: llama-server starts in a background thread at module load time,
before RunPod registers the worker. This ensures the worker is ready to handle
requests immediately when RunPod sends the first job, preventing the endpoint from
staying stuck in "Initializing".
"""
import os
import re
import subprocess
import threading
import time
import requests
import runpod


# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------
def _discover_volume() -> str:
    explicit = os.environ.get("VOLUME_PATH", "")
    candidates = [c for c in [explicit, "/runpod-volume", "/workspace"] if c]
    for vol in candidates:
        if os.path.exists(f"{vol}/llama.cpp/build/bin/llama-server"):
            if explicit and vol != explicit:
                print(f"[worker] VOLUME_PATH={explicit!r} has no llama-server; found it at {vol!r}")
            return vol
    fallback = explicit or "/runpod-volume"
    print(f"[worker] WARNING: llama-server not found in {candidates}; falling back to {fallback!r}")
    return fallback


def _resolve_model(volume: str) -> str:
    explicit = os.environ.get("MODEL_PATH", "")
    if not explicit:
        return f"{volume}/harvey_q4km.gguf"
    if os.path.exists(explicit):
        return explicit
    # Fix wrong volume prefix
    fixed = re.sub(r"^(/runpod-volume|/workspace)", volume, explicit)
    if os.path.exists(fixed):
        print(f"[worker] MODEL_PATH={explicit!r} not found; using {fixed!r}")
        return fixed
    return explicit  # return as-is; pre-flight will surface the error


def _get_diagnostics(volume: str) -> dict:
    diag: dict = {}
    for p in [volume, "/runpod-volume", "/workspace"]:
        try:
            diag[f"ls:{p}"] = sorted(os.listdir(p))
        except Exception as e:
            diag[f"ls:{p}"] = str(e)
    diag["env"] = {k: os.environ.get(k, "") for k in
                   ["VOLUME_PATH", "MODEL_PATH", "PORT", "PARALLEL", "CTX_SIZE", "N_GPU_LAYERS"]}
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        diag["nvidia_smi"] = r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        diag["nvidia_smi"] = str(e)
    return diag


# ---------------------------------------------------------------------------
# Global server state
# ---------------------------------------------------------------------------
_server = None       # subprocess.Popen once running
_start_error = None  # str if startup failed
_volume = None       # resolved volume path
_model = None        # resolved model path


def _start_server():
    """Start llama-server. Called once in a background thread at module load."""
    global _server, _start_error, _volume, _model

    try:
        _volume = _discover_volume()
        _model  = _resolve_model(_volume)
        llama   = f"{_volume}/llama.cpp/build/bin/llama-server"
        no_think = f"{_volume}/no_think.jinja"
        port     = int(os.environ.get("PORT",        "8000"))
        parallel = int(os.environ.get("PARALLEL",    "1"))
        ctx      = int(os.environ.get("CTX_SIZE",    "32768"))
        n_gpu    = int(os.environ.get("N_GPU_LAYERS", "-1"))
        log      = "/tmp/llama_worker.log"

        print(f"[worker] volume={_volume!r} model={_model!r}")
        print(f"[worker] exists: llama={os.path.exists(llama)} model={os.path.exists(_model)} no_think={os.path.exists(no_think)}")

        # Pre-flight
        missing = [p for p in [llama, _model] if not os.path.exists(p)]
        if missing:
            raise RuntimeError(
                f"Required files missing: {missing}\n"
                f"Diagnostics: {_get_diagnostics(_volume)}"
            )

        cmd = [
            llama,
            "--model", _model,
            "--port", str(port),
            "--host", "0.0.0.0",
            "--ctx-size", str(ctx),
            "--n-predict", "-1",
            "--parallel", str(parallel),
            "--n-gpu-layers", str(n_gpu),
        ]
        if os.path.exists(no_think):
            cmd += ["--chat-template-file", no_think]

        # Shared libs (.so) are in build/bin alongside the binary — add to LD_LIBRARY_PATH
        env = os.environ.copy()
        bin_dir = f"{_volume}/llama.cpp/build/bin"
        extra_dirs = [bin_dir, f"{_volume}/llama.cpp/build/lib", f"{_volume}/llama.cpp/build/lib64"]
        ld_extra = ":".join(d for d in extra_dirs if os.path.exists(d))
        if ld_extra:
            env["LD_LIBRARY_PATH"] = ld_extra + ":" + env.get("LD_LIBRARY_PATH", "")
            print(f"[worker] LD_LIBRARY_PATH={env['LD_LIBRARY_PATH']!r}")
        else:
            print(f"[worker] WARNING: no lib dirs found under {_volume}/llama.cpp/build/")

        print(f"[worker] Starting: {' '.join(cmd)}")
        log_fh = open(log, "w")
        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT, env=env)
        print(f"[worker] pid={proc.pid}, polling /health ...")

        for i in range(180):  # 15 min max
            if proc.poll() is not None:
                log_fh.flush()
                with open(log) as f:
                    tail = "".join(f.readlines()[-60:])
                raise RuntimeError(
                    f"llama-server exited (code={proc.returncode}) after {i*5}s.\n"
                    f"--- last 60 log lines ---\n{tail}"
                )
            try:
                if requests.get(f"http://localhost:{port}/health", timeout=2).ok:
                    print(f"[worker] llama-server healthy after {i*5}s")
                    _server = proc
                    return
            except Exception:
                pass
            if i % 12 == 11:
                print(f"[worker] still waiting... ({(i+1)*5}s)")
            time.sleep(5)

        raise RuntimeError("llama-server timed out (15 min)")

    except Exception as e:
        _start_error = str(e)
        print(f"[worker] STARTUP FAILED: {_start_error}")


# ---------------------------------------------------------------------------
# Eager startup — begin before RunPod registers the worker
# ---------------------------------------------------------------------------
_startup_thread = threading.Thread(target=_start_server, daemon=True)
_startup_thread.start()


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------
def handler(job):
    # Wait for llama-server to finish starting (up to 15 min)
    _startup_thread.join(timeout=900)

    if _start_error:
        vol = _volume or os.environ.get("VOLUME_PATH", "/runpod-volume")
        return {"error": "llama-server failed to start", "detail": _start_error,
                "diagnostics": _get_diagnostics(vol)}

    if _server is None:
        return {"error": "llama-server not ready yet — worker still starting up"}

    if _server.poll() is not None:
        return {"error": "llama-server process has exited — worker needs restart"}

    port = int(os.environ.get("PORT", "8000"))
    try:
        resp = requests.post(
            f"http://localhost:{port}/v1/chat/completions",
            json=job["input"],
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        return {"error": f"llama-server HTTP {e.response.status_code}: {e.response.text[:500]}"}
    except Exception as e:
        return {"error": str(e)}


runpod.serverless.start({"handler": handler})
