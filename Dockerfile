# Cloud Run Job image for the ingest pipeline.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

RUN useradd --create-home app
USER app

# DATA_URI is set on the job (gs://<bucket>); defaults to ./data for local runs.
ENTRYPOINT ["clippers-ingest"]
