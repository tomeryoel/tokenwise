FROM python:3.11-slim
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/app/data/hf \
    CHROMA_DIR=/app/data/chroma

# Install CPU-only torch first so sentence-transformers does not pull the large
# CUDA build. This keeps the image smaller and inference CPU-bound.
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data/chroma /app/data/hf
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
