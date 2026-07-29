from __future__ import annotations

from fastapi import FastAPI

from api.routes import (
    assets,
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
    app.include_router(publish.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
