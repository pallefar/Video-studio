from __future__ import annotations

from fastapi import FastAPI

from api.routes import (
    assets,
    config,
    effects,
    emotions,
    generations,
    identities,
    images,
    jobs,
    loops,
    metrics,
    music,
    presets,
    projects,
    publish,
    stats,
    storyboards,
    timelines,
    voices,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Avatar Render Pipeline", version="0.1.0")
    app.include_router(jobs.router)
    app.include_router(loops.router)
    app.include_router(voices.router)
    app.include_router(assets.router)
    app.include_router(effects.router)
    app.include_router(emotions.router)
    app.include_router(generations.router)
    app.include_router(identities.router)
    app.include_router(images.router)
    app.include_router(presets.router)
    app.include_router(projects.router)
    app.include_router(storyboards.router)
    app.include_router(timelines.router)
    app.include_router(metrics.router)
    app.include_router(music.router)
    app.include_router(stats.router)
    app.include_router(config.router)
    app.include_router(publish.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Production panel: serve the built SPA straight from the API when
    # web/dist exists (npm run build), so the studio is one uvicorn process
    # on 127.0.0.1 — no vite dev server, no Node runtime. Mounted last: API
    # routes always win, the mount only catches what they didn't.
    from pathlib import Path

    dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="panel")

    return app


app = create_app()
