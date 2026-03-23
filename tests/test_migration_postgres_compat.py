import importlib.util
from pathlib import Path

from sqlalchemy.dialects import postgresql


def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/a4c2e8b1d9f0_add_canonical_role_model_and_role_description.py"
    )
    spec = importlib.util.spec_from_file_location("canonical_role_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_canonical_role_migration_uses_postgres_safe_boolean_literals():
    migration = _load_migration_module()
    role_table = migration._role_table()

    insert_sql = str(
        migration._core_role_insert_statement(role_table).compile(
            dialect=postgresql.dialect()
        )
    ).lower()
    update_sql = str(
        migration._core_role_update_statement(role_table).compile(
            dialect=postgresql.dialect()
        )
    ).lower()
    legacy_sql = str(
        migration._legacy_role_deactivate_statement(role_table).compile(
            dialect=postgresql.dialect()
        )
    ).lower()

    assert "true" in insert_sql
    assert "true" in update_sql
    assert "false" in legacy_sql
    assert "= 1" not in update_sql
    assert "= 0" not in legacy_sql
    assert ", 1," not in insert_sql
    assert ", 0," not in insert_sql
