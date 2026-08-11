FROM python:3.11-slim

# OpenCV needs libGL + libglib2
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Sweep caches live here; the compose mount for /app/data makes them survive a
# rebuild, which matters because a sweep is ~3 minutes per video.
RUN mkdir -p /app/data/sam-training/sweeps

EXPOSE 5060

CMD ["python", "-m", "src.app"]
