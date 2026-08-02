# Codebase Structure

**Analysis Date:** 2026-08-02

## Directory Layout

```
video-studio/
├── api/                          # FastAPI application and routes
│   ├── main.py                   # App factory: create_app()
│   ├── db.py                     # Session dependency injection
│   ├── routes/                   # API endpoint handlers
│   │   ├── jobs.py               # RenderJob CRUD, lifecycle
│   │   ├── generations.py        # Generation requests
│   │   ├── projects.py           # Project CRUD
│   │   ├── assets.py             # Asset library
│   │   ├── identities.py         # Identity training
│   │   ├── images.py             # Image generation
│   │   ├── audio.py              # Audio/voice profiles
│   │   ├── prompts.py            # Prompt library
│   │   ├── storyboards.py        # Storyboard creation
│   │   ├── timelines.py          # Timeline multi-track
│   │   ├── effects.py            # Effect presets
│   │   ├── emotions.py           # Emotion parameters
│   │   ├── presets.py            # Camera/style presets
│   │   ├── music.py              # Music generation
│   │   ├── voices.py             # Voice profile management
│   │   ├── publish.py            # YouTube publishing
│   │   ├── stats.py              # Dashboard stats
│   │   ├── metrics.py            # Performance metrics
│   │   ├── config.py             # Configuration endpoints
│   │   ├── loops.py              # Base loop management
│   │   ├── rentals.py            # GPU rental providers
│   │   └── __init__.py
│   ├── validators/               # Compliance and input validation
│   │   ├── compliance.py         # C1–C5 gates
│   │   └── __init__.py
│   └── __pycache__
│
├── worker_gpu/                   # GPU worker processes
│   ├── run.py                    # GPU worker entrypoint (render + shared models)
│   ├── run_wan.py                # WAN worker entrypoint (exclusive GPU lock)
│   ├── stages.py                 # Stage functions: tts, lipsync, assemble, generation
│   ├── engines/                  # Model wrappers
│   │   ├── tts.py                # Chatterbox TTS engine
│   │   ├── lipsync.py            # MuseTalk lipsync engine
│   │   ├── identity.py           # Identity training
│   │   ├── dev.py                # Dev placeholder engines
│   │   └── __init__.py
│   ├── preprocess/               # Model loading and preprocessing
│   │   ├── loop_cache.py         # Base loop preprocessing
│   │   └── __init__.py
│   └── __pycache__
│
├── worker_cpu/                   # CPU worker process
│   ├── run.py                    # CPU worker entrypoint
│   ├── stages.py                 # Stage functions: API generation, ffmpeg, publish
│   ├── publish.py                # YouTube upload logic
│   ├── ffmpeg/                   # FFmpeg operations
│   │   ├── ingest.py             # Stock/upload ingestion
│   │   ├── assemble.py           # Video assembly (fallback CPU path)
│   │   ├── compiler.py           # FFmpeg command building
│   │   ├── overlay.py            # Watermark overlay
│   │   └── __init__.py
│   └── __pycache__
│
├── packages/                     # Shared Python packages
│   ├── pipeline_core/            # Core pipeline logic
│   │   ├── __init__.py
│   │   ├── db.py                 # SQLModel engine, session management
│   │   ├── storage.py            # ObjectStore (S3/MinIO interface)
│   │   ├── dispatch.py           # Dispatcher, queue enqueue logic
│   │   ├── queues.py             # Queue constants, stage_key
│   │   ├── settings.py           # Configuration from env
│   │   ├── metrics.py            # Stage timing, @timed_stage decorator
│   │   ├── comfy.py              # ComfyUI headless client
│   │   ├── comfy_nodes.py        # Custom ComfyUI node definitions
│   │   ├── providers.py          # Provider registry, model specs
│   │   ├── generation.py         # Generation dispatch logic
│   │   ├── locks.py              # GPU lock implementation
│   │   ├── embeddings.py         # Asset embedding generation
│   │   ├── segmenting.py         # Script segmentation for TTS
│   │   ├── effects.py            # VFX effect chain
│   │   ├── enhance.py            # Prompt enhancement (Qwen/Ollama)
│   │   ├── emotions.py           # Speak-style emotion parameters
│   │   ├── chunking.py           # Video/audio chunking for processing
│   │   ├── captioner.py          # Florence-2 asset captioning
│   │   ├── seam.py               # Loop seam detection
│   │   ├── resolvers.py          # Asset selection (semantic search)
│   │   ├── styles.py             # Style template catalog
│   │   ├── presets.py            # Camera/effect preset catalog
│   │   ├── prompts.py            # Prompt library management
│   │   ├── stock.py              # Stock asset download (Pexels, Pixabay)
│   │   ├── rentals.py            # GPU rental provider clients
│   │   ├── workflows/            # ComfyUI workflow templates
│   │   │   ├── wan2.2-t2v.json   # Wan 2.2 text-to-video template
│   │   │   ├── wan2.2-i2v.json   # Wan 2.2 image-to-video template
│   │   │   ├── wan2.2-vace-1.3b.json  # VACE VFX template
│   │   │   ├── chatterbox.json   # Chatterbox TTS template (if ComfyUI-native)
│   │   │   ├── musetalk-image.json  # MuseTalk lipsync template
│   │   │   ├── sdxl.json         # SDXL image generation
│   │   │   ├── qwen-image.json   # Qwen image generation
│   │   │   └── ... (more templates)
│   │   └── __pycache__
│   │
│   └── schema/                   # Single source of truth
│       ├── models.py             # SQLModel entities, enums, validators
│       ├── export_ts.py          # TS type generator
│       ├── __init__.py
│       └── __pycache__
│
├── web/                          # React SPA
│   ├── src/
│   │   ├── App.tsx               # Main app shell, tab navigation
│   │   ├── main.tsx              # React entrypoint, theme provider
│   │   ├── lib.ts                # Theme, toast, utilities
│   │   ├── components/           # View components (one per tab)
│   │   │   ├── DashboardView.tsx # Home: stats, queues, storage
│   │   │   ├── ProjectsView.tsx  # Projects list
│   │   │   ├── CreateView.tsx    # Video generation with presets
│   │   │   ├── AvatarView.tsx    # Avatar/lipsync rendering
│   │   │   ├── ImagesView.tsx    # Image generation
│   │   │   ├── AudioView.tsx     # Audio/voice profiles
│   │   │   ├── PromptsView.tsx   # Prompt library
│   │   │   ├── StoryboardsView.tsx  # Storyboard planning
│   │   │   ├── EditorView.tsx    # Multi-track timeline editor
│   │   │   ├── LibraryView.tsx   # Asset library (approval gate)
│   │   │   ├── IdentitiesView.tsx   # Identity training + consent
│   │   │   ├── SettingsView.tsx  # Config, worker status
│   │   │   ├── charts.tsx        # Dashboard chart components
│   │   │   ├── Thumb.tsx         # Thumbnail component
│   │   │   └── __init__.ts (implicit)
│   │   ├── routes/               # If using routing (TBD)
│   │   ├── types/                # Auto-generated types
│   │   │   └── schema.ts         # Generated by export_ts.py
│   │   ├── lib/                  # Utilities
│   │   │   ├── toast.tsx         # Toast notification provider
│   │   │   └── (other utilities)
│   │   └── index.css             # Tailwind/global styles
│   ├── vite.config.ts            # Vite bundler config
│   ├── tsconfig.json             # TypeScript config
│   ├── package.json              # React dependencies
│   ├── dist/                     # Built SPA (npm run build)
│   └── node_modules/
│
├── studio_mcp/                   # MCP server for LLM control
│   ├── server.py                 # MCPServer builder, tool definitions
│   ├── client.py                 # HTTP client to studio API
│   ├── __main__.py               # Entrypoint: python -m studio_mcp
│   ├── __init__.py
│   └── __pycache__
│
├── tests/                        # Test suite
│   ├── test_queue_topology.py    # GPU concurrency = 1 assertion
│   ├── test_portability.py       # No hardcoded endpoints in workers
│   ├── test_gpu_exclusivity.py   # Render + WAN lock exclusivity
│   ├── test_compliance.py        # C1–C5 validation
│   ├── test_mcp.py               # MCP tool restrictions (no publish/consent)
│   ├── test_comfy.py             # Workflow template validation
│   ├── conftest.py               # Pytest fixtures
│   └── ... (many more test files)
│
├── scripts/                      # Utility scripts
│   ├── setup.sh                  # Bootstrap: dependencies, DB, bucket
│   ├── setup.ps1                 # Windows bootstrap
│   ├── dev_up.sh                 # Start stack (macOS/Linux)
│   ├── start.ps1                 # Start stack (Windows)
│   ├── verify_gpu.py             # GPU health check
│   ├── rent_gpu.sh               # Vast/RunPod provisioning
│   └── (other utilities)
│
├── deploy/                       # Service units
│   ├── launchd/                  # macOS launch agents
│   │   ├── studio.plist
│   │   └── studio-gpu.plist
│   └── systemd/                  # Linux systemd units
│       ├── studio.service
│       └── studio-gpu.service
│
├── alembic/                      # Database migrations
│   ├── versions/                 # Migration files
│   │   ├── 0001_initial.py       # Schema creation
│   │   ├── 0002_segments.py      # Segment table
│   │   └── ...
│   ├── env.py                    # Alembic config
│   ├── script.py.mako            # Migration template
│   └── alembic.ini
│
├── docs/                         # Documentation
│   ├── pipeline-spec.md          # Hardware, models, performance baseline
│   ├── roadmap-v2.md             # Feature roadmap, provider matrix
│   ├── milestones.md             # M1–M28 acceptance criteria
│   ├── psd.md                    # Compliance rules (C1–C5)
│   ├── mcp.md                    # MCP server usage
│   ├── workstation.md            # GPU host setup, ComfyUI config
│   ├── ops.md                    # Backup, restore, service units
│   ├── mac-dev.md                # Apple Silicon dev mode
│   └── (other docs)
│
├── .github/                      # GitHub workflows
│   └── workflows/                # CI/CD pipelines
│
├── .planning/                    # GSD phase docs
│   └── codebase/                 # This directory
│       ├── ARCHITECTURE.md
│       └── STRUCTURE.md
│
├── .env                          # Local config (DO NOT COMMIT SECRETS)
├── .env.example                  # Config template
├── .gitignore
├── docker-compose.yml            # Postgres, Redis, MinIO
├── pyproject.toml                # Python project config
├── CLAUDE.md                     # Architecture summary, hard constraints
├── README.md                     # Quick start guide
└── VERSION                       # Release version
```

