# OntoSage 2.0 - Code Executor Dockerfile
# Heavily restricted for security

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy shared module
COPY shared/ /app/shared/

# Copy requirements
COPY code-executor/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY code-executor/ /app/code-executor/

WORKDIR /app/code-executor

# Create non-root user with no shell
RUN useradd -m -u 1000 -s /usr/sbin/nologin appuser && \
    chown -R appuser:appuser /app

# Create artifacts directory
RUN mkdir -p /artifacts && chown appuser:appuser /artifacts

USER appuser

# Expose port
EXPOSE 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
