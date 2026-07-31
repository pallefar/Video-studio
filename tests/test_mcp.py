"""M21: the MCP control surface. The server's tools drive the real FastAPI
app end-to-end (httpx ASGITransport — no network), the compliance boundary
is structural (no publish/consent/approve/flag tools can exist), and
project kinds organise movie/game/other production work."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport
from sqlmodel import Session

from api.main import create_app
from api.db import get_session
from api.routes.generations import get_registry
from api.routes.jobs import get_dispatcher
from pipeline_core.providers import ProviderRegistry
from studio_mcp.client import StudioClient, StudioError
from studio_mcp.server import FORBIDDEN_TOOL_PATTERNS, build_server
from tests.conftest import RecordingDispatcher
from tests.test_providers import FakeApiProvider


@pytest.fixture()
def mcp_setup(engine):
    """MCP server whose StudioClient talks straight to the FastAPI app."""
    app = create_app()

    def override_session():
        with Session(engine) as session:
            yield session

    from tests.test_image_studio import FakeImageProvider

    registry = ProviderRegistry()
    registry.register(FakeApiProvider())
    registry.register(FakeImageProvider())  # registers as 'local' with image models
    dispatcher = RecordingDispatcher()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher

    client = StudioClient(base_url="http://studio.test", transport=ASGITransport(app=app))
    server = build_server(client)
    yield {"server": server, "dispatcher": dispatcher}
    asyncio.run(client.aclose())


def _call(server, tool: str, args: dict):
    """Unpack a CallToolResult: list returns arrive as one content block per
    item, dict returns as a single JSON block."""
    result = asyncio.run(server.call_tool(tool, args))
    if result.structured_content is not None:
        return result.structured_content
    parsed = [json.loads(block.text) for block in result.content]
    return parsed[0] if len(parsed) == 1 else parsed


# --- the compliance boundary is structural -----------------------------------


def test_no_human_judgement_tools_exist(mcp_setup):
    tools = asyncio.run(mcp_setup["server"].list_tools())
    names = [t.name for t in tools]
    assert len(names) >= 20
    for name in names:
        for forbidden in FORBIDDEN_TOOL_PATTERNS:
            assert forbidden not in name.lower(), f"tool {name} crosses the human-judgement boundary"


def test_instructions_state_the_boundary(mcp_setup):
    assert "human-only" in (mcp_setup["server"].instructions or "")


# --- tools drive the real app ------------------------------------------------


def test_project_kinds_round_trip(mcp_setup):
    server = mcp_setup["server"]
    created = _call(server, "create_project", {"title": "Starfall", "kind": "game"})
    assert created["kind"] == "game"
    movie = _call(server, "create_project", {"title": "The Long Coast", "kind": "movie"})
    assert movie["kind"] == "movie"
    projects = _call(server, "list_projects", {})
    assert {p["kind"] for p in projects} == {"game", "movie"}


def test_generate_video_creates_generation(mcp_setup):
    server = mcp_setup["server"]
    generation = _call(
        server, "generate_video",
        {"subject": "a red espresso machine", "preset_ids": ["crash_zoom_in"],
         "provider": "fake", "model": "fake-t2v"},
    )
    assert generation["status"] == "queued"
    assert "crash zoom" in generation["prompt"]
    status = _call(server, "generation_status", {"generation_id": generation["id"]})
    assert status["id"] == generation["id"]
    assert mcp_setup["dispatcher"].calls  # really enqueued


def test_game_asset_batch_via_images(mcp_setup):
    """The game-dev flow: a batch of related assets sharing one seed/style
    so the art direction reads as one game."""
    server = mcp_setup["server"]
    project = _call(server, "create_project", {"title": "Pixel Quest", "kind": "game"})
    frames = _call(
        server, "generate_image",
        {"prompt": "pixel-art potion bottle, item icon", "frames": 3,
         "width": 512, "height": 512, "project_id": project["id"]},
    )
    assert len(frames) == 3
    assert len({f["params"]["seed"] for f in frames}) == 1  # shared seed
    assert all(f["params"]["width"] == 512 for f in frames)
    assert all(f["project_id"] == project["id"] for f in frames)


def test_api_errors_surface_as_studio_errors(mcp_setup):
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="422"):
        asyncio.run(
            mcp_setup["server"].call_tool("generation_status", {"generation_id": "not-a-uuid"})
        )


def test_storyboard_flow_and_reorder(mcp_setup, engine):
    server = mcp_setup["server"]
    from schema.models import Asset, AssetOrigin

    with Session(engine) as session:
        a = Asset(origin=AssetOrigin.own, uri="s3://b/a.mp4", caption="a",
                  has_identifiable_people=False, approved=True)
        b = Asset(origin=AssetOrigin.own, uri="s3://b/b.mp4", caption="b",
                  has_identifiable_people=False, approved=True)
        session.add(a)
        session.add(b)
        session.commit()
        asset_ids = [str(a.id), str(b.id)]

    board = _call(server, "create_storyboard", {"title": "Scene 1", "format": "long"})
    for index, asset_id in enumerate(asset_ids):
        board = _call(
            server, "add_shot",
            {"storyboard_id": board["id"], "idx": index, "subject": f"beat {index}",
             "asset_id": asset_id},
        )
    shot_ids = [s["id"] for s in board["shots"]]
    reordered = _call(
        server, "reorder_shots",
        {"storyboard_id": board["id"], "shot_ids": list(reversed(shot_ids))},
    )
    assert [s["id"] for s in reordered["shots"]] == list(reversed(shot_ids))

    export = _call(server, "export_storyboard", {"storyboard_id": board["id"]})
    assert export["timeline"]["shots"][0]["subject"] == "beat 1"


# --- workflow prompts --------------------------------------------------------


def test_production_prompts_registered(mcp_setup):
    prompts = asyncio.run(mcp_setup["server"].list_prompts())
    names = {p.name for p in prompts}
    assert {"movie_scene_workflow", "game_asset_batch", "youtube_video_workflow"} <= names
    rendered = asyncio.run(
        mcp_setup["server"].get_prompt("game_asset_batch", {"asset_brief": "16-bit dungeon tileset"})
    )
    text = rendered.messages[0].content.text
    assert "16-bit dungeon tileset" in text
    assert 'kind="game"' in text
