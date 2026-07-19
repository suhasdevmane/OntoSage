# OntoSage 2.0 - GraphDB RAG Service Dockerfile

FROM python:3.12-slim-trixie

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy shared module (from root context)
COPY shared/ /app/shared/

# Copy requirements specific to this service
COPY rag-service/graphdbRAG/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY rag-service/graphdbRAG/ /app/

# Build provenance — commit + build time, surfaced at /health so an operator can tell which code is
# running. Declared late so changing them only re-runs the final layers. Defaults to "unknown".
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV BUILD_SHA=$GIT_SHA
ENV BUILD_TIME=$BUILD_TIME

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]

