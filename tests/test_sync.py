from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from rew_api.config import Settings
from rew_api.models import Organization, OrganizationSource, Project, Review, ReviewMedia
from rew_api.providers import (
    ProviderFetchResult,
    ProviderMedia,
    ProviderReview,
    ResolvedSource,
    ReviewProvider,
)
from rew_api.services.sync import ReviewSyncService


class FakeProvider(ReviewProvider):
    code = "fake"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.text = "first"

    def resolve_source(self, url: str) -> ResolvedSource:
        return ResolvedSource(self.code, url, url, "company-1")

    def fetch_reviews(self, source: ResolvedSource, *, since=None) -> ProviderFetchResult:
        return ProviderFetchResult(
            reviews=(
                ProviderReview(
                    external_id="review-1",
                    author_name="Author",
                    author_avatar_url=None,
                    published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                    edited_at=None,
                    rating=5,
                    text=self.text,
                    media=(ProviderMedia("photo", "https://img.test/1.jpg"),),
                    raw_payload={"id": "review-1"},
                ),
            ),
            metrics={"review_count": 1},
        )


class FakeRegistry:
    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider

    def get(self, code: str) -> FakeProvider:
        assert code == "fake"
        return self.provider


def test_sync_is_idempotent_and_updates_media(settings: Settings, session_factory) -> None:
    provider = FakeProvider(settings)
    service = ReviewSyncService(settings, FakeRegistry(provider))

    with session_factory() as session:
        project = Project(name="Project", slug="project")
        organization = Organization(name="Organization", project=project)
        source = OrganizationSource(
            organization=organization,
            provider="fake",
            source_url="https://source.test/company",
            normalized_url="https://source.test/company",
            external_org_id="company-1",
        )
        session.add(source)
        session.commit()
        source_id = source.id

        first = service.sync_source(session, source_id)
        assert first.created_count == 1
        assert first.updated_count == 0

        provider.text = "updated full text"
        second = service.sync_source(session, source_id)
        assert second.created_count == 0
        assert second.updated_count == 1

        stored = session.scalar(select(Review).where(Review.source_id == source_id))
        assert stored.text == "updated full text"
        assert stored.author_avatar_url is None
        assert session.scalar(select(func.count()).select_from(Review)) == 1
        assert session.scalar(select(func.count()).select_from(ReviewMedia)) == 1
