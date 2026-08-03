from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rew_api.api.dependencies import (
    get_registry,
    get_session,
    get_settings,
    get_sync_service,
    require_admin,
)
from rew_api.config import Settings
from rew_api.models import Organization, OrganizationSource, Project, utcnow
from rew_api.providers import ProviderError, ProviderRegistry
from rew_api.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    OrganizationCreate,
    OrganizationSourceCreate,
    ProjectCreate,
    ProjectResponse,
    SourceResponse,
    SyncSummaryResponse,
)
from rew_api.security import create_api_key
from rew_api.services.sync import ReviewSyncService


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.public_id,
        name=project.name,
        slug=project.slug,
        is_active=project.is_active,
        created_at=project.created_at,
    )


def _source_response(source: OrganizationSource) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        provider=source.provider,
        source_url=source.source_url,
        external_org_id=source.external_org_id,
        enabled=source.enabled,
        sync_status=source.sync_status,
        sync_error=source.sync_error,
        last_success_at=source.last_success_at,
        next_sync_at=source.next_sync_at,
        metrics=source.metrics,
    )


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, session: Session = Depends(get_session)
) -> ProjectResponse:
    project = Project(name=payload.name, slug=payload.slug)
    session.add(project)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Project slug already exists") from exc
    session.refresh(project)
    return _project_response(project)


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectResponse]:
    projects = session.scalars(select(Project).order_by(Project.id)).all()
    return [_project_response(project) for project in projects]


@router.post(
    "/projects/{project_id}/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
def issue_api_key(
    project_id: str,
    payload: ApiKeyCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ApiKeyCreated:
    project = session.scalar(select(Project).where(Project.public_id == project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    record, raw_key = create_api_key(session, project, name=payload.name, settings=settings)
    session.commit()
    return ApiKeyCreated(
        id=record.id,
        name=record.name,
        prefix=record.key_prefix,
        api_key=raw_key,
        created_at=record.created_at,
    )


@router.post(
    "/projects/{project_id}/organizations",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
def create_organization(
    project_id: str,
    payload: OrganizationCreate,
    session: Session = Depends(get_session),
) -> dict:
    project = session.scalar(select(Project).where(Project.public_id == project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    organization = Organization(project=project, name=payload.name)
    session.add(organization)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Organization already exists in project"
        ) from exc
    return {
        "id": organization.public_id,
        "name": organization.name,
        "project_id": project.public_id,
    }


@router.post(
    "/organizations/{organization_id}/sources",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_source(
    organization_id: str,
    payload: OrganizationSourceCreate,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings),
) -> SourceResponse:
    organization = session.scalar(
        select(Organization).where(Organization.public_id == organization_id)
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        provider = registry.get(payload.provider)
        resolved = provider.resolve_source(payload.url)
    except ProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    source = OrganizationSource(
        organization=organization,
        provider=resolved.provider,
        source_url=resolved.source_url,
        normalized_url=resolved.normalized_url,
        external_org_id=resolved.external_org_id,
        sync_interval_minutes=payload.sync_interval_minutes or settings.sync_interval_minutes,
        next_sync_at=utcnow(),
    )
    session.add(source)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Source is already attached") from exc
    session.refresh(source)
    return _source_response(source)


@router.get("/sources", response_model=list[SourceResponse])
def list_sources(session: Session = Depends(get_session)) -> list[SourceResponse]:
    sources = session.scalars(select(OrganizationSource).order_by(OrganizationSource.id)).all()
    return [_source_response(source) for source in sources]


@router.post("/sources/{source_id}/sync", response_model=SyncSummaryResponse)
def sync_source(
    source_id: int,
    session: Session = Depends(get_session),
    service: ReviewSyncService = Depends(get_sync_service),
) -> SyncSummaryResponse:
    if session.get(OrganizationSource, source_id) is None:
        raise HTTPException(status_code=404, detail="Source not found")
    summary = service.sync_source(session, source_id)
    return SyncSummaryResponse(**asdict(summary))
