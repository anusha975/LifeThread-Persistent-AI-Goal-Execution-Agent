import sys
from pathlib import Path

# Ensure root package directories are resolvable in test environments
ROOT_DIR = Path(__file__).resolve().parent.parent

for pkg in ["backend", "agent", "mcp-server"]:
    pkg_path = str(ROOT_DIR / pkg)
    if pkg_path not in sys.path:
        sys.path.insert(0, pkg_path)
