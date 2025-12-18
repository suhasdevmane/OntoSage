FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi==0.115.5 uvicorn[standard]==0.32.1 httpx==0.28.1

COPY main.py /app/main.py

ENV OLLAMA_BASE_URL=http://ollama-deepseek-r1:11434
ENV OLLAMA_MODEL=deepseek-r1:32b

EXPOSE 8005
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