## Directory Purposes

**`api/`:**
- Purpose: FastAPI HTTP server and route handlers
- Contains: App factory, route logic, compliance validators, session management
- Key files: `main.py` (app creation), `routes/*` (endpoint handlers), `db.py` (session dep)

**`worker_gpu/`:**
- Purpose: GPU worker processes for render pipeline and local generation
- Contains: Stage functions (TTS, lipsync, assemble, generation), engine wrappers, model loaders
- Key files: `run.py` (render worker), `run_wan.py` (WAN worker), `stages.py` (all stage functions), `engines/*` (model implementations)

**`worker_cpu/`:**
- Purpose: CPU worker for API providers, ffmpeg assembly, publishing
- Contains: Generation dispatch, ffmpeg operations, YouTube upload
- Key files: `run.py` (entrypoint), `stages.py` (API generation, publish), `ffmpeg/*` (video ops)

**`packages/pipeline_core/`:**
- Purpose: Shared core pipeline logic
- Contains: Dispatcher, ObjectStore, ComfyUI client, providers, metrics, locks, settings
- Key files: `dispatch.py` (queue enqueue), `storage.py` (S3 abstraction), `comfy.py` (workflow executor), `settings.py` (env config)

**`packages/schema/`:**
- Purpose: Single source of truth for all domain entities
- Contains: SQLModel tables, enums, validators, Pydantic models for API boundaries
- Key files: `models.py` (all entities), `export_ts.py` (TS type generator)

