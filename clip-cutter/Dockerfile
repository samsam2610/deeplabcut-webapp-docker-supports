FROM python:3.11-slim

# System deps: OpenCV needs libGL + libglib2
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the CLIP model into the image so the first run is instant
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('clip-ViT-B-32')"

# Pre-download DINOv2 ViT-L/14 model (~1.1 GB) for fine-scan feature
RUN python -c "import torch; torch.hub.load('facebookresearch/dinov2', 'dinov2_vitl14', pretrained=True)"

COPY . .

EXPOSE 5002

CMD ["python", "app.py"]
