"""Unit tests must be fully offline and independent of the developer's .env."""
import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    # tools.py / maps_client.py import load_dotenv locally inside each function,
    # so patching the dotenv module attribute neutralizes all of them.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("NPS_API_KEY", raising=False)
    monkeypatch.delenv("MAPS_API_KEY", raising=False)
