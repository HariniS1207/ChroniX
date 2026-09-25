import os
import sys
from pathlib import Path

os.environ["CHRONIX_TESTING"] = "1"
os.environ["CHRONIX_LLM_PROVIDER"] = "disabled"
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parents[1]))
