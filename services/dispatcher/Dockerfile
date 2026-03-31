# ============================================================
# Dispatcher Service - Dockerfile
# FastAPI app served via uvicorn on Cloud Run
# ============================================================

FROM python:3.11-slim

# Prevents Python from writing .pyc files and enables stdout logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (cached layer unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Cloud Run injects PORT env var; default to 8080
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
