"""Trip plan save/upload: local file, GCS upload, signed URL, fallbacks."""
import datetime
import os

import pytest

import tools


class FakeBlob:
    def __init__(self):
        self.uploaded_from = None
        self.signed_url_kwargs = None

    def upload_from_filename(self, path):
        self.uploaded_from = path

    def generate_signed_url(self, **kwargs):
        self.signed_url_kwargs = kwargs
        return "https://storage.example/signed-plan-url"


class FakeBucket:
    def __init__(self, exists=True):
        self._exists = exists
        self.blob_instance = FakeBlob()

    def exists(self):
        return self._exists

    def blob(self, name):
        self.blob_name = name
        return self.blob_instance


class FakeClient:
    def __init__(self, bucket):
        self._bucket = bucket
        self.created_bucket = None

    def bucket(self, name):
        self.requested_bucket = name
        return self._bucket

    def create_bucket(self, name, location=None):
        self.created_bucket = (name, location)
        self._bucket._exists = True
        return self._bucket


@pytest.fixture
def plan_file_cleanup():
    yield
    path = os.path.join(os.path.dirname(tools.__file__), "tmp", "day_99_plan.md")
    if os.path.exists(path):
        os.remove(path)


def test_upload_returns_signed_url(monkeypatch, plan_file_cleanup):
    bucket = FakeBucket(exists=True)
    client = FakeClient(bucket)
    monkeypatch.setattr(tools.storage, "Client", lambda: client)

    url = tools.save_and_upload_trip_plan(99, "Test Day", "## Itinerary\n- Drive")

    assert url == "https://storage.example/signed-plan-url"
    assert bucket.blob_name == "day_99_plan.md"
    assert bucket.blob_instance.signed_url_kwargs["expiration"] == datetime.timedelta(hours=24)
    assert client.created_bucket is None  # bucket existed, not re-created


def test_local_file_written_with_header(monkeypatch, plan_file_cleanup):
    monkeypatch.setattr(tools.storage, "Client", lambda: FakeClient(FakeBucket()))

    tools.save_and_upload_trip_plan(99, "Test Day", "## Itinerary\n- Drive")

    local_path = os.path.join(os.path.dirname(tools.__file__), "tmp", "day_99_plan.md")
    content = open(local_path, encoding="utf-8").read()
    assert content.startswith("# Trip Itinerary: Day 99 - Test Day")
    assert "## Itinerary" in content


def test_bucket_created_when_missing(monkeypatch, plan_file_cleanup):
    bucket = FakeBucket(exists=False)
    client = FakeClient(bucket)
    monkeypatch.setattr(tools.storage, "Client", lambda: client)

    tools.save_and_upload_trip_plan(99, "Test Day", "plan")

    assert client.created_bucket is not None


def test_gcs_failure_returns_local_fallback(monkeypatch, plan_file_cleanup):
    def broken_client():
        raise RuntimeError("no credentials")

    monkeypatch.setattr(tools.storage, "Client", broken_client)

    url = tools.save_and_upload_trip_plan(99, "Test Day", "plan")

    assert url == "/tmp/day_99_plan.md"
