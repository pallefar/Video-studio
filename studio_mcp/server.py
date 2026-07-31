"""The MCP server: tools + workflow prompts over the studio API.

Deliberate exclusions (the human-judgement boundary — enforced by absence
and asserted in tests/test_mcp.py):
- publish_*     — C5: publishing requires manual human confirmation, never
                  automation. An LLM can carry a job to review; a person
                  clicks Publish.
- *consent*     — C6: consent is a human act recorded by a person.
- approve/flag  — the asset approval gate exists so a human clears content
                  before the resolver may select it.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from studio_mcp.client import StudioClient

# Tool names that must never exist on this server (compliance boundary).
FORBIDDEN_TOOL_PATTERNS = ("publish", "consent", "approve", "flag")


def build_server(client: StudioClient | None = None) -> MCPServer:
    studio = client or StudioClient()
    server = MCPServer(
        "video-studio",
        instructions=(
            "Self-hosted AI video studio: preset-first video generation, image "
            "studio, VFX, music beds, storyboards, avatar renders. Outputs land "
            "in an asset library organised into projects (video, movie, game, "
            "other). Publishing, consent recording, and asset approval are "
            "human-only actions done in the web panel — never ask for tools to "
            "do them. Generated media carries a mandatory 'Made with AI' "
            "watermark and synthetic-media disclosure by design."
        ),
    )

    # ---- discovery --------------------------------------------------------

    @server.tool()
    async def studio_stats() -> Any:
        """Studio snapshot: asset/queue/job counts, storage use, recent
        renders and stage durations."""
        return await studio.get("/stats")

    @server.tool()
    async def list_engines() -> Any:
        """Generation model catalog: (provider, model, kinds, lane). Local
        models render on the studio GPU; API providers run hosted."""
        return await studio.get("/generations/catalog")

    @server.tool()
    async def list_camera_presets() -> Any:
        """One-click camera moves (crash zoom, orbit, dolly...). Stack up to
        3 per video generation."""
        return await studio.get("/presets")

    @server.tool()
    async def list_styles() -> Any:
        """Curated style templates applied across shots/stills."""
        return await studio.get("/styles")

    @server.tool()
    async def list_effects() -> Any:
        """VFX presets applied to existing footage (levitation, restyles...)."""
        return await studio.get("/effects")

    # ---- prompt intelligence (M27) ---------------------------------------

    @server.tool()
    async def prompt_catalog(category: str | None = None, kind: str | None = None) -> Any:
        """Curated prompt-engineering catalog: structure frames, camera
        language, lighting, styles, negatives, music tags — each with source
        attribution. Filter by category and/or kind (video/image/music)."""
        return await studio.get("/prompts/catalog", category=category, kind=kind)

    @server.tool()
    async def reverse_prompt(asset_id: str, save: bool = False) -> Any:
        """Reverse prompt engineering: turn a library asset back into a
        reusable prompt (+ standard negative) from its Florence-2 caption.
        save=true files it in the prompt library."""
        return await studio.post(f"/prompts/reverse/{asset_id}?save={str(save).lower()}", json={})

    @server.tool()
    async def save_prompt(
        title: str,
        text: str,
        kind: str = "video",
        negative: str | None = None,
        tags: list[str] | None = None,
    ) -> Any:
        """Save a prompt to the studio's prompt library for reuse."""
        return await studio.post(
            "/prompts",
            json={"title": title, "text": text, "kind": kind,
                  "negative": negative, "tags": tags, "source": "manual"},
        )

    @server.tool()
    async def list_saved_prompts() -> Any:
        """The user's saved prompt library (manual, reverse-engineered, and
        catalog-derived prompts)."""
        return await studio.get("/prompts")

    # ---- projects & library ----------------------------------------------

    @server.tool()
    async def create_project(title: str, kind: str = "video", description: str | None = None) -> Any:
        """Create a production container. kind: video | movie | game | other.
        Assets pool per project; one asset can serve many projects."""
        return await studio.post(
            "/projects", json={"title": title, "kind": kind, "description": description}
        )

    @server.tool()
    async def list_projects() -> Any:
        """All projects with asset/storyboard counts."""
        return await studio.get("/projects")

    @server.tool()
    async def list_assets(query: str | None = None, origin: str | None = None, limit: int = 50) -> Any:
        """Library assets, optionally filtered by caption substring and
        origin (own | stock | generated). Unapproved assets exist but only a
        human can approve them for automatic selection."""
        assets = await studio.get("/assets")
        if origin:
            assets = [a for a in assets if a.get("origin") == origin]
        if query:
            needle = query.lower()
            assets = [a for a in assets if needle in (a.get("caption") or "").lower()]
        return assets[:limit]

    @server.tool()
    async def attach_asset_to_project(project_id: str, asset_id: str) -> Any:
        """Pool an existing library asset into a project."""
        return await studio.post(f"/projects/{project_id}/assets/{asset_id}")

    @server.tool()
    async def asset_provenance(asset_id: str) -> Any:
        """Walk an asset's derivation chain back to its source (generation
        records with provider/model/params at each hop)."""
        return await studio.get(f"/assets/{asset_id}/provenance")

    @server.tool()
    async def asset_download_url(asset_id: str) -> Any:
        """Presigned URL to fetch an asset's bytes (posting, external tools)."""
        return await studio.get(f"/assets/{asset_id}/download")

    # ---- generation -------------------------------------------------------

    @server.tool()
    async def generate_video(
        subject: str,
        preset_ids: list[str],
        provider: str = "local",
        model: str = "wan2.2-fun-camera",
        project_id: str | None = None,
        identity_id: str | None = None,
    ) -> Any:
        """Preset-first video generation: stack up to 3 camera presets on a
        subject. Returns the queued generation; poll generation_status."""
        return await studio.post(
            "/presets/generate",
            json={
                "preset_ids": preset_ids, "subject": subject, "provider": provider,
                "model": model, "project_id": project_id, "identity_id": identity_id,
            },
        )

    @server.tool()
    async def generate_image(
        prompt: str,
        style_id: str | None = None,
        frames: int = 1,
        width: int = 1024,
        height: int = 1024,
        seed: int | None = None,
        provider: str = "local",
        model: str = "z-image-turbo",
        project_id: str | None = None,
        identity_id: str | None = None,
    ) -> Any:
        """Styled stills. frames > 1 is storyboard mode: one shared seed so a
        sequence holds together — also ideal for game-asset batches (set
        width/height for sprites, textures, key art)."""
        return await studio.post(
            "/images/generate",
            json={
                "prompt": prompt, "style_id": style_id, "frames": frames,
                "width": width, "height": height, "seed": seed,
                "provider": provider, "model": model,
                "project_id": project_id, "identity_id": identity_id,
            },
        )

    @server.tool()
    async def generate_thumbnail(title: str, style_id: str | None = None, project_id: str | None = None) -> Any:
        """1280x720 YouTube thumbnail on the text-capable model."""
        return await studio.post(
            "/images/thumbnail",
            json={"title": title, "style_id": style_id, "project_id": project_id},
        )

    @server.tool()
    async def generate_music(prompt: str, duration_s: int = 60, project_id: str | None = None) -> Any:
        """Music bed (mood/genre/instrumentation prompt). Licensed-clean
        output lands in the library for the editor's audio tracks."""
        return await studio.post(
            "/music/generate",
            json={"prompt": prompt, "duration_s": duration_s, "project_id": project_id},
        )

    @server.tool()
    async def apply_effects(
        asset_id: str,
        effect_ids: list[str],
        camera_preset_ids: list[str] | None = None,
        preview: bool = False,
        project_id: str | None = None,
    ) -> Any:
        """Apply VFX presets to existing footage (optionally mixed with
        camera moves). Derives a NEW asset; the source is never touched.
        preview=true routes to the fast model."""
        return await studio.post(
            "/effects/apply",
            json={
                "asset_id": asset_id, "effect_ids": effect_ids,
                "camera_preset_ids": camera_preset_ids or [],
                "preview": preview, "project_id": project_id,
            },
        )

    @server.tool()
    async def upscale_asset(asset_id: str, model: str = "seedvr2-3b", project_id: str | None = None) -> Any:
        """Finishing pass (upscale/interpolate) deriving a new asset."""
        return await studio.post(
            "/effects/upscale",
            json={"asset_id": asset_id, "model": model, "project_id": project_id},
        )

    @server.tool()
    async def generation_status(generation_id: str) -> Any:
        """One generation's status/params/output asset id."""
        return await studio.get(f"/generations/{generation_id}")

    # ---- storyboards (movie scenes, trailers, cutscenes) ------------------

    @server.tool()
    async def create_storyboard(
        title: str,
        format: str = "long",
        style_id: str | None = None,
        project_id: str | None = None,
    ) -> Any:
        """Plan a video shot-by-shot. format: long (16:9) | short (9:16,
        <=60s). A movie is a sequence of storyboards — one per scene."""
        return await studio.post(
            "/storyboards",
            json={"title": title, "format": format, "style_id": style_id, "project_id": project_id},
        )

    @server.tool()
    async def add_shot(
        storyboard_id: str,
        idx: int,
        subject: str,
        preset_ids: list[str] | None = None,
        duration_target_ms: int = 5000,
        asset_id: str | None = None,
    ) -> Any:
        """Append a shot: either a subject + camera presets to generate, or
        an existing pooled asset_id to use directly."""
        return await studio.post(
            f"/storyboards/{storyboard_id}/shots",
            json={
                "idx": idx, "subject": subject, "preset_ids": preset_ids or [],
                "duration_target_ms": duration_target_ms, "asset_id": asset_id,
            },
        )

    @server.tool()
    async def reorder_shots(storyboard_id: str, shot_ids: list[str]) -> Any:
        """Reorder a board's shots to the given id sequence (a permutation)."""
        return await studio.post(
            f"/storyboards/{storyboard_id}/shots/reorder", json={"shot_ids": shot_ids}
        )

    @server.tool()
    async def generate_shot(storyboard_id: str, shot_id: str) -> Any:
        """Generate (or regenerate) one shot through the provider layer."""
        return await studio.post(f"/storyboards/{storyboard_id}/shots/{shot_id}/generate", json={})

    @server.tool()
    async def get_storyboard(storyboard_id: str) -> Any:
        """A board with its shots and their generation states."""
        return await studio.get(f"/storyboards/{storyboard_id}")

    @server.tool()
    async def export_storyboard(storyboard_id: str) -> Any:
        """Compile a finished board into a timeline and render the video
        (refused while shots are unfinished). Track via export_progress."""
        return await studio.post(f"/storyboards/{storyboard_id}/export")

    @server.tool()
    async def export_progress(ref: str) -> Any:
        """Live render progress for an export (storyboard or timeline id)."""
        return await studio.get(f"/metrics/exports/{ref}")

    # ---- avatar renders ---------------------------------------------------

    @server.tool()
    async def create_avatar_job(title: str, script: str, voice_profile_id: str, base_loop_id: str) -> Any:
        """Script -> talking-head video (TTS + lip-sync + assembly). The
        result waits in review; a human previews and publishes in the panel."""
        return await studio.post(
            "/jobs",
            json={
                "title": title, "script": script,
                "voice_profile_id": voice_profile_id, "base_loop_id": base_loop_id,
            },
        )

    @server.tool()
    async def avatar_job_status(job_id: str) -> Any:
        """Job state machine position, segments, and (once assembled) the
        output uri a human can preview before publishing."""
        return await studio.get(f"/jobs/{job_id}")

    @server.tool()
    async def list_voices_and_loops() -> Any:
        """Voice profiles and base loops available for avatar jobs."""
        return {
            "voices": await studio.get("/voices"),
            "loops": await studio.get("/loops"),
        }

    @server.tool()
    async def list_identities() -> Any:
        """Identities (read-only). Consent status shown; recording consent is
        a human act done in the panel — identities without consent cannot be
        trained or used in face-bearing generation (C6)."""
        return await studio.get("/identities")

    # ---- workflow prompts -------------------------------------------------

    @server.prompt()
    def movie_scene_workflow(scene_description: str) -> str:
        """Produce one movie scene end-to-end from a description."""
        return f"""Produce a movie scene in the studio from this description:

{scene_description}

Work through it like a production, using the studio tools:
1. create_project(kind="movie") if none exists yet — one project per film.
2. list_styles and pick ONE style for the whole scene (consistency beats variety).
3. create_storyboard with that style; break the description into 4-8 shots,
   each a single visual beat with ONE clear subject. add_shot for each,
   choosing camera presets that serve the beat (list_camera_presets — e.g.
   slow dolly for tension, crash zoom for reveals, orbit for establishing).
4. generate_shot for each; poll get_storyboard until all shots succeed.
   Regenerate any shot whose result you'd cut in review.
5. generate_music matching the scene's mood, pooled to the project.
6. export_storyboard, then export_progress until done — report the final
   asset so a human can review it in the panel."""

    @server.prompt()
    def game_asset_batch(asset_brief: str) -> str:
        """Generate a coherent batch of game assets from a brief."""
        return f"""Generate a game-asset batch in the studio from this brief:

{asset_brief}

1. create_project(kind="game") if none exists — one project per game.
2. Pick a style (list_styles) and keep it fixed for the whole batch so the
   art direction reads as one game.
3. Use generate_image with frames>1 and a shared seed for families of
   related assets (character turnarounds, tile variants, item sets) —
   shared seed + style keeps them coherent. Set width/height to the asset's
   real use: square for icons/sprites, wide for backdrops/key art.
4. For animated flourishes (menu backgrounds, cutscene beats), use
   generate_video with camera presets, or apply_effects on stills that were
   pooled into the project.
5. upscale_asset the hero pieces (key art, marketing) as a finishing pass.
6. Report every generated asset id with its role; a human approves them in
   the panel before anything auto-selects them."""

    @server.prompt()
    def youtube_video_workflow(topic: str) -> str:
        """Produce a full YouTube video: avatar + b-roll + thumbnail."""
        return f"""Produce a YouTube video in the studio on this topic:

{topic}

1. create_project(kind="video").
2. Write a tight script (short sentences — each becomes a TTS segment).
3. list_voices_and_loops; create_avatar_job with the script.
4. While it renders: generate_image for a thumbnail (generate_thumbnail
   with the video title) and generate_music for a bed.
5. avatar_job_status until the job reaches review, then hand off: a human
   previews and publishes in the panel — publishing is never automated,
   and uploads always land private with the synthetic-media disclosure."""

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