**`web/`:**
- Purpose: React SPA control panel
- Contains: View components per tab, API client, theme system, auto-generated types
- Key files: `src/App.tsx` (shell), `src/components/*` (views), `src/types/schema.ts` (generated types)

**`studio_mcp/`:**
- Purpose: MCP server for LLM-driven studio control
- Contains: Tool definitions, HTTP client wrapper, compliance boundaries
- Key files: `server.py` (MCPServer builder), `client.py` (API wrapper)

**`tests/`:**
- Purpose: Test suite covering queue topology, compliance, portability, workflows
- Contains: Unit and integration tests, fixtures, conftest
- Key files: `conftest.py` (fixtures), test_*.py (test modules)

**`scripts/`:**
- Purpose: Automation and utilities
- Contains: Setup/start scripts, GPU verification, rental provisioning
- Key files: `setup.sh` (bootstrap), `dev_up.sh` (dev start), `verify_gpu.py` (health check)

**`deploy/`:**
- Purpose: Service units for production bring-up
- Contains: systemd and launchd service definitions
- Key files: `launchd/*.plist` (macOS), `systemd/*.service` (Linux)

**`alembic/`:**
- Purpose: Database schema versioning and migrations
- Contains: Migration files, Alembic environment config
- Key files: `env.py` (config), `versions/*.py` (migrations)

