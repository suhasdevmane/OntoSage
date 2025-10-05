FROM ollama/ollama:latest

COPY ./entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

# Document the Ollama service port used by compose (host 11434 -> container 11434)
EXPOSE 11434

ENTRYPOINT ["/entrypoint.sh"]