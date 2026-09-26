import configparser
from pathlib import Path


def test_alembic_ini_configuration() -> None:
    """Verify backend/alembic.ini exists and has correct script_location."""
    backend_dir = Path(__file__).resolve().parent.parent
    alembic_ini_path = backend_dir / "alembic.ini"

    assert alembic_ini_path.exists(), "alembic.ini not found in backend directory"

    config = configparser.ConfigParser()
    config.read(alembic_ini_path, encoding="utf-8")

    assert config.has_section("alembic")
    script_loc = config.get("alembic", "script_location", raw=True)
    assert "app/db/migrations" in script_loc


def test_migration_files_exist() -> None:
    """Verify migration folder contains required environment scripts and versions."""
    backend_dir = Path(__file__).resolve().parent.parent
    migrations_dir = backend_dir / "app" / "db" / "migrations"

    assert (migrations_dir / "env.py").exists()
    assert (migrations_dir / "script.py.mako").exists()
    assert (migrations_dir / "versions").is_dir()

    versions = list((migrations_dir / "versions").glob("*.py"))
    assert len(versions) >= 1
    assert any("0001_initial_baseline" in v.name for v in versions)
