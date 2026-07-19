"""Settings loading: env overrides (flat and nested) and Phase 4 LLM knobs.

Settings(...) is constructed directly with _env_file=None so tests are hermetic —
a developer's local .env can never change test outcomes.
"""

from app.core.config import Settings


def test_defaults(tmp_path) -> None:
    s = Settings(_env_file=None, data_dir=tmp_path / "data")
    assert s.env == "dev"
    assert s.max_upload_mb == 25
    assert s.chunking.target_tokens == 400
    assert s.search.rrf_k == 60
    assert s.graph.edge_threshold == 0.35
    assert s.llm.enabled is True
    assert s.llm.repo_id == "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
    assert s.llm.filename == "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    assert s.llm.model_path is None
    assert s.llm.rpm_limit == 6
    assert s.llm.warm is False


def test_env_override_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOCMESH_ENV", "prod")
    monkeypatch.setenv("DOCMESH_MAX_UPLOAD_MB", "5")
    monkeypatch.setenv("DOCMESH_DATA_DIR", str(tmp_path / "data"))
    # Nested override via double-underscore delimiter
    monkeypatch.setenv("DOCMESH_SEARCH__RRF_K", "99")
    monkeypatch.setenv("DOCMESH_CHUNKING__OVERLAP_RATIO", "0.2")
    monkeypatch.setenv("DOCMESH_LLM__ENABLED", "false")
    monkeypatch.setenv("DOCMESH_LLM__RPM_LIMIT", "2")
    s = Settings(_env_file=None)
    assert s.env == "prod"
    assert s.max_upload_mb == 5
    assert s.search.rrf_k == 99
    assert s.chunking.overlap_ratio == 0.2
    assert s.llm.enabled is False
    assert s.llm.rpm_limit == 2
    # Untouched nested fields keep their defaults
    assert s.search.dense_weight == 0.5
    assert s.llm.n_ctx == 4096


def test_data_dirs_created_on_construction(tmp_path) -> None:
    data_dir = tmp_path / "fresh"
    s = Settings(_env_file=None, data_dir=data_dir)
    assert s.uploads_dir.is_dir()
    assert s.models_dir.is_dir()  # data/models — the GGUF download target
