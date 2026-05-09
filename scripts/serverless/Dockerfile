FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Minimal runtime deps: Python, curl for health checks, C++ runtime libs for llama-server binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    libgomp1 libstdc++6 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir runpod==1.7.9 requests

COPY handler.py /handler.py

# Environment variables — override in RunPod endpoint configuration per-model
ENV VOLUME_PATH=/runpod-volume
ENV MODEL_PATH=/runpod-volume/harvey_q4km.gguf
ENV PARALLEL=4
ENV CTX_SIZE=32768
ENV PORT=8000

CMD ["python3", "-u", "/handler.py"]
