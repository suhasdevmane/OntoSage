# =====================================================================
# Stage 1 — libredwg builder
# =====================================================================
# Phase 18 (2026-05-30): libredwg-utils is not packaged in any current
# Debian release (bookworm/trixie/sid).  We build it from a pinned source
# release in this builder stage and copy only the resulting binaries +
# shared library + headers into the runtime stage.  Source build adds
# ~3 minutes to the first build (cached afterwards) and ~12 MB to the
# runtime image vs ~250 MB if we kept all build deps in the runtime stage.
#
# Pinned to 0.13.3 (the last 0.13.x release) for build reproducibility.
# Bump intentionally — newer master often breaks the autotools build.
FROM python:3.12-slim-trixie AS libredwg-builder

ARG LIBREDWG_VERSION=0.13.3

RUN apt-get update && apt-get install -y --no-install-recommends \
        autoconf \
        automake \
        libtool \
        pkg-config \
        gcc \
        g++ \
        make \
        swig \
        curl \
        ca-certificates \
        libpcre2-dev \
        libpcre2-8-0 \
        libxml2-dev \
        texinfo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN curl -fsSL -o libredwg.tar.gz \
        "https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VERSION}/libredwg-${LIBREDWG_VERSION}.tar.gz" \
    && tar -xzf libredwg.tar.gz \
    && mv libredwg-${LIBREDWG_VERSION} src

WORKDIR /build/src
# Disable Python bindings + docs + tests — we only need the C library + the
# `dwg2dxf` / `dwg2svg` binaries that the OntoSage DWG pipeline shells out to.
# --enable-release strips debug symbols, halving the .so size.
RUN ./configure \
        --prefix=/opt/libredwg \
        --disable-python \
        --disable-bindings \
        --enable-release \
        --disable-debugging \
    && make -j"$(nproc)" \
    && make install


# =====================================================================
# Stage 2 — runtime
# =====================================================================
FROM python:3.12-slim-trixie
# Phase-18 (2026-05-29): moved from python:3.11-slim-bookworm → 3.12-slim-trixie.
# Python 3.11 exited active maintenance Oct 2024 and the bookworm base carried
# 1 critical + 13 high CVEs.  Python 3.12 + Debian 13 (trixie) clears both.

WORKDIR /app

# System dependencies for runtime:
#   * gcc/g++          — pip needs to compile a few wheel deps
#   * tesseract-ocr    — OCR fallback for floor-plan PDFs
#   * libpango/cairo/* — weasyprint native deps (Phase 18 PDF backend)
#   * libpcre2-8-0     — runtime dep of the libredwg shared lib
#   * libxml2          — runtime dep of the libredwg shared lib
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        curl \
        tesseract-ocr \
        ca-certificates \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        libpcre2-8-0 \
        libxml2 \
    && rm -rf /var/lib/apt/lists/*

# Phase 18 (2026-05-30): copy the libredwg binaries + shared library from the
# builder stage and register the lib path with ldconfig so the existing
# `dwg2dxf` shell-out in orchestrator/services/dwg_pipeline.py finds it on $PATH.
COPY --from=libredwg-builder /opt/libredwg/bin/ /usr/local/bin/
COPY --from=libredwg-builder /opt/libredwg/lib/ /usr/local/lib/
RUN ldconfig && \
    ( dwg2dxf --version 2>&1 | head -1 || \
      echo "[Dockerfile] WARNING: dwg2dxf not callable after install" )

# Copy shared module first
COPY shared/ /app/shared/

# Copy orchestrator requirements
COPY orchestrator/requirements.txt /app/orchestrator/

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/orchestrator/requirements.txt

# ── Bake the local embedding model into the image (self-contained, offline) ──
# Done BEFORE copying app code so ordinary code changes don't bust the ~1.3 GB model layer.
# bge-large-en-v1.5 is pre-downloaded so the first request pays no download cost and the
# system needs no network at runtime. Cached under /app so the chown below covers it and
# the non-root runtime user can read it. Build-arg lets you override the model.
ENV HF_HOME=/app/.hf_cache
ENV SENTENCE_TRANSFORMERS_HOME=/app/.hf_cache
ARG EMBEDDING_MODEL_LOCAL=BAAI/bge-large-en-v1.5
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL_LOCAL}')"
# Model is now baked — run fully offline at runtime (no HuggingFace network calls).
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

# Copy orchestrator code
COPY orchestrator/ /app/orchestrator/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Build provenance — the commit + build time this image was built from, surfaced at /health so an
# operator can tell exactly which code is running (and whether it has drifted from the repo).
# Declared late so changing them only re-runs the final layers, never the dependency install.
# Defaults to "unknown" when not passed, so a plain `docker compose build` still works.
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV BUILD_SHA=$GIT_SHA
ENV BUILD_TIME=$BUILD_TIME

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
