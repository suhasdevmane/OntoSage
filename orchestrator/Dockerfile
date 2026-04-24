FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies
# libredwg-utils (provides dwg2dxf) is in Debian sid/trixie but not bookworm;
# install it best-effort — the DWG pipeline degrades gracefully if absent.
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    wkhtmltopdf \
    tesseract-ocr \
    && ( apt-get install -y libredwg-utils || true ) \
    && rm -rf /var/lib/apt/lists/*

# Copy shared module first
COPY shared/ /app/shared/

# Copy orchestrator requirements
COPY orchestrator/requirements.txt /app/orchestrator/

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/orchestrator/requirements.txt

# Copy orchestrator code
COPY orchestrator/ /app/orchestrator/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN useradd -m -u 1000 ontosage && \
    chown -R ontosage:ontosage /app

USER ontosage

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')"

# Run the application
CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
