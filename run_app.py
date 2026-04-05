"""Wrapper to launch Streamlit in sandboxed environments that restrict os.getcwd()."""
import os
import sys

# Monkey-patch os.getcwd to return the project directory
# when the real getcwd() fails (e.g., in sandboxed preview environments)
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_original_getcwd = os.getcwd

def _safe_getcwd():
    try:
        return _original_getcwd()
    except (PermissionError, OSError):
        return _PROJECT_DIR

os.getcwd = _safe_getcwd

# Ensure the project is on the path
sys.path.insert(0, _PROJECT_DIR)

# Now launch Streamlit
from streamlit.web.cli import main
sys.argv = [
    "streamlit", "run", os.path.join(_PROJECT_DIR, "app.py"),
    "--server.headless", "true",
    "--server.port", os.environ.get("PORT", "8501"),
    "--server.fileWatcherType", "none",
]
main()
