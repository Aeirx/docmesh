"""Settings loading: env overrides (flat and nested) and graceful key absence.

Settings(...) is constructed directly with _env_file=None so tests are hermetic —
a developer's local .env can never change test outcomes.
"""

from app.core.config import Settings


def test_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = Settings(_env_file=None, data_dir=tmp_path / "data")
    assert s.env == "dev"
    assert s.max_upload_mb == 25
    assert s.chunking.target_tokens == 400
    assert s.search.rrf_k == 60
    assert s.graph.edge_threshold == 0.35
    assert s.claude.model == "claude-sonnet-4-6"


def test_env_override_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOCMESH_ENV", "prod")
    monkeypatch.setenv("DOCMESH_MAX_UPLOAD_MB", "5")
    monkeypatch.setenv("DOCMESH_DATA_DIR", str(tmp_path / "data"))
    # Nested override via double-underscore delimiter
    monkeypatch.setenv("DOCMESH_SEARCH__RRF_K", "99")
    monkeypatch.setenv("DOCMESH_CHUNKING__OVERLAP_RATIO", "0.2")
    s = Settings(_env_file=None)
    assert s.env == "prod"
    assert s.max_upload_mb == 5
    assert s.search.rrf_k == 99
    assert s.chunking.overlap_ratio == 0.2
    # Untouched nested fields keep their defaults
    assert s.search.dense_weight == 0.5


def test_missing_anthropic_key_is_none_not_error(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = Settings(_env_file=None, data_dir=tmp_path / "data")
    assert s.anthropic_api_key is None


def test_anthropic_key_read_unprefixed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    s = Settings(_env_file=None, data_dir=tmp_path / "data")
    assert s.anthropic_api_key == "sk-ant-test"


def test_data_dirs_created_on_construction(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    data_dir = tmp_path / "fresh"
    s = Settings(_env_file=None, data_dir=data_dir)
    assert s.uploads_dir.is_dir()
