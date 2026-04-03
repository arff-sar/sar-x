#!/usr/bin/env python3
"""Static/media referans denetimi (dry-run).

Varsayılan davranış yalnızca rapor üretmektir; dosya silmez.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Set, Tuple
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET_DIRS = ("static/uploads/cms", "static/img")
SOURCE_EXTENSIONS = {
    ".py",
    ".html",
    ".js",
    ".css",
    ".md",
    ".json",
    ".txt",
    ".yaml",
    ".yml",
}
EXCLUDED_DIR_NAMES = {
    ".git",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "htmlcov",
    "coverage",
}
REFERENCE_PATTERN = re.compile(
    r"(?P<value>https?://[^\s\"'<>]+|/static/[^\s\"'<>]+|static/[^\s\"'<>]+)",
    flags=re.IGNORECASE,
)


def _normalize_static_path(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    candidate = parsed.path if (parsed.scheme or parsed.netloc) else value
    candidate = candidate.split("?", 1)[0].split("#", 1)[0].strip()
    if not candidate:
        return ""

    if candidate.startswith("/"):
        candidate = candidate[1:]

    if not candidate.startswith("static/"):
        return ""

    # Güvenlik için path traversal normalize et.
    normalized = "/".join(part for part in candidate.split("/") if part not in {"", "."})
    if ".." in normalized.split("/"):
        return ""
    return normalized


def _iter_source_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        yield path


def _collect_code_references(root: Path) -> DefaultDict[str, Set[str]]:
    references: DefaultDict[str, Set[str]] = defaultdict(set)
    for file_path in _iter_source_files(root):
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in REFERENCE_PATTERN.finditer(text):
            normalized = _normalize_static_path(match.group("value"))
            if not normalized:
                continue
            references[normalized].add(f"code:{file_path.relative_to(root).as_posix()}")
    return references


def _add_ref(reference_map: DefaultDict[str, Set[str]], raw_value: str, source: str) -> None:
    normalized = _normalize_static_path(raw_value)
    if normalized:
        reference_map[normalized].add(source)


def _collect_db_references(env_name: str) -> Tuple[DefaultDict[str, Set[str]], List[str]]:
    references: DefaultDict[str, Set[str]] = defaultdict(set)
    warnings: List[str] = []

    try:
        from app import create_app
        from extensions import db, table_exists
        from models import (
            Announcement,
            DocumentResource,
            HomeSection,
            HomeSlider,
            HomeStatCard,
            MediaAsset,
            SiteAyarlari,
            SliderResim,
        )
    except Exception as exc:  # pragma: no cover - env bağımlı
        warnings.append(f"Uygulama import edilemedi, DB referansları atlandı: {exc}")
        return references, warnings

    try:
        app = create_app(env_name)
    except Exception as exc:  # pragma: no cover - runtime bağımlı
        warnings.append(f"create_app('{env_name}') başarısız, DB referansları atlandı: {exc}")
        return references, warnings

    model_fields = (
        ("media_asset", MediaAsset, "file_path"),
        ("home_slider", HomeSlider, "image_url"),
        ("home_section", HomeSection, "image_url"),
        ("announcement", Announcement, "cover_image"),
        ("home_stat_card", HomeStatCard, "icon"),
        ("document_resource", DocumentResource, "file_path"),
        ("slider_resim", SliderResim, "resim_url"),
    )

    with app.app_context():
        for table_name, model, field_name in model_fields:
            if not table_exists(table_name):
                continue
            field = getattr(model, field_name)
            try:
                values = db.session.query(field).all()
            except Exception as exc:  # pragma: no cover - schema/connection bağımlı
                db.session.rollback()
                warnings.append(f"{table_name}.{field_name} okunamadı: {exc}")
                continue

            for row in values:
                _add_ref(references, row[0] if row else "", f"db:{table_name}.{field_name}")

        if table_exists("site_ayarlari"):
            try:
                rows = db.session.query(SiteAyarlari.iletisim_notu).all()
            except Exception as exc:  # pragma: no cover
                db.session.rollback()
                warnings.append(f"site_ayarlari.iletisim_notu okunamadı: {exc}")
                rows = []

            logo_keys = {"public_logo_url", "homepage_demo_logo_url"}
            for row in rows:
                raw_meta = str((row[0] if row else "") or "").strip()
                if not raw_meta:
                    continue
                try:
                    parsed = json.loads(raw_meta)
                except (TypeError, ValueError):
                    continue
                if not isinstance(parsed, dict):
                    continue
                for key in logo_keys:
                    _add_ref(references, parsed.get(key) or "", f"db:site_ayarlari.{key}")

    return references, warnings


def _collect_target_files(root: Path) -> Dict[str, Dict[str, int | str]]:
    inventory: Dict[str, Dict[str, int | str]] = {}
    for relative_dir in TARGET_DIRS:
        directory = root / relative_dir
        if not directory.exists() or not directory.is_dir():
            continue
        for file_path in directory.rglob("*"):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(root).as_posix()
            try:
                size_bytes = int(file_path.stat().st_size)
            except OSError:
                size_bytes = -1
            inventory[rel_path] = {
                "size_bytes": size_bytes,
                "directory": relative_dir,
            }
    return inventory


def _human_size(size_bytes: int) -> str:
    if size_bytes < 0:
        return "bilinmiyor"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SAR-X static/media referans denetimi (dry-run)")
    parser.add_argument("--env", default="development", help="DB referansları için app environment (default: development)")
    parser.add_argument("--max-list", type=int, default=80, help="Konsolda listelenecek maksimum aday sayısı")
    parser.add_argument("--min-large-kb", type=int, default=256, help="Büyük dosya eşiği (KB)")
    parser.add_argument("--json-out", default="", help="Opsiyonel JSON rapor dosya yolu")
    parser.add_argument("--fail-on-orphan", action="store_true", help="Aday orphan varsa exit code 1 dön")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    code_refs = _collect_code_references(ROOT)
    db_refs, db_warnings = _collect_db_references(args.env)

    combined_refs: DefaultDict[str, Set[str]] = defaultdict(set)
    for path, sources in code_refs.items():
        combined_refs[path].update(sources)
    for path, sources in db_refs.items():
        combined_refs[path].update(sources)

    files = _collect_target_files(ROOT)
    tracked_paths = sorted(files.keys())
    referenced_existing = sorted(path for path in tracked_paths if path in combined_refs)
    orphan_candidates = sorted(path for path in tracked_paths if path not in combined_refs)

    min_large_bytes = max(args.min_large_kb, 1) * 1024
    largest_orphans = sorted(
        [path for path in orphan_candidates if int(files[path]["size_bytes"]) >= min_large_bytes],
        key=lambda item: int(files[item]["size_bytes"]),
        reverse=True,
    )

    logo_references = sorted(path for path in combined_refs if "logo" in Path(path).name.lower())

    report = {
        "env": args.env,
        "target_dirs": list(TARGET_DIRS),
        "scanned_file_count": len(tracked_paths),
        "referenced_existing_count": len(referenced_existing),
        "orphan_candidate_count": len(orphan_candidates),
        "large_orphan_candidate_count": len(largest_orphans),
        "db_warnings": db_warnings,
        "logo_reference_paths": logo_references,
        "referenced_existing": [
            {
                "path": path,
                "size_bytes": int(files[path]["size_bytes"]),
                "sources": sorted(combined_refs[path]),
            }
            for path in referenced_existing
        ],
        "orphan_candidates": [
            {
                "path": path,
                "size_bytes": int(files[path]["size_bytes"]),
                "directory": str(files[path]["directory"]),
            }
            for path in orphan_candidates
        ],
        "large_orphan_candidates": [
            {
                "path": path,
                "size_bytes": int(files[path]["size_bytes"]),
                "directory": str(files[path]["directory"]),
            }
            for path in largest_orphans
        ],
    }

    print(f"[Bilgi] Ortam: {args.env}")
    print(f"[Bilgi] Taranan klasörler: {', '.join(TARGET_DIRS)}")
    print(f"[Bilgi] Toplam dosya: {len(tracked_paths)}")
    print(f"[Bilgi] Referanslı (mevcut) dosya: {len(referenced_existing)}")
    print(f"[Bilgi] Referanssız aday dosya: {len(orphan_candidates)}")
    print(f"[Bilgi] Büyük referanssız aday (>{args.min_large_kb} KB): {len(largest_orphans)}")

    if db_warnings:
        print("[Uyarı] DB referansları kısmi/eksik:")
        for warning in db_warnings:
            print(f"  - {warning}")

    if logo_references:
        print("[Bilgi] Tespit edilen aktif logo referansları:")
        for path in logo_references[: args.max_list]:
            print(f"  - {path}")

    if orphan_candidates:
        print("[Bilgi] Referanssız aday dosyalar (dry-run):")
        for path in orphan_candidates[: args.max_list]:
            print(f"  - {path} | {_human_size(int(files[path]['size_bytes']))}")
        if len(orphan_candidates) > args.max_list:
            print(f"  ... (+{len(orphan_candidates) - args.max_list} aday)")

    if args.json_out:
        output_path = Path(args.json_out)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Bilgi] JSON rapor yazıldı: {output_path}")

    if args.fail_on_orphan and orphan_candidates:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
