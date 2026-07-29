from __future__ import annotations

from fastapi import FastAPI

from api.routes import (
    assets,
    generations,
    jobs,
    loops,
    presets,
    publish,
    storyboards,
    voices,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Avatar Render Pipeline", version="0.1.0")
    app.include_router(jobs.router)
    app.include_router(loops.router)
    app.include_router(voices.router)
    app.include_router(assets.router)
    app.include_router(generations.router)
    app.include_router(presets.router)
    app.include_router(storyboards.router)
    app.include_router(publish.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
