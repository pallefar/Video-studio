"""Generation execution shared by both lanes (M10).

The provider class decides the lane: local models run on the wan queue under
the exclusive GPU lock (worker_gpu.stages.generation_stage_local); API models
run as network jobs on the cpu queue (worker_cpu.stages.generation_stage_api).
On failure the fallback chain re-dispatches the next target to whichever lane
it belongs to. Success always lands an Asset with origin='generated' — the
only door into the pipeline.
"""

from __future__ import annotations

import uuid
from typing import Optional

import structlog

from pipeline_core.db import open_session
from pipeline_core.dispatch import Dispatcher
from pipeline_core.embeddings import get_embedder
from pipeline_core.providers import (
    CLASS_LOCAL,
    LANE_SHARED,
    ProviderRegistry,
    build_registry,
)
from pipeline_core.queues import QUEUE_CPU, QUEUE_GPU, QUEUE_WAN
from pipeline_core.stock import download
from pipeline_core.storage import ObjectStore
from schema.models import (
    Asset,
    AssetOrigin,
    Generation,
    GenerationStatus,
    ProjectAsset,
    utcnow,
)

log = structlog.get_logger()

_EXTENSIONS = {
    "video/mp4": "mp4",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/flac": "flac",
}

STAGE_LOCAL = "worker_gpu.stages.generation_stage_local"
STAGE_SHARED = "worker_gpu.stages.generation_stage_shared"
STAGE_API = "worker_cpu.stages.generation_stage_api"


def enqueue_generation(
    dispatcher: Dispatcher, generation: Generation, registry: Optional[ProviderRegistry] = None
) -> None:
    registry = registry or build_registry()
    _, spec = registry.resolve(generation.provider, generation.model, generation.kind)
    if spec.provider_class == CLASS_LOCAL:
        # lane routing (roadmap-v2 §5): shared residents ride the render
        # queue; the 14B-class models take the exclusive wan lane.
        if getattr(spec, "lane", None) == LANE_SHARED:
            queue, stage = QUEUE_GPU, STAGE_SHARED
        else:
            queue, stage = QUEUE_WAN, STAGE_LOCAL
    else:
        queue, stage = QUEUE_CPU, STAGE_API
    dispatcher.enqueue(
        queue, stage, str(generation.id), job_key=f"gen-{generation.id}-{generation.provider}"
    )


def run_generation(
    generation_id: str,
    registry: Optional[ProviderRegistry] = None,
    store: Optional[ObjectStore] = None,
    dispatcher: Optional[Dispatcher] = None,
) -> None:
    registry = registry or build_registry()
    store = store or ObjectStore()

    with open_session() as session:
        generation = session.get(Generation, uuid.UUID(generation_id))
        if generation is None:
            raise ValueError(f"generation {generation_id} not found")
        if generation.status == GenerationStatus.succeeded:
            log.info("generation_skip_idempotent", generation_id=generation_id)
            return
        if generation.status == GenerationStatus.cancelled:
            # cancelled while still queued — the RQ job fires anyway, so the
            # worker honours the cancellation here
            log.info("generation_skip_cancelled", generation_id=generation_id)
            return

        generation.status = GenerationStatus.running
        generation.updated_at = utcnow()
        session.add(generation)
        session.commit()

        try:
            provider, _ = registry.resolve(generation.provider, generation.model, generation.kind)
            result = provider.generate(generation)
            data = result.data if result.data is not None else download(result.download_url)
        except Exception as exc:
            fallback = list(generation.fallback or [])
            if fallback:
                next_target = fallback.pop(0)
                log.warning(
                    "generation_fallback",
                    generation_id=generation_id,
                    failed=f"{generation.provider}/{generation.model}",
                    next=f"{next_target['provider']}/{next_target['model']}",
                    error=str(exc),
                )
                generation.provider = next_target["provider"]
                generation.model = next_target["model"]
                generation.fallback = fallback
                generation.status = GenerationStatus.queued
                generation.error = f"{type(exc).__name__}: {exc}"
                generation.updated_at = utcnow()
                session.add(generation)
                session.commit()
                enqueue_generation(dispatcher or Dispatcher(), generation, registry)
                return
            generation.status = GenerationStatus.failed
            generation.error = f"{type(exc).__name__}: {exc}"
            generation.updated_at = utcnow()
            session.add(generation)
            session.commit()
            raise

        extension = _EXTENSIONS.get(result.content_type, "bin")
        key = f"generations/{generation_id}/output.{extension}"
        uri = store.put_bytes(key, data, content_type=result.content_type)

        asset = Asset(
            origin=AssetOrigin.generated,
            uri=uri,
            caption=generation.prompt,
            has_identifiable_people=False,
            # licence provenance rides in on the request (e.g. M18 music beds
            # record the generating model's clean licence)
            license=(generation.params or {}).get("asset_license"),
            approved=False,  # human approval gate before the resolver may pick it
            embedding=get_embedder().embed(generation.prompt),
        )
        session.add(asset)
        session.commit()

        if generation.project_id is not None:
            session.add(ProjectAsset(project_id=generation.project_id, asset_id=asset.id))
            session.commit()

        generation.asset_id = asset.id
        generation.external_id = result.external_id
        generation.cost = result.cost
        generation.status = GenerationStatus.succeeded
        generation.error = None
        generation.updated_at = utcnow()
        session.add(generation)
        session.commit()
        log.info(
            "generation_succeeded",
            generation_id=generation_id,
            provider=generation.provider,
            model=generation.model,
            uri=uri,
            cost=result.cost,
        )
