<!-- refreshed: 2026-08-02 -->
# Architecture

**Analysis Date:** 2026-08-02

## System Overview

Self-hosted AI video studio: a multi-stage asynchronous job pipeline built on FastAPI (API), Redis+RQ (queues), and distributed workers. The system processes renders (avatar script → lipsync → video) and media generation (text→video, image generation, audio) through specialized queue lanes.

```text
┌──────────────────────────────────────────────────────────────────┐
│                     FastAPI Web Panel                            │
│                    `api/main.py:create_app()`                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Routes: jobs, generations, projects, assets, images, etc.   │ │
│  │ `api/routes/*.py` → single session per request via `api/db` │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                        React SPA                                  │
│                    `web/src/App.tsx`                              │
└──────────────┬───────────────────────────────────────────────────┘
               │ HTTP
               ▼
┌──────────────────────────────────────────────────────────────────┐
│           Dispatch & Queue Management Layer                      │
│          `packages/pipeline_core/dispatch.py`                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Dispatcher enqueues stage functions → Redis Queues:        │ │
│  │ • QUEUE_GPU (render: tts→lipsync→assemble, shared models) │ │
│  │ • QUEUE_WAN (exclusive GPU lock: Wan 2.x generation)      │ │
│  │ • QUEUE_CPU (API providers, ffmpeg assembly, publishing)  │ │
│  │ Each stage idempotent on (job_id, stage_key)              │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────┬───────────────────────────────────────────────────┘
               │ Redis
       ┌───────┴──────────┬──────────────┐
       │                  │              │
       ▼                  ▼              ▼
┌─────────────────┐┌──────────────┐┌──────────────┐
│ GPU Worker      ││ WAN Worker   ││ CPU Worker   │
│ (Render Lane)   ││(B-roll Lane) ││(API / FFmpeg)│
│ Concurrency: 1  ││Concurrency: 1││Concurrency:N │
│ `worker_gpu/`   ││`worker_gpu/` ││`worker_cpu/` │
│ • tts_stage     ││• generation_ ││• generation_ │
│ • lipsync_stage ││  stage_local ││  stage_api   │
│ • assemble_stage││• comfy exec  ││• ffmpeg      │
│ (shared models) ││ (Wan, SDXL)  ││• publish     │
└─────────────────┘└──────────────┘└──────────────┘
       │                  │              │
       ▼                  ▼              ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Single Source of Truth                          │
│              `packages/schema/models.py`                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ SQLModel entities (table + validation):                    │ │
│  │ • RenderJob, Segment (avatar workflow)                    │ │
│  │ • Generation, Asset (media generation / library)          │ │
│  │ • Project, VoiceProfile, BaseLoop, Identity              │ │
│  │ • PublishRecord (compliance audit trail)                 │ │
│  └─────────────────────────────────────────────────────────────┘ │
│          TS types auto-generated: `packages/schema/export_ts.py`  │
└──────────────┬───────────────────────────────────────────────────┘
               │ SQLAlchemy ORM
               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Persistence Layer                             │
│  ┌──────────────────────────┐    ┌─────────────────────────────┐ │
│  │ PostgreSQL Database      │    │ ObjectStore (S3/MinIO)      │ │
│  │ `packages/pipeline_core/`│    │ `packages/pipeline_core/`   │ │
│  │ • Metadata, job state    │    │ • All artifacts (audio,     │ │
│  │ • Compliance records     │    │   video, images, models)    │ │
│  │ • Asset library          │    │ • Private by construction   │ │
│  │ • alembic/ migrations    │    │ • No public ACL methods     │ │
│  └──────────────────────────┘    └─────────────────────────────┘ │
│                                                                   │
│                 Redis (queue broker + locks)                     │
│                                                                   │
│                ComfyUI Headless (optional, env-gated)            │
│                  `packages/pipeline_core/comfy.py`               │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| **FastAPI App** | HTTP API, route handling, session management | `api/main.py` |
| **Route Handlers** | Entity CRUD, job lifecycle, validation | `api/routes/*` |
| **Validators** | Compliance gates (C1–C5) | `api/validators/compliance.py` |
| **Dispatcher** | Enqueue stage functions to Redis | `packages/pipeline_core/dispatch.py` |
| **GPU Worker** | TTS, lipsync, assemble stages (render lane) | `worker_gpu/run.py`, `worker_gpu/stages.py` |
| **WAN Worker** | Wan 2.x generation (exclusive GPU lock) | `worker_gpu/run_wan.py` |
| **CPU Worker** | API generation, ffmpeg assembly, publish | `worker_cpu/run.py`, `worker_cpu/stages.py` |
| **ObjectStore** | S3/MinIO artifact storage (single interface) | `packages/pipeline_core/storage.py` |
| **Schema/Models** | Single source of truth, ORM entities, validators | `packages/schema/models.py` |
| **ComfyUI Client** | Headless workflow executor (local generation) | `packages/pipeline_core/comfy.py` |
| **React Panel** | UI: jobs, generation, library, editor | `web/src/App.tsx`, `web/src/components/*` |
| **MCP Server** | LLM-driven studio control (human-approved gates only) | `studio_mcp/server.py` |

## Pattern Overview

**Overall:** Asynchronous job pipeline with stage-based idempotency and exclusive GPU lane management.

**Key Characteristics:**
- Jobs flow through named stages (tts → lipsync → assemble → review → publishing → published) with valid state transitions enforced in `schema/models.py`
- Each stage is idempotent on `(job_id, stage)` — re-running a stage is safe, and stages skip if the job has moved past them
- Three queue lanes (GPU render, WAN b-roll, CPU api/ffmpeg) with exclusive GPU lock preventing concurrent access
- Stateless workers consuming from Redis queues — all configuration from env, all artifacts from ObjectStore
- Compliance gates at API edge (Create schemas) + publish phase (`api/validators/compliance.py`)

## Layers

**API/HTTP Layer:**
- Purpose: HTTP request dispatch, validation, session management
- Location: `api/`
- Contains: FastAPI app factory, route handlers, session management, compliance validators
- Depends on: SQLModel (schema), Dispatcher (queue enqueue), pipeline_core utilities
- Used by: Web panel (React), MCP server, external clients

**Dispatcher/Queue Layer:**
- Purpose: Decouple job creation from execution; queue stage functions by import path
- Location: `packages/pipeline_core/dispatch.py`
- Contains: `Dispatcher` class, queue name constants, default job timeout
- Depends on: Redis client, `pipeline_core.settings`
- Used by: All routes that enqueue work (jobs, generations)

**Worker Layer (GPU/WAN/CPU):**
- Purpose: Execute stage functions in parallel, consume Redis queues
- Location: `worker_gpu/`, `worker_cpu/`
- Contains: Stage functions, engine wrappers (TTS, lipsync, ComfyUI), ffmpeg assembly, publish flow
- Depends on: Pipeline_core (dispatch, storage, metrics, db), schema (models), provider libraries
- Used by: Queue consumers

**Storage Layer:**
- Purpose: Centralized S3-compatible artifact I/O; no public ACL paths
- Location: `packages/pipeline_core/storage.py`
- Contains: `ObjectStore` class with put/get operations for files and bytes
- Depends on: boto3, `pipeline_core.settings`
- Used by: All workers and generation code

**Schema/Model Layer:**
- Purpose: Single source of truth for all entities; TS types auto-generated
- Location: `packages/schema/models.py`
- Contains: SQLModel table classes (RenderJob, Segment, Asset, etc.), enums (JobStatus, GenerationKind), validators, compliance rules
- Depends on: Pydantic, SQLModel, SQLAlchemy
- Used by: API routes, workers, schema export

**ComfyUI Integration:**
- Purpose: Execute local generation workflows (Wan, SDXL, etc.) via headless ComfyUI
- Location: `packages/pipeline_core/comfy.py`, `packages/pipeline_core/workflows/*.json`
- Contains: Template loader, graph injection, polling executor
- Depends on: httpx, `pipeline_core.settings`, schema
- Used by: `worker_gpu.stages.generation_stage_local`, `worker_gpu.stages.generation_stage_shared`

**UI Layer:**
- Purpose: React SPA for studio control
- Location: `web/src/`
- Contains: View components (Avatar, Dashboard, Library, Editor, etc.), API client hooks, theme/toast utilities
- Depends on: React, TypeScript, auto-generated schema types
- Used by: Users in the web browser

## Data Flow

### Primary Render Job Flow (Avatar)

1. **Create Job** (`api/routes/jobs.py:create_job`) — User submits script + voice + base loop
   - Validates RenderJobCreate, creates RenderJob and Segments
   - Commits to database
   - Dispatcher.enqueue("gpu", "worker_gpu.stages.tts_stage", job_id)
   - Returns RenderJobRead

2. **TTS Stage** (`worker_gpu/stages.py:tts_stage`) — GPU worker processes
   - Loads job from DB, checks idempotency (job.status must be queued or tts)
   - Acquires gpu_lock (HOLDER_RENDER)
   - Calls ChatterboxEngine.synthesize_segment() for pending segments
   - Writes audio_uri and duration_ms per segment, commits after each for crash safety
   - Advances job status to lipsync → enqueues next stage

3. **Lipsync Stage** (`worker_gpu/stages.py:lipsync_stage`)
   - Loads job, acquires gpu_lock
   - Calls MuseTalkEngine.lip_sync() per segment
   - Writes lipsync output URIs
   - Advances job status to assemble

4. **Assemble Stage** (`worker_gpu/stages.py:assemble_stage`)
   - Loads job, acquires gpu_lock (last GPU use)
   - Calls assembler.compose() with lipsync results + base loop
   - Writes final output_uri
   - Advances job status to review

5. **Review** (Human) — Panel shows preview, user accepts or rejects
   - POST `/jobs/{id}/review` → validates → transitions to publishing or queued

6. **Publish Stage** (`worker_cpu/stages.py:publish_stage`) — CPU worker
   - Validates compliance (watermark must persist, publish.altered_content must be true)
   - Uploads to YouTube private (if configured), writes PublishRecord
   - Advances job to published

**State Machine:** queued → tts → lipsync → assemble → review → publishing → published (or failed, or cancelled at any point)

### Generation Flow (Media Assets)

1. **Create Generation** (`api/routes/generations.py:create_generation`)
   - Validates GenerationCreate (provider, model, kind, parameters)
   - Creates Generation with status=queued
   - Dispatcher routes based on provider class:
     - `CLASS_LOCAL` + `LANE_SHARED` → enqueue to QUEUE_GPU, generation_stage_shared
     - `CLASS_LOCAL` → enqueue to QUEUE_WAN, generation_stage_local
     - API class → enqueue to QUEUE_CPU, generation_stage_api

2. **Generation Stage (Local)** (`worker_gpu/stages.py:generation_stage_local`)
   - Acquires gpu_lock (HOLDER_WAN)
   - Loads ComfyUI template for the model
   - Calls inject() to patch parameters into workflow
   - Polls ComfyUI /history API until complete
   - Downloads outputs via /view
   - Creates Asset with origin='generated' and writes embedding
   - Updates Generation status to succeeded

3. **Generation Stage (API)** (`worker_cpu/stages.py:generation_stage_api`)
   - No GPU lock (runs on CPU queue)
   - Calls provider client (fal, Replicate, etc.)
   - Polls provider status
   - Downloads result, creates Asset, updates Generation

4. **Fallback Chain:** On failure, next provider in generation.targets is enqueued to the appropriate queue

**Asset Entry:** Only path into the asset library is origin='generated' from a successful generation or origin='stock' from ingest with license+source_url

### State Management

- **Job State:** Stored in RenderJob.status (enum), enforced transitions in VALID_TRANSITIONS dict
- **Segment State:** Individual fields (audio_uri, duration_ms, etc.) on Segment; no status column
- **Generation State:** Stored in Generation.status, provider/model/targets in Generation record
- **Transient State:** GPU locks (Redis) prevent concurrent render/wan access; stage_key idempotency via RQ job_id

## Key Abstractions

**Stage Function:**
- Purpose: Idempotent unit of work, registered by import path string
- Examples: `"worker_gpu.stages.tts_stage"`, `"worker_gpu.stages.lipsync_stage"`, `"worker_cpu.stages.generation_stage_api"`
- Pattern: Takes job_id (or generation_id) as string, reads from DB, acquires GPU lock if needed, mutates state, advances status, enqueues next stage

**Queue Lane:**
- Purpose: Redis queue + concurrency model for a class of work
- Examples: QUEUE_GPU (concurrency 1), QUEUE_WAN (concurrency 1, exclusive lock), QUEUE_CPU (concurrency N)
- Pattern: Worker pulls from named queue, executes stage function, raises or completes

**GPU Lock:**
- Purpose: Exclusive access control for shared 24 GB GPU memory
- Implementation: Redis key with TTL; render lane (HOLDER_RENDER) and wan lane (HOLDER_WAN) are separate holders
- Pattern: `with gpu_lock(redis, HOLDER_RENDER): ...` blocks if other holder has lock; raises GpuLockHeld if already held

**ObjectStore (S3/MinIO):**
- Purpose: Single abstraction for artifact storage; no code outside storage.py calls boto3
- Methods: put_bytes(), get_bytes(), put_file(), get_file(), exists(), list_keys(), usage()
- Guarantee: No public ACL paths; ACL parameter deliberately omitted

**Provider & Registry:**
- Purpose: Model aggregation over local + API providers
- Examples: ProviderRegistry.resolve(provider, model, kind) → (engine, spec)
- Pattern: Spec includes provider_class, lane, and endpoint; registry routes generation to appropriate worker

## Entry Points

**API Server:**
- Location: `api/main.py:create_app()`
- Triggers: `uvicorn api.main:app` or `python -m uvicorn api.main:app`
- Responsibilities: Create FastAPI app, register routes, optionally mount SPA from web/dist

**GPU Worker:**
- Location: `worker_gpu/run.py:main()`
- Triggers: `python worker_gpu/run.py` or boot-time service start
- Responsibilities: Load models (TTS, lipsync) at startup, connect to Redis, consume QUEUE_GPU indefinitely

**WAN Worker:**
- Location: `worker_gpu/run_wan.py:main()`
- Triggers: `python worker_gpu/run_wan.py` (if separate process)
- Responsibilities: Load generation models (Wan, SDXL), consume QUEUE_WAN with exclusive GPU lock

**CPU Worker:**
- Location: `worker_cpu/run.py:main()`
- Triggers: `python worker_cpu/run.py` or boot-time service start
- Responsibilities: Connect to Redis, consume QUEUE_CPU, execute API calls and ffmpeg jobs

**MCP Server:**
- Location: `studio_mcp/server.py:build_server()`
- Triggers: `python -m studio_mcp`
- Responsibilities: Build MCP server with studio tools, forbidden: publish/consent/approve (human-only)

## Architectural Constraints

- **Threading:** Single GPU worker concurrency (GPU_WORKER_CONCURRENCY = 1), enforced in tests/test_queue_topology.py. WAN and render lanes share the 24 GB via exclusive GPU lock. CPU worker concurrency unbounded.
- **Global state:** Engine singletons cached at module level in `worker_gpu/stages.py:_engines` (TTS, lipsync loaded once at boot). ComfyUI client cached on first use. Dispatcher singleton cached per route handler (Depends).
- **Circular imports:** None detected; workers never import from api/routes, API never imports worker code, schema is leaf dependency.
- **Idempotency:** Every stage is idempotent on (job_id, stage). Stages skip if job status has advanced past them. Enforced: RQ job_id = stage_key(job_id, stage).
- **No streaming/real-time:** Batch renderer only. No websockets, no push notifications — polling from panel via GET /jobs.

## Anti-Patterns

### Direct Database Mutations in Route Handlers Without Validation

**What happens:** A route creates a model instance directly via SQLModel constructor, bypassing Pydantic validators.

**Why it's wrong:** SQLModel `table=True` classes skip validation on instantiation. A RenderJob created without hitting RenderJobCreate validators could violate compliance rules (e.g., watermark.persistent).

**Do this instead:** Always validate at the API edge via Create schemas (`RenderJobCreate`, `AssetCreate`). Create instances from validated data:
```python
# routes/jobs.py:create_job()
body: RenderJobCreate  # Pydantic validates here
job = RenderJob(**body.model_dump(...))  # Safe: body is already valid
```

### Loading Models Per Job in Worker Code

**What happens:** A stage function calls `load_model()` for every job, thrashing VRAM and forcing evictions.

**Why it's wrong:** Models should load once at worker boot and stay resident. Every job hits disk/network for model weights, killing throughput.

**Do this instead:** Cache engines at module level and load once:
```python
# worker_gpu/stages.py
_engines = None  # Loaded at module import, stays resident

def get_engines():
    global _engines
    if _engines is None:
        tts, lipsync = ChatterboxEngine(...), MuseTalkEngine(...)
        tts.load()
        lipsync.load()
        _engines = (tts, lipsync)
    return _engines
```

### Hardcoding Service Endpoints in Worker Code

**What happens:** Worker code contains `redis_url = "localhost:6379"` or `s3_endpoint = "minio.local"`.

**Why it's wrong:** Workers must be portable to rented GPUs. Hardcoded endpoints fail in cloud.

**Do this instead:** Read all addresses from env via `pipeline_core.settings.Settings`:
```python
# worker_gpu/stages.py
from pipeline_core.settings import Settings
settings = Settings()  # REDIS_URL, S3_ENDPOINT from env
```

### Skipping Compliance Validators for Expedience

**What happens:** `publish_stage` skips C1 watermark check because "the UI won't send a job without one."

**Why it's wrong:** Validators exist to prevent accidental non-compliance. UI code is human-written; a bug can bypass checks.

**Do this instead:** Enforce validators in both places:
- API edge: Create schemas validate on ingest
- Publish gate: `api/validators/compliance.py` re-checks before publishing
```python
# api/validators/compliance.py
if not job.watermark.persistent:
    raise ValueError("C1: watermark.persistent must be true")
```

## Error Handling

**Strategy:** Fail fast with clear error messages; mark jobs failed with error details. Stages are retriable (stuck jobs can re-enqueue).

**Patterns:**

1. **Validation Errors** → 400/422 at API boundary, caught before job creation
2. **Missing Dependencies** → 404 (voice profile, base loop not found)
3. **Stage Execution Errors** → Job marked failed with error string:
   ```python
   # worker_gpu/stages.py:tts_stage()
   except Exception as exc:
       fail_job(session, job, f"tts: {exc}")
       raise  # RQ logs the exception
   ```
4. **GPU Lock Contention** → GpuLockHeld raised, job left in current status (retriable):
   ```python
   except GpuLockHeld:
       raise  # Job will re-enqueue automatically
   ```
5. **Transient Network Errors** (API providers, ComfyUI) → Logged, generation marked failed, fallback target enqueued

## Cross-Cutting Concerns

**Logging:** Structured logging via structlog. Every stage logs entry/exit with duration. GPU lock contention and provider fallbacks logged at info level.
```python
# worker_gpu/stages.py
log = structlog.get_logger()
log.info("tts_stage_entry", job_id=job_id)
log.info("tts_segment_done", job_id=job_id, idx=segment.idx, seed=segment.seed)
```

**Metrics:** Stage duration recorded to metrics table via `@timed_stage()` decorator for throughput/regression detection:
```python
# packages/pipeline_core/metrics.py
@timed_stage("tts")
def tts_stage(job_id: str) -> None:
    ...  # Duration auto-recorded to DB
```

**Validation:** Compliance rules (C1–C5) enforced at two gates:
- API edge: Create schemas and validators
- Publish gate: `api/validators/compliance.py:validate_publish()`

**Authentication:** Single-user localhost. No auth in routes. MCP server enforces human-only actions (publish, consent, approve) via tool absence, not auth.

---

*Architecture analysis: 2026-08-02*
