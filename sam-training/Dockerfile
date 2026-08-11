# SAM 3 requires transformers >= 5.x, which needs Python 3.12+ — hence 3.12
# rather than the 3.11 the other support modules use.
FROM python:3.12-slim

# OpenCV needs libGL + libglib2
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Torch first and on its own layer: it is ~3 GB and never changes, so keeping it
# out of the requirements layer means an app dependency bump does not re-pull it.
# cu128 matches the Blackwell cards (sm_120) this runs on.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu128

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Sweep caches and model weights live under /app/data, which compose mounts, so
# neither is lost on rebuild. A sweep is ~3 min per video and the SAM 3 +
# DINOv3 weights are several GB — re-downloading either on every rebuild would
# make iteration painful.
ENV HF_HOME=/app/data/sam-training/hf
RUN mkdir -p /app/data/sam-training/sweeps /app/data/sam-training/hf

EXPOSE 5060

CMD ["python", "-m", "src.app"]
