"""Start the FastAPI server for the literature library."""

import os
import sys
import uvicorn

# Ensure we're running from the project root so 'api' module is importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="127.0.0.1", port=19527, reload=True)
