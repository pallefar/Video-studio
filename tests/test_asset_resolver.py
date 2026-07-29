"""M8 acceptance: the resolver never returns a flagged or unapproved asset,
and sub-threshold matches fall through (return None / 404)."""

from __future__ import annotations

from pipeline_core.embeddings import HashingEmbedder, cosine
from pipeline_core.resolver import resolve_asset
from schema.models import Asset, AssetOrigin

EMBEDDER = HashingEmbedder()


def _asset(session, caption: str, *, approved=True, people=False, origin=AssetOrigin.own) -> Asset:
    asset = Asset(
        origin=origin,
        uri=f"s3://test/assets/{caption.replace(' ', '-')}.mp4",
        caption=caption,
        has_identifiable_people=people,
        approved=approved,
        license="Pexels License" if origin == AssetOrigin.stock else None,
        source_url="https://example.com/src" if origin == AssetOrigin.stock else None,
        embedding=EMBEDDER.embed(caption),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def test_embeddings_are_deterministic_and_normalised():
    a = EMBEDDER.embed("hands typing on a keyboard")
    assert a == EMBEDDER.embed("hands typing on a keyboard")
    assert abs(cosine(a, a) - 1.0) < 1e-9


def test_resolver_returns_best_match(session):
    _asset(session, "city skyline at night timelapse")
    keyboard = _asset(session, "hands typing on a mechanical keyboard")
    match = resolve_asset(session, "typing hands keyboard closeup", EMBEDDER, threshold=0.2)
    assert match is not None
    assert match.id == keyboard.id


def test_flagged_asset_is_never_returned(session):
    """The acceptance case: a perfect caption match that is flagged must lose."""
    _asset(session, "presenter talking to camera", people=True, approved=True)
    match = resolve_asset(session, "presenter talking to camera", EMBEDDER, threshold=0.1)
    assert match is None


def test_unapproved_asset_is_never_returned(session):
    _asset(session, "office desk with laptop", approved=False, people=False)
    assert resolve_asset(session, "office desk with laptop", EMBEDDER, threshold=0.1) is None


def test_subthreshold_falls_through(session):
    _asset(session, "underwater coral reef fish")
    assert resolve_asset(session, "quarterly revenue projections", EMBEDDER, threshold=0.35) is None


def test_resolve_endpoint_contract(client, session):
    _asset(session, "hands typing on a mechanical keyboard")
    hit = client.get("/assets/resolve", params={"query": "typing hands keyboard", "threshold": 0.2})
    assert hit.status_code == 200
    assert hit.json()["caption"] == "hands typing on a mechanical keyboard"

    miss = client.get("/assets/resolve", params={"query": "volcanic eruption on mars"})
    assert miss.status_code == 404


def test_resolve_endpoint_never_returns_flagged(client, session):
    _asset(session, "presenter talking to camera", people=True)
    response = client.get(
        "/assets/resolve", params={"query": "presenter talking to camera", "threshold": 0.1}
    )
    assert response.status_code == 404