**`docs/`:**
- Purpose: Architecture and operations documentation
- Key files: `pipeline-spec.md` (hardware/models), `roadmap-v2.md` (features), `psd.md` (compliance)

## Key File Locations

**Entry Points:**
- `api/main.py:create_app()` — API server factory
- `worker_gpu/run.py:main()` — GPU worker entrypoint
- `worker_cpu/run.py:main()` — CPU worker entrypoint
- `studio_mcp/__main__.py` — MCP server entrypoint
- `web/src/main.tsx` — React app entry
- `web/src/App.tsx` — React app shell and routing

**Configuration:**
- `packages/pipeline_core/settings.py` — All env vars parsed here
- `.env` — Local secrets (not committed)
- `.env.example` — Config template
- `alembic.ini` — Database migration config
- `docker-compose.yml` — Local stack (Postgres, Redis, MinIO)
- `pyproject.toml` — Python dependencies and project config
- `web/vite.config.ts` — Bundler config

**Core Logic:**
- `packages/schema/models.py` — Single source of truth for all entities
- `packages/pipeline_core/dispatch.py` — Queue dispatch and Dispatcher class
- `packages/pipeline_core/storage.py` — ObjectStore (S3/MinIO abstraction)
- `packages/pipeline_core/comfy.py` — ComfyUI workflow executor
- `packages/pipeline_core/providers.py` — Provider registry
- `api/validators/compliance.py` — Compliance gate validators
- `worker_gpu/stages.py` — All GPU stage functions
- `worker_cpu/stages.py` — CPU stage functions

**Testing:**
- `tests/conftest.py` — Pytest fixtures
- `tests/test_queue_topology.py` — Queue topology assertions
- `tests/test_portability.py` — Portability assertions
- `tests/test_compliance.py` — Compliance rule tests

**Type Generation:**
- `packages/schema/export_ts.py` — TS type generator
- `packages/schema/models.py:EXPORTED_MODELS, EXPORTED_ENUMS` — What to export

## Naming Conventions

**Files:**
- Routes: `api/routes/{entity}.py` (e.g., `jobs.py`, `generations.py`)
- Stages: `{worker_type}/stages.py` (e.g., `worker_gpu/stages.py`, `worker_cpu/stages.py`)
- Engines: `worker_gpu/engines/{model_name}.py` (e.g., `tts.py`, `lipsync.py`)
- FFmpeg: `worker_cpu/ffmpeg/{operation}.py` (e.g., `ingest.py`, `assemble.py`)
- Workflows: `packages/pipeline_core/workflows/{model}.json` (e.g., `wan2.2-t2v.json`)
- Tests: `tests/test_{feature}.py` (e.g., `test_compliance.py`)
- Migrations: `alembic/versions/{timestamp}_{description}.py`

**Directories:**
- Routes: `api/routes/`
- Workers: `worker_{device_type}/` (gpu, cpu)
- Packages: `packages/{module}/`
- Services: `{service_name}/` (studio_mcp, web)
- Tests: `tests/`
- Utilities: `scripts/`
- Deployment: `deploy/`

