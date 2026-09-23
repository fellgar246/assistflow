"""Health route and startup behavior."""

import sys

import pytest
from assistflow_test_fixtures import build_health_status
from fastapi.testclient import TestClient

from assistflow_api.config import load_settings
from assistflow_api.main import create_app


def test_importing_the_api_does_not_load_the_aws_sdk() -> None:
    assert "boto3" not in sys.modules
    assert "botocore" not in sys.modules


def test_health_route_reports_healthy() -> None:
    client = TestClient(create_app(load_settings({})))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == build_health_status()


def test_startup_log_names_no_cloud_sdk_and_no_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    settings = load_settings({"AWS_SECRET_ACCESS_KEY": "super-secret-value"})
    with TestClient(create_app(settings)):
        pass

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "api_started" in output
    assert "super-secret-value" not in output
    assert "boto3" not in output
    assert "amazonaws.com" not in output
    assert '"aws_enabled": false' in output
