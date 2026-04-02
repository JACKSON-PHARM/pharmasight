"""Clinic router requires authentication (module gate runs after auth in dependency chain)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_clinic_patients_401_or_403_without_auth(client):
    r = client.get("/api/clinic/patients")
    assert r.status_code in (401, 403)
