import os
import sys

# `src/` is a package whose modules import each other as top-level names
# (e.g. `from graph.state import ...`, `from db.session import ...`). That
# only works if `src/` itself is on sys.path. pytest gets this for free via
# pyproject.toml's `[tool.pytest.ini_options] pythonpath = ["src"]`, but
# `python -m src` does not pick that up, so we add it here explicitly before
# importing anything from the package.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=False)
