#!/usr/bin/env python3
"""Production deployment preflight checks.

Bu script yalnızca doğrulama yapar; dosya silmez veya git index değiştirmez.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = ROOT / "migrations" / "versions"

WEAK_SECRET_VALUES = {"changeme", "secret", "default", "123456", "password"}

FORBIDDEN_TRACKED_RULES: Sequence[Tuple[re.Pattern[str], str]] = (
    (re.compile(r"^\.env$"), "Runtime secret dosyası (.env) track ediliyor."),
    (re.compile(r"^instance/.*\.(db|sqlite|sqlite3)$", flags=re.IGNORECASE), "Runtime veritabanı dosyası track ediliyor."),
    (re.compile(r"^(?:venv|\.venv)/"), "Virtualenv dosyaları track ediliyor."),
    (re.compile(r"^static/uploads/"), "Upload/runtime medya dosyaları track ediliyor."),
    (re.compile(r"(?:^|/)konusma_kaydi_.*\.txt$", flags=re.IGNORECASE), "Konuşma/artifact metin dosyası track ediliyor."),
    (re.compile(r"(?:^|/)(?:artifacts?|artifact)(?:/|$)", flags=re.IGNORECASE), "Artifact klasörü/dosyası track ediliyor."),
    (re.compile(r"\.log$", flags=re.IGNORECASE), "Log dosyası track ediliyor."),
)


def _bool_from_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _run_git_ls_files(root: Path) -> List[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files çalıştırılamadı: {proc.stderr.strip()}")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _check_forbidden_tracked_files(paths: Iterable[str]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    for path in paths:
        for pattern, reason in FORBIDDEN_TRACKED_RULES:
            if pattern.search(path):
                findings.append({"path": path, "reason": reason})
                break
    return findings


def _is_strong_secret(secret: str) -> bool:
    if len(secret.strip()) < 32:
        return False
    return secret.strip().lower() not in WEAK_SECRET_VALUES


def _is_sqlite_url(database_url: str) -> bool:
    return str(database_url or "").strip().lower().startswith("sqlite:")


def _sqlite_db_path(database_url: str) -> Path | None:
    url = str(database_url or "").strip()
    if not url.lower().startswith("sqlite:"):
        return None

    parsed = urlparse(url)
    raw_path = parsed.path or ""
    if not raw_path:
        return None

    candidate = raw_path
    if candidate.startswith("//"):
        candidate = candidate[2:]
    if candidate.startswith("/"):
        return Path(candidate)
    return ROOT / candidate


def _load_sqlite_current_revisions(database_url: str) -> List[str]:
    db_path = _sqlite_db_path(database_url)
    if not db_path or not db_path.exists() or not db_path.is_file():
        return []

    try:
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.Error:
        return []

    versions = sorted({str(row[0]).strip() for row in rows if row and row[0]})
    return versions


def _load_migration_heads() -> List[str]:
    if not VERSIONS_DIR.exists():
        return []

    revisions = set()
    down_revisions = set()

    for path in VERSIONS_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        revision_match = re.search(r"^revision\s*=\s*['\"]([0-9a-f]+)['\"]", text, flags=re.MULTILINE)
        if revision_match:
            revisions.add(revision_match.group(1))

        down_match = re.search(r"^down_revision\s*=\s*(.+)$", text, flags=re.MULTILINE)
        if not down_match:
            continue
        down_value = down_match.group(1)
        for item in re.findall(r"['\"]([0-9a-f]+)['\"]", down_value):
            down_revisions.add(item)

    heads = sorted(revisions - down_revisions)
    return heads


def _check_production_env() -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    secret_key = str(os.getenv("SECRET_KEY") or "")
    if not _is_strong_secret(secret_key):
        errors.append("SECRET_KEY güçlü değil veya eksik (min 32 karakter).")

    database_url = str(os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        errors.append("DATABASE_URL eksik.")

    flask_env = str(os.getenv("FLASK_ENV") or "").strip().lower()
    app_env = str(os.getenv("APP_ENV") or "").strip().lower()
    if flask_env == "development" or app_env == "development":
        errors.append("APP_ENV/FLASK_ENV production için development olamaz.")

    if _bool_from_env("DEBUG", False):
        errors.append("DEBUG production için açık olamaz.")

    if _bool_from_env("DEMO_TOOLS_ENABLED", False):
        errors.append("DEMO_TOOLS_ENABLED production için açık olamaz.")

    storage_backend = str(os.getenv("STORAGE_BACKEND") or "local").strip().lower() or "local"
    is_sqlite = _is_sqlite_url(database_url)
    if storage_backend == "gcs" and not str(os.getenv("GCS_BUCKET_NAME") or "").strip():
        errors.append("STORAGE_BACKEND=gcs iken GCS_BUCKET_NAME zorunludur.")
    if storage_backend == "local" and not is_sqlite and not _bool_from_env("ALLOW_LOCAL_STORAGE_IN_PRODUCTION", False):
        errors.append(
            "Non-sqlite production için local storage kapalıdır. "
            "GCS kullanın veya kontrollü geçiş için ALLOW_LOCAL_STORAGE_IN_PRODUCTION=1 ayarlayın."
        )

    rate_limit_uri = str(os.getenv("RATELIMIT_STORAGE_URI") or "").strip() or "memory://"
    if rate_limit_uri.startswith("memory://"):
        if not is_sqlite:
            errors.append("RATELIMIT_STORAGE_URI production’da memory:// olamaz (merkezi backend gerekli).")
        elif not _bool_from_env("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", False):
            errors.append(
                "Sqlite production kurtarma modunda memory rate-limit için "
                "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=1 zorunludur."
            )

    heads = _load_migration_heads()
    if heads:
        current_versions = _load_sqlite_current_revisions(database_url)
        if is_sqlite and current_versions and not set(heads).issubset(set(current_versions)):
            errors.append(
                "SQLite migration head uyumsuz: "
                f"current={','.join(current_versions)} expected_head={','.join(heads)}"
            )
        elif is_sqlite and not current_versions:
            warnings.append("SQLite alembic_version bilgisi okunamadı; migration durumu manuel doğrulanmalı.")

    return errors, warnings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SAR-X production preflight kontrolü")
    parser.add_argument(
        "--env",
        default=(os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "production").strip().lower() or "production",
        help="Kontrol hedef ortamı (default: APP_ENV/FLASK_ENV veya production)",
    )
    parser.add_argument("--json", action="store_true", help="Çıktıyı JSON formatında yazdır")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    try:
        tracked_paths = _run_git_ls_files(ROOT)
    except RuntimeError as exc:
        print(f"[HATA] {exc}", file=sys.stderr)
        return 2

    forbidden_tracked = _check_forbidden_tracked_files(tracked_paths)

    env_errors: List[str] = []
    env_warnings: List[str] = []
    if args.env == "production":
        env_errors, env_warnings = _check_production_env()

    summary = {
        "env": args.env,
        "forbidden_tracked_count": len(forbidden_tracked),
        "forbidden_tracked": forbidden_tracked,
        "env_error_count": len(env_errors),
        "env_errors": env_errors,
        "env_warning_count": len(env_warnings),
        "env_warnings": env_warnings,
    }

    if args.json:
        import json

        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"[Bilgi] Ortam: {args.env}")
        print(f"[Bilgi] Yasak tracked dosya sayısı: {len(forbidden_tracked)}")
        for finding in forbidden_tracked[:50]:
            print(f"  - {finding['path']} | {finding['reason']}")
        if len(forbidden_tracked) > 50:
            print(f"  ... (+{len(forbidden_tracked) - 50} dosya)")

        if args.env == "production":
            print(f"[Bilgi] Production env hata sayısı: {len(env_errors)}")
            for item in env_errors:
                print(f"  - {item}")
            if env_warnings:
                print(f"[Bilgi] Production env uyarı sayısı: {len(env_warnings)}")
                for item in env_warnings:
                    print(f"  - {item}")

    has_blocker = bool(forbidden_tracked or env_errors)
    return 1 if has_blocker else 0


if __name__ == "__main__":
    raise SystemExit(main())
