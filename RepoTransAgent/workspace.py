import os
from pathlib import Path


def workspace_root():
    return Path(os.environ.get("REPOTRANS_WORKSPACE", "/workspace")).resolve()
