# One-off offline Ragas evaluation runner (NOT a persistent production service).
# Started only via the compose `evaluation` profile:
#   docker compose --profile evaluation run --rm evaluation-runner --mode smoke
#
# NOTE: the host-side Python CLI (see evaluation/README.md) is the primary,
# validated execution path on Windows. This image exists for reproducibility on
# a fresh machine and installs CPU-only torch to stay lean.
FROM python:3.13-slim

WORKDIR /app

# System deps for sentence-transformers / tokenizers wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY evaluation/requirements.txt /app/evaluation/requirements.txt

# CPU-only torch first (from the PyTorch CPU index), then the rest from PyPI.
RUN pip install --no-cache-dir "torch==2.13.0" --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /app/evaluation/requirements.txt

COPY evaluation /app/evaluation

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/evaluation/.hf_cache \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_XET=1

ENTRYPOINT ["python", "-m", "evaluation.ragas_eval.run_evaluation"]
CMD ["--mode", "smoke"]
