from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from rew_api.config import Settings
from rew_api.db import Base, create_database_engine
from rew_api.main import create_app
from rew_api.providers import ProviderRegistry


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        admin_api_key="test-admin-key",
        api_key_pepper="test-pepper",
        twogis_reviews_api_key="test-2gis-key",
        provider_request_delay_seconds=0,
        sync_delay_min_seconds=0,
        sync_delay_max_seconds=0,
    )


@pytest.fixture
def session_factory(settings: Settings):
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def registry(settings: Settings) -> ProviderRegistry:
    return ProviderRegistry(settings)


@pytest.fixture
def client(settings: Settings, session_factory, registry: ProviderRegistry):
    app = create_app(
        settings=settings,
        session_factory=session_factory,
        provider_registry=registry,
    )
    with TestClient(app) as test_client:
        yield test_client
