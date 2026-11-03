"""CLI-level Quick Install provisioning smoke test."""

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from api.app.models.user import User
from shared.config import get_settings

ROOT = Path(__file__).resolve().parent.parent.parent


async def test_quickstart_cli_writes_notes_and_summary(db_session, tmp_path):
    settings = get_settings()
    notes = tmp_path / "install-notes.txt"
    summary = tmp_path / "install-summary.json"
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DB_HOST": settings.db_host,
        "DB_PORT": str(settings.db_port),
        "DB_NAME": "parking_test",
        "DB_USER": settings.db_user,
        "DB_PASSWORD": settings.db_password,
        "SETUP_TOKEN_PATH": str(tmp_path / "no-setup-token"),
        "ENROLL_TOKEN_PATH": str(tmp_path / "no-enroll-token"),
        "QUICKSTART_NOTES_PATH": str(notes),
        "QUICKSTART_SUMMARY_PATH": str(summary),
        "QUICKSTART_ENROLL_TOKEN_PATH": str(tmp_path / "no-enroll-token"),
    }

    result = subprocess.run(
        [
            sys.executable,
            "scripts/quickstart_provision.py",
            "--site-name",
            "CLI Site",
            "--admin-username",
            "cli-admin",
            "--in-count",
            "1",
            "--out-count",
            "1",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "QUICKSTART_OK" in result.stdout
    assert "cli-admin" in result.stdout

    notes_text = notes.read_text(encoding="utf-8")
    assert "Admin username : cli-admin" in notes_text
    assert "Admin password :" in notes_text
    assert "GIN-01" in notes_text
    assert "GOUT-01" in notes_text

    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["admin_created"] is True
    assert payload["admin_password"]
    assert payload["site_created"] is True
    assert notes.stat().st_mode & 0o077 == 0

    admin = await db_session.execute(
        select(User).where(User.username == "cli-admin")
    )
    assert admin.scalar_one().role == "admin"
