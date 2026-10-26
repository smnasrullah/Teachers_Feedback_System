import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_healthz_returns_ok_and_exposes_no_config(client):
    response = client.get(reverse("core:healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "Content-Security-Policy" in response
