"""Agent-level evals use the developer's real .env keys (Gemini + Maps)."""
import os

import pytest
from dotenv import load_dotenv

load_dotenv()


def pytest_collection_modifyitems(config, items):
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return
    skip = pytest.mark.skip(reason="agent eval needs GEMINI_API_KEY (or GOOGLE_API_KEY) in .env")
    for item in items:
        if "eval" in item.keywords:
            item.add_marker(skip)
