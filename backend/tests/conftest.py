import os
import sys
import tempfile
from pathlib import Path

os.environ["CHRONIX_TESTING"] = "1"
os.environ["CHRONIX_LLM_PROVIDER"] = "disabled"
os.environ.pop("OPENAI_API_KEY", None)
os.environ["CHRONIX_DB_PATH"] = str(Path(tempfile.gettempdir()) / f"chronix-test-{os.getpid()}.db")
Path(os.environ["CHRONIX_DB_PATH"]).unlink(missing_ok=True)
sys.path.insert(0, str(Path(__file__).parents[1]))
