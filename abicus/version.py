import subprocess
from pathlib import Path

from abicus import __version__


def get_version() -> str:
    base = f"v{__version__}"
    try:
        repo_root = Path(__file__).resolve().parent.parent
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            timeout=1,
        ).decode().strip()
        if sha:
            return f"{base} · {sha}"
    except Exception:
        pass
    return base
