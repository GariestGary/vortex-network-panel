import os
import subprocess
import sys
from pathlib import Path


def test_production_startup_rejects_missing_session_secret():
    environment = os.environ | {"VORTEX_MODE": "production"}
    environment.pop("VORTEX_SESSION_SECRET", None)
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "VORTEX_SESSION_SECRET" in result.stderr

def test_startup_rejects_unknown_mode():
    environment = os.environ | {"VORTEX_MODE": "unexpected", "VORTEX_SESSION_SECRET": "test-secret"}
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "VORTEX_MODE" in result.stderr


def test_production_image_does_not_copy_mock_fixtures():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "COPY mock ./mock" not in dockerfile

def test_production_startup_rejects_missing_public_subscription_url():
    environment = os.environ | {"VORTEX_MODE": "production", "VORTEX_SESSION_SECRET": "test-secret"}
    environment.pop("VORTEX_PUBLIC_SUBSCRIPTION_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "VORTEX_PUBLIC_SUBSCRIPTION_URL" in result.stderr