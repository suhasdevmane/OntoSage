## Security Notice (September 2025)

An OpenRouter API key was accidentally committed in `Transformers/Mistral/test.ipynb`. The key has been disabled by the provider. We have removed the file from the repository and updated `.gitignore` to prevent future commits of SSH keys and large artifacts.

Actions taken:
- Deleted the offending notebook and SSH key files under `Transformers/Mistral/`
- Strengthened `.gitignore` (secrets, SSH keys, large model files)
- Added `MODELS.md` to document where to place local models without committing

Recommended next steps:
- Rotate any keys that were exposed (OpenRouter: https://openrouter.ai/keys)
- If strict history purging is required, use `git filter-repo` or BFG to remove the secrets from all history
- Consider adding a pre-commit hook and/or secret scanning (GitHub Advanced Security, gitleaks, TruffleHog)

Contact the maintainers if you believe you’ve found a security issue.