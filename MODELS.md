# Models and Artifacts

Large model files are not stored in this repository. Use the instructions below to obtain them and where to place them locally so containers and scripts can find them.

## Contents

- Rasa models
- NL2SPARQL (T5) checkpoints
- Ollama (Mistral) models
- Notes on alternatives (Git LFS or private registry)

## Rasa models

- Directory (ignored by git): `rasa-ui/models/`
- How to obtain:
  - Train locally with `rasa train` inside the `rasa` container or on your host.
  - Or download a pre-trained `.tar.gz` model from your artifact storage and place it in `rasa-ui/models/`.
- The `rasa` container mounts `./rasa-ui/models:/app/models`.

## NL2SPARQL (T5) checkpoints

- Directory (ignored by git): `Transformers/t5_base/trained/checkpoint-*`
- How to obtain:
  - Pull from Hugging Face Hub or your internal storage. Example commands:

```bash
# Example: using huggingface_hub to download a specific checkpoint
pip install huggingface_hub
python - << 'PY'
from huggingface_hub import snapshot_download
snapshot_download(repo_id="<your-org>/<your-repo>", revision="checkpoint-2", local_dir="Transformers/t5_base/trained/checkpoint-2", local_dir_use_symlinks=False)
PY
```

- The `nl2sparql` service maps a checkpoint into the container via:
  - `./Transformers/t5_base/trained/checkpoint-2:/app/checkpoint-2:ro`
  - Adjust this path if you change the checkpoint name.

## Ollama (Mistral)

- Directory (ignored by git): Docker volume `ollama-models` holds the model data inside the container at `/usr/share/ollama/.ollama/models`.
- How to obtain:
  - The container entrypoint pulls `mistral` on first run (internet required).
  - Alternatively, pre-load the model on the host and mount the volume as configured in docker-compose.

## Notes

- This repo intentionally ignores large binary artifacts (`*.safetensors`, `*.bin`, `*.pt`, `*.pth`) and model directories.
- Prefer pointing to public Hugging Face models or hosting them privately; document exact repo IDs and revisions.
- If you need to version models alongside code, consider Git LFS with size limits and lock policies.