**Classes:**
- SQLModel tables: PascalCase (e.g., `RenderJob`, `VoiceProfile`, `Segment`)
- API create schemas: `{Entity}Create` (e.g., `RenderJobCreate`, `AssetCreate`)
- API read schemas: `{Entity}Read` (e.g., `RenderJobRead`, `AssetRead`)
- Base classes: `{Entity}Base` (e.g., `RenderJobBase`, `AssetBase`)
- Enums: PascalCase (e.g., `JobStatus`, `GenerationKind`, `AssetOrigin`)
- Workers: `{Model}Engine` (e.g., `ChatterboxEngine`, `MuseTalkEngine`)
- Providers: `{Service}Provider` or `{Model}Provider`

**Functions:**
- Stage functions: `{stage_name}_stage()` (e.g., `tts_stage`, `lipsync_stage`, `generation_stage_local`)
- Private helpers: `_snake_case()` (e.g., `_get_job()`, `_read_model()`)
- Async route handlers: `async def {action}_{entity}()` (e.g., `async def create_job()`)

**Variables:**
- Queue names: `QUEUE_{DEVICE}` (e.g., `QUEUE_GPU`, `QUEUE_CPU`, `QUEUE_WAN`)
- Lock holders: `HOLDER_{LANE}` (e.g., `HOLDER_RENDER`, `HOLDER_WAN`)
- Enums: UPPERCASE (e.g., `JobStatus.queued`, `GenerationKind.text_to_video`)

## Where to Add New Code

**New API Endpoint:**
1. Add entity to `packages/schema/models.py` (XBase, X table=True, XCreate, XRead)
2. Run `python packages/schema/export_ts.py` to update TS types
3. Create route handler in `api/routes/{entity}.py`
4. Register router in `api/main.py:create_app()`
5. Add compliance validators if needed in `api/validators/compliance.py`

**New Generation Model/Provider:**
1. Add model spec to `packages/pipeline_core/providers.py:PROVIDERS` (or provider client file)
2. Create stage function in `worker_cpu/stages.py` if API provider, or `worker_gpu/stages.py` if local
3. Create workflow template in `packages/pipeline_core/workflows/{model}.json` if ComfyUI-based
4. Add tests in `tests/test_{provider}.py`

**New Worker Functionality:**
- Render lane: Add stage to `worker_gpu/stages.py`, update stage dispatch in `api/routes/`
- API lane: Add stage to `worker_cpu/stages.py`
- New engine: Create `worker_gpu/engines/{engine_name}.py` with load() and execute methods
- New ffmpeg operation: Create `worker_cpu/ffmpeg/{operation}.py` with builder functions

**New UI View/Component:**
1. Create `web/src/components/{FeatureName}View.tsx`
2. Add tab name to `web/src/App.tsx:type Tab`
3. Add icon to `ICONS` dict, title to `TITLES` dict, add to group in `GROUPS`
4. Import component in `App.tsx` and wire up in render

**New Configuration Parameter:**
1. Add field to `packages/pipeline_core/settings.py:Settings` class
2. Provide default or document requirement
3. Document in `.env.example`
4. Access via `settings = Settings()` in code

**Database Migration:**
1. Run `alembic revision --autogenerate -m "description"`
2. Edit `alembic/versions/{timestamp}_description.py`
3. Run `alembic upgrade head` to apply
4. Commit migration file

## Special Directories

**`web/dist/`:**
- Purpose: Built SPA (created by `npm run build`)
- Generated: Yes
- Committed: No
- Mounted by `api/main.py:create_app()` when present; production mode serves SPA from API

**`avatar_pipeline.egg-info/`:**
- Purpose: Package metadata (created by `pip install -e .`)
- Generated: Yes
- Committed: No

**`.venv/`:**
- Purpose: Python virtual environment
- Generated: Yes (by setup.sh)
- Committed: No

**`.pytest_cache/`:**
- Purpose: Pytest cache
- Generated: Yes
- Committed: No

**`alembic/versions/__pycache__/`:**
- Purpose: Python bytecode for migrations
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-08-02*
