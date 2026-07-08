# Cloud Run image for the trip agent (specs/06-deployment.md).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Cloud Run injects PORT; default to 8080 for local docker runs.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
