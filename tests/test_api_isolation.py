from __future__ import annotations

from datetime import datetime, timezone

from rew_api.models import Organization, OrganizationSource, Project, Review
from rew_api.security import create_api_key


def _seed_project(session, settings, slug: str):
    project = Project(name=slug.upper(), slug=slug)
    organization = Organization(name=f"Organization {slug}", project=project)
    source = OrganizationSource(
        organization=organization,
        provider="yandex",
        source_url=f"https://yandex.ru/maps/org/{slug}/123/",
        normalized_url=f"https://yandex.ru/maps/org/org/123/reviews/?project={slug}",
        external_org_id=f"123-{slug}",
    )
    review = Review(
        organization=organization,
        source=source,
        provider_review_id=f"review-{slug}",
        author_name=f"Author {slug}",
        author_avatar_url=None,
        published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        rating=5,
        text=f"Secret review for {slug}",
    )
    session.add(review)
    _, raw_key = create_api_key(session, project, name="test", settings=settings)
    session.commit()
    return project, organization, raw_key


def test_api_key_can_only_read_its_own_project(client, settings, session_factory) -> None:
    with session_factory() as session:
        _, org_a, key_a = _seed_project(session, settings, "a")
        _, org_b, key_b = _seed_project(session, settings, "b")
        org_b_id = org_b.public_id

    response = client.get("/v1/reviews", headers={"Authorization": f"Bearer {key_a}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["text"] == "Secret review for a"
    assert "Secret review for b" not in response.text

    response = client.get(
        f"/v1/organizations/{org_b_id}/reviews",
        headers={"Authorization": f"Bearer {key_a}"},
    )
    assert response.status_code == 404

    response = client.get("/v1/reviews", headers={"Authorization": f"Bearer {key_b}"})
    assert response.status_code == 200
    assert response.json()["items"][0]["text"] == "Secret review for b"


def test_client_api_rejects_missing_key(client) -> None:
    response = client.get("/v1/reviews")
    assert response.status_code == 401


def test_admin_api_is_separate_from_client_keys(client, settings, session_factory) -> None:
    unauthorized = client.post(
        "/admin/projects",
        json={"name": "Project", "slug": "project"},
    )
    assert unauthorized.status_code == 401

    created = client.post(
        "/admin/projects",
        headers={"X-Admin-Key": settings.admin_api_key},
        json={"name": "Project", "slug": "project"},
    )
    assert created.status_code == 201
    assert created.json()["slug"] == "project"
