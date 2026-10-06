"""Host-side alias for the encrypted archive format.

The format is defined ONCE, in ``orchestrator/services/backup_format.py``, so the container
that writes the automatic backups and these host scripts cannot drift apart. This file loads
that module by path rather than importing ``orchestrator.services``: the package import runs
``orchestrator/__init__.py``, which pulls in the whole agent stack and is not needed to decrypt
an archive. The loaded module must stay stdlib + cryptography only (a test enforces it).
"""

import importlib.util
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[1] / "orchestrator" / "services" / "backup_format.py"
_spec = importlib.util.spec_from_file_location("ontosage_backup_format", _SOURCE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

globals().update({k: v for k, v in vars(_module).items() if not k.startswith("__")})
