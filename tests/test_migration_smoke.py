import os
import sqlite3
import subprocess
from pathlib import Path


def test_fresh_database_can_upgrade_with_migrations(app):
    project_root = Path(app.root_path)
    db_path = project_root / "instance" / "test_migration_smoke.db"
    if db_path.exists():
        db_path.unlink()

    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "production",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "ALLOW_SQLITE_IN_PRODUCTION": "1",
            "SECRET_KEY": "test-release-stabilization-secret-key-123456",
        }
    )

    result = subprocess.run(
        ["./venv/bin/flask", "--app", "app:create_app", "db", "upgrade"],
        cwd=str(project_root),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "inventory_asset" in tables
    assert "work_order" in tables
    assert "notification" in tables
