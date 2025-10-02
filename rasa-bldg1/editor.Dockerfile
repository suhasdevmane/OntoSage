FROM rasa/rasa:3.6.12-full

# Install FastAPI, Uvicorn, and Ruff for linting
USER root
RUN pip install --no-cache-dir fastapi uvicorn ruff
USER 1001

WORKDIR /srv

EXPOSE 6080

# Expect the editor_server.py to be mounted at /srv/editor_server.py
CMD ["bash", "-lc", "uvicorn editor_server:app --host 0.0.0.0 --port 6080 --app-dir /srv"]
