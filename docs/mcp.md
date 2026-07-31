# MCP — drive the studio from any LLM

The studio ships an MCP (Model Context Protocol) server: any MCP-capable
client — Claude Code, Claude Desktop, or any other LLM runtime speaking MCP
— can run productions against it: create projects, generate video/images/
music/VFX, plan and export storyboards, and carry avatar renders to review.

The server is a **client of the studio's HTTP API**, never a second
backend: every request goes through the same routes, validators, and
compliance gates (C1–C6) as the web panel.

## Setup

```bash
pip install -e ".[mcp]"        # in the studio venv
```

The server needs the studio API running (`./scripts/dev_up.sh` or the
individual services) and finds it via `STUDIO_API_URL`
(default `http://localhost:8000`).

**Claude Code**

```bash
claude mcp add video-studio -- python -m studio_mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "video-studio": {
      "command": "/path/to/Video-studio/.venv/bin/python",
      "args": ["-m", "studio_mcp"],
      "env": { "STUDIO_API_URL": "http://localhost:8000" }
    }
  }
}
```

**Any other MCP client**: stdio transport, command `python -m studio_mcp`.

## What the LLM can do

~25 tools covering the full creative surface: `studio_stats`,
`create_project` (kinds: **video / movie / game / other**), library
search + provenance + downloads, `generate_video` (camera-preset stacks),
`generate_image` (styles, shared-seed batches, arbitrary sizes),
`generate_thumbnail`, `generate_music`, `apply_effects` (VFX + Mix),
`upscale_asset`, the full storyboard flow (create / add shots / reorder /
generate / export with live progress), and avatar jobs to the review gate.

Three workflow prompts ship with the server and encode the production
recipes end-to-end:

- `movie_scene_workflow` — scene description → styled storyboard → per-beat
  camera moves → music bed → rendered export.
- `game_asset_batch` — brief → project(kind=game) → shared-seed/style asset
  families (sprites, tilesets, key art) → hero-piece upscales.
- `youtube_video_workflow` — topic → script → avatar render + thumbnail +
  music, handed to a human at review.

## What the LLM deliberately cannot do

Three actions are human-only and have **no tools** (asserted structurally
in `tests/test_mcp.py` — a tool whose name contains publish/consent/
approve/flag fails the suite):

| Missing tool | Why |
|---|---|
| publish | C5: publishing needs manual human confirmation — never automation. The LLM carries a job to review; a person clicks Publish, and uploads land private with the synthetic-media disclosure. |
| record consent | C6: consent is a human act recorded by a person in the panel. Identities without it cannot be trained or used — the API refuses regardless of caller. |
| approve / flag assets | The approval gate exists so a human clears content before the resolver may auto-select it. |

Everything else the LLM does still passes the server-side gates: the C1
watermark has no off-switch, generated output only enters the pipeline as
`origin='generated'` assets, and identity use is consent-checked on every
request.
