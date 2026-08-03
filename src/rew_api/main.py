from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from rew_api.api.admin import router as admin_router
from rew_api.api.client import router as client_router
from rew_api.config import Settings, get_settings
from rew_api.db import Base, SessionLocal
from rew_api.providers import ProviderRegistry
from rew_api.services.sync import ReviewSyncService


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    app_session_factory = session_factory or SessionLocal
    registry = provider_registry or ProviderRegistry(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if app_settings.auto_create_schema:
            Base.metadata.create_all(bind=app_session_factory.kw["bind"])
        yield

    app = FastAPI(title=app_settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.session_factory = app_session_factory
    app.state.provider_registry = registry
    app.state.sync_service = ReviewSyncService(app_settings, registry)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(admin_router)
    app.include_router(client_router)
    return app


app = create_app()
