from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

import uvicorn
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from rew_api.config import get_settings
from rew_api.db import SessionLocal
from rew_api.models import Organization, OrganizationSource, Project, utcnow
from rew_api.providers import ProviderError, ProviderRegistry
from rew_api.security import create_api_key
from rew_api.services.sync import ReviewSyncService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rew-api", description="Review collector management")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("init-db", help="Apply all database migrations")

    create_project = subcommands.add_parser(
        "create-project", help="Create an isolated client project"
    )
    create_project.add_argument("--name", required=True)
    create_project.add_argument("--slug", required=True)

    create_key = subcommands.add_parser("create-key", help="Issue a project API key")
    create_key.add_argument("--project", required=True, help="Project slug")
    create_key.add_argument("--name", default="default")

    create_org = subcommands.add_parser("create-organization", help="Create an organization")
    create_org.add_argument("--project", required=True, help="Project slug")
    create_org.add_argument("--name", required=True)

    add_source = subcommands.add_parser("add-source", help="Attach a review source")
    add_source.add_argument("--organization", required=True, help="Organization public UUID")
    add_source.add_argument("--provider", required=True, choices=("2gis", "yandex"))
    add_source.add_argument("--url", required=True)
    add_source.add_argument("--interval", type=int, default=None, help="Sync interval in minutes")

    sync_source = subcommands.add_parser("sync-source", help="Synchronize one source immediately")
    sync_source.add_argument("--id", type=int, required=True)

    sync_due = subcommands.add_parser("sync-due", help="Synchronize all due sources sequentially")
    sync_due.add_argument("--limit", type=int, default=None)
    sync_due.add_argument("--delay-min", type=float, default=None)
    sync_due.add_argument("--delay-max", type=float, default=None)

    serve = subcommands.add_parser("serve", help="Run the HTTP API")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    return parser


def init_db() -> None:
    command.upgrade(AlembicConfig("alembic.ini"), "head")
    print("Database schema is up to date")


def execute(args: argparse.Namespace) -> int:
    settings = get_settings()
    registry = ProviderRegistry(settings)
    service = ReviewSyncService(settings, registry)

    if args.command == "init-db":
        init_db()
        return 0
    if args.command == "serve":
        uvicorn.run("rew_api.main:app", host=args.host, port=args.port, reload=args.reload)
        return 0

    if args.command == "sync-due":
        summaries = service.sync_due(
            SessionLocal,
            limit=args.limit,
            delay_min_seconds=args.delay_min,
            delay_max_seconds=args.delay_max,
        )
        print(json.dumps([asdict(item) for item in summaries], ensure_ascii=False, indent=2))
        return 1 if any(item.status == "failed" for item in summaries) else 0

    with SessionLocal() as session:
        try:
            if args.command == "create-project":
                project = Project(name=args.name, slug=args.slug)
                session.add(project)
                session.commit()
                print(
                    json.dumps({"id": project.public_id, "slug": project.slug}, ensure_ascii=False)
                )
                return 0

            if args.command == "create-key":
                project = session.scalar(select(Project).where(Project.slug == args.project))
                if project is None:
                    raise ValueError(f"Project not found: {args.project}")
                record, raw_key = create_api_key(
                    session, project, name=args.name, settings=settings
                )
                session.commit()
                print(
                    json.dumps(
                        {"id": record.id, "prefix": record.key_prefix, "api_key": raw_key},
                        ensure_ascii=False,
                    )
                )
                return 0

            if args.command == "create-organization":
                project = session.scalar(select(Project).where(Project.slug == args.project))
                if project is None:
                    raise ValueError(f"Project not found: {args.project}")
                organization = Organization(project=project, name=args.name)
                session.add(organization)
                session.commit()
                print(
                    json.dumps(
                        {"id": organization.public_id, "name": organization.name},
                        ensure_ascii=False,
                    )
                )
                return 0

            if args.command == "add-source":
                organization = session.scalar(
                    select(Organization).where(Organization.public_id == args.organization)
                )
                if organization is None:
                    raise ValueError(f"Organization not found: {args.organization}")
                resolved = registry.get(args.provider).resolve_source(args.url)
                source = OrganizationSource(
                    organization=organization,
                    provider=resolved.provider,
                    source_url=resolved.source_url,
                    normalized_url=resolved.normalized_url,
                    external_org_id=resolved.external_org_id,
                    sync_interval_minutes=args.interval or settings.sync_interval_minutes,
                    next_sync_at=utcnow(),
                )
                session.add(source)
                session.commit()
                print(
                    json.dumps({"id": source.id, "provider": source.provider}, ensure_ascii=False)
                )
                return 0

            if args.command == "sync-source":
                summary = service.sync_source(session, args.id)
                print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
                return 1 if summary.status == "failed" else 0
        except (ValueError, ProviderError, IntegrityError) as exc:
            session.rollback()
            print(str(exc), file=sys.stderr)
            return 2

    return 2


def main() -> None:
    raise SystemExit(execute(build_parser().parse_args()))


if __name__ == "__main__":
    main()
