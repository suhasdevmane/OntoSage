FROM python:3.9-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
RUN mkdir -p /app/logs /app/attachments
RUN chmod -R 755 /app/logs /app/attachments && find /app/attachments -type f -exec chmod 644 {} \;
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "--log-level", "info", "--access-logfile", "-", "--error-logfile", "-", "server:app"]dpoc