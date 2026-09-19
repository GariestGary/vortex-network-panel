import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_requires_valid_public_subscription_origin():
    environment = os.environ | {
        "VORTEX_MODE": "production",
        "VORTEX_SESSION_SECRET": "test-session-secret",
        "VORTEX_PUBLIC_SUBSCRIPTION_URL": "https://sub.example.test",
    }
    valid = subprocess.run([sys.executable, "-c", "import app.main"], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
    assert valid.returncode == 0, valid.stderr
    invalid = subprocess.run([sys.executable, "-c", "import app.main"], cwd=ROOT, env=environment | {"VORTEX_PUBLIC_SUBSCRIPTION_URL": "https://sub.example.test/path"}, capture_output=True, text=True, check=False)
    assert invalid.returncode != 0
    assert "VORTEX_PUBLIC_SUBSCRIPTION_URL" in invalid.stderr


def test_panel_gets_public_subscription_origin_but_subscription_service_does_not():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    panel, subscription = compose.split("  subscription:\n", 1)
    assert "VORTEX_PUBLIC_SUBSCRIPTION_URL" in panel
    assert "VORTEX_PUBLIC_SUBSCRIPTION_URL" not in subscription
    assert "VORTEX_PUBLIC_SUBSCRIPTION_URL=https://sub.jetstream.su" in (ROOT / ".env.example").read_text(encoding="utf-8")


def test_remote_profile_frontend_encodes_url_and_name_only_after_click():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "return subscriptionBaseUrl+'/s/'+encodeURIComponent(token);" in script
    assert "sing-box://import-remote-profile?url='+encodeURIComponent(url)+'#'+encodeURIComponent(name)" in script
    assert "window.location.href=remoteProfileLink(url,'VORTEX '+name)" in script
    assert "subscriptionUrlFor(name)" in script
