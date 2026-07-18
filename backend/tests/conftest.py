"""Shared fixtures.

Strategy: point Settings at a per-test tmp_path via environment variables (the same
channel production uses), clear the lru_cache, and build the real app. Tests then
exercise the actual startup path — migrations included — against a throwaway SQLite
file. No mocks of the storage layer: mocking the DB tests the mock.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.storage.database import create_db_engine


@pytest.fixture(autouse=True)
def _fake_ml_models(request, monkeypatch):
    """Fast tier: substitute the fake embedder/reranker for the real ones BEFORE
    any app is built. Works because app.main imports the class NAMES (and the
    real classes lazy-import torch), so patching the names is all it takes.
    Tests marked ``slow`` opt out and load the real models."""
    if request.node.get_closest_marker("slow"):
        yield
        return
    from tests.fixtures.fakes import FakeEmbedder, FakeEntityExtractor, FakeReranker

    monkeypatch.setattr("app.main.DenseEmbedder", FakeEmbedder)
    monkeypatch.setattr("app.main.Reranker", FakeReranker)
    monkeypatch.setattr("app.main.EntityExtractor", FakeEntityExtractor)
    yield


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    data_dir = tmp_path / "data"
    # as_posix(): forward slashes keep the sqlite URL unambiguous on Windows.
    db_url = f"sqlite+aiosqlite:///{(data_dir / 'test.db').as_posix()}"
    monkeypatch.setenv("DOCMESH_ENV", "test")
    monkeypatch.setenv("DOCMESH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DOCMESH_DATABASE_URL", db_url)
    # 1 MB cap: the oversized-upload test only has to ship ~1 MB through ASGI
    # instead of 25 MB. The cap logic is identical at any value.
    monkeypatch.setenv("DOCMESH_MAX_UPLOAD_MB", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
async def engine(settings):
    """Migrated engine on the tmp DB, for repo tests that bypass the HTTP layer."""
    from app.main import run_migrations

    await asyncio.to_thread(run_migrations, settings.database_url)
    engine = create_db_engine(settings.database_url)
    yield engine
    # Dispose before tmp_path teardown: Windows can't delete an open SQLite file.
    await engine.dispose()


@pytest.fixture
async def app(settings):
    """The real app with its lifespan (migrations, engine, repos) running."""
    from app.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
