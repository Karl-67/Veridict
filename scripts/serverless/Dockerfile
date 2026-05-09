FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libstdc++6 ca-certificates \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir runpod requests

COPY handler.py /handler.py

# Override these per-endpoint in the RunPod environment variables UI
ENV VOLUME_PATH=/runpod-volume
ENV MODEL_PATH=/runpod-volume/harvey_q4km.gguf
ENV PORT=8000
ENV PARALLEL=4
ENV CTX_SIZE=32768
ENV N_GPU_LAYERS=-1

CMD ["python3", "/handler.py"]
