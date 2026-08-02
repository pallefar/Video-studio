# External Integrations

**Analysis Date:** 2026-08-02

## APIs & External Services

**Generation Providers (M10):**

**Local (ComfyUI-based):**
- Service: ComfyUI headless (self-hosted sidecar)
- SDK/Client: httpx (custom HTTP wrapper in `packages/pipeline_core/comfy.py`)
- Configuration: `COMFY_URL` (e.g., `http://localhost:8188`)
- Authentication: None (local network only)
- What it's used for:
  - Text-to-video via Wan 2.2 / Wan 2.1-1.3B (open-source models)
  - Image-to-video (Uni3C, ReCamMaster)
  - Image generation (Z-Image-Turbo, Qwen-Image, SDXL)
  - VFX & upscaling (VACE, SeedVR2-3B, Real-ESRGAN, FILM interpolation)
  - Audio (ACE-Step music, MuseTalk talking images, Chatterbox voiceovers)
- File: `packages/pipeline_core/comfy.py`
- Workflow templates: `packages/pipeline_core/workflows/*.json` (one per local model)
- Poll interval: `COMFY_POLL_INTERVAL_S` (default 2.0s), timeout: `COMFY_TIMEOUT_S` (default 3600s)
- Provider class: `LocalWanProvider` (`packages/pipeline_core/providers.py`)

**fal.ai (aggregator API):**
- Service: fal.ai queue API (https://queue.fal.run/)
- SDK/Client: httpx (custom polling in `FalProvider`)
- Configuration: `FAL_API_KEY`
- Authentication: Bearer token in `Authorization: Key {FAL_API_KEY}` header
- What it's used for:
  - Kling Video v2 (text-to-video, image-to-video) - $1.40/generation
  - Seedance (text/image-to-video) - $0.74/generation
  - Hailuo/Minimax (text-to-video) - $0.48/generation
  - Flux (image generation) - $0.003/generation
- File: `packages/pipeline_core/providers.py` (class `FalProvider`)
- Job polling: submit → poll `/status` → fetch response URL
- Provider class: `FalProvider` (CLASS_API, runs on CPU queue)

**ElevenLabs (direct API):**
- Service: ElevenLabs API (https://api.elevenlabs.io)
- SDK/Client: httpx (custom client in `ElevenLabsProvider`)
- Configuration: `ELEVENLABS_API_KEY`
- Authentication: `xi-api-key: {ELEVENLABS_API_KEY}` header
- What it's used for:
  - Text-to-speech voiceovers (`eleven-tts`) - $0.15/generation, 70+ languages
  - Sound effects generation (`eleven-sfx`) - $0.08/generation, max 22s
  - Music track generation (`eleven-music`) - $0.50/generation via Eleven Music
- File: `packages/pipeline_core/providers.py` (class `ElevenLabsProvider`)
- Default voice: Rachel (ID: 21m00Tcm4TlvDq8ikWAM)
- Default TTS model: `eleven_multilingual_v2`
- Provider class: `ElevenLabsProvider` (CLASS_API, runs on CPU queue)
- Note: Commercial use requires paid ElevenLabs plan; licence recorded on each asset

**OpenAI Sora (text-to-video):**
- Service: OpenAI API (https://api.openai.com)
- SDK/Client: httpx (custom client in `SoraProvider`)
- Configuration: `OPENAI_API_KEY`
- Authentication: `Authorization: Bearer {OPENAI_API_KEY}` header
- What it's used for:
  - Sora 2 (text-to-video, 720p) - $0.80/generation (8s clip)
  - Sora 2 Pro (higher fidelity, slower) - $2.40/generation (8s clip)
- File: `packages/pipeline_core/providers.py` (class `SoraProvider`)
- Supported durations: 4s, 8s, 12s (API constraint)
- Aspect ratios: 9:16 (portrait) or 16:9 (landscape)
- Job pattern: create → poll `/videos/{video_id}` → download `/videos/{video_id}/content`
- Provider class: `SoraProvider` (CLASS_API, runs on CPU queue)

**Google Veo (text-to-video via Gemini API):**
- Service: Google Generative Language API (https://generativelanguage.googleapis.com)
- SDK/Client: httpx (custom client in `VeoProvider`)
- Configuration: `GEMINI_API_KEY`
- Authentication: `x-goog-api-key: {GEMINI_API_KEY}` header
- What it's used for:
  - Veo 3.0 (standard, with audio) - $6.00/generation
  - Veo 3.0 Fast (faster + cheaper) - $3.20/generation
- File: `packages/pipeline_core/providers.py` (class `VeoProvider`)
- Fixed clip length: 8 seconds
- Aspect ratios: 9:16 (portrait) or 16:9 (landscape)
- Job pattern: predictLongRunning → poll operation → fetch video (base64 or URI)
- Provider class: `VeoProvider` (CLASS_API, runs on CPU queue)

**Provider Registration:**
- Central registry: `packages/pipeline_core/providers.py::build_registry()`
- Providers registered only if API key is configured (no key = provider unavailable)
- API endpoint: `GET /generations/catalog` - lists all registered providers and models
- File: `api/routes/generations.py`

## Data Storage

**Databases:**

**PostgreSQL 16:**
- Connection: `postgresql+psycopg://[user]:[pass]@[host]:[port]/[dbname]` via `DATABASE_URL`
- Client: psycopg (binary) via SQLAlchemy/SQLModel
- Schema:
  - Jobs, Generations, Assets, PublishRecords, Identities, Projects, etc.
  - Migrations: Alembic (if present, in `alembic/` directory)
  - File: `packages/schema/models.py`
- Purpose: Transactional state for jobs, users, generated content, compliance records

**Redis 7:**
- Connection: `redis://[host]:[port]/[db]` via `REDIS_URL`
- Client: `redis-py` package
- Purpose: Job queue (RQ), caching, temporary state
- Queues: `gpu` (exclusive, concurrency=1), `cpu`, `wan`
- Data persistence: Redis dump.rdb file (via Docker volume locally)

**File Storage:**

**MinIO / S3-Compatible Object Storage:**
- Endpoint: `S3_ENDPOINT` (e.g., `http://localhost:9000` for MinIO, AWS S3 URL for production)
- Access: `S3_ACCESS_KEY` / `S3_SECRET_KEY`
- Bucket: `S3_BUCKET` (default: `avatar-pipeline`)
- Region: `S3_REGION` (default: `us-east-1`)
- Client: boto3 (via `packages/pipeline_core/storage.py::ObjectStore`)
- Purpose: Persistent storage for generated videos, images, audio, uploads
- Key paths:
  - `assets/uploads/` - User-uploaded media
  - `generations/` - Generated outputs
  - `jobs/` - Job-related artifacts
- Design: All objects stored private; no public ACL method exposed

## Authentication & Identity

**YouTube OAuth 2.0:**
- OAuth Provider: Google (https://oauth2.googleapis.com)
- Grant Type: Refresh Token Flow
- Configuration:
  - `YOUTUBE_CLIENT_ID` - OAuth client ID
  - `YOUTUBE_CLIENT_SECRET` - OAuth client secret
  - `YOUTUBE_REFRESH_TOKEN` - Refresh token (one-time consent flow required)
  - `YOUTUBE_TOKEN_URI` - Token endpoint (default: `https://oauth2.googleapis.com/token`)
- Purpose: Publish videos to YouTube (private by default)
- Implementation: `worker_cpu/publish.py::YouTubeDataApiClient` (google-api-python-client wrapper)
- File: `worker_cpu/publish.py`
- Process: Videos uploaded PRIVATE always; C5 compliance gate enforced

## External Services - Stock Media

**Pexels API:**
- Endpoint: https://api.pexels.com
- SDK/Client: httpx (custom provider in `stock.py`)
- Configuration: `PEXELS_API_KEY`
- Authentication: `Authorization: {PEXELS_API_KEY}` header
- What it's used for: Video and photo search (stock media asset library)
- Video endpoint: `https://api.pexels.com/videos/search`
- Photo endpoint: `https://api.pexels.com/v1/search`
- License: Pexels License (permissive)
- File: `packages/pipeline_core/stock.py` (class `PexelsProvider`)
- Provider class: Can be disabled if API key not configured

**Pixabay API:**
- Endpoint: https://pixabay.com/api/
- SDK/Client: httpx (custom provider in `stock.py`)
- Configuration: `PIXABAY_API_KEY`
- Authentication: Query parameter `key={PIXABAY_API_KEY}`
- What it's used for: Video and photo search (stock media alternative)
- Video endpoint: `https://pixabay.com/api/videos/`
- Photo endpoint: `https://pixabay.com/api/`
- License: Pixabay Content License (explicitly permits caching/serving from own infrastructure)
- File: `packages/pipeline_core/stock.py` (class `PixabayProvider`)
- Provider class: Can be disabled if API key not configured
- Note: Pixabay secondary; Pexels primary per roadmap

## Prompt Enhancement

**Ollama Server (LLM-based enhancement):**
- Service: Ollama local/remote server (self-hosted)
- Endpoint: `OLLAMA_URL` (e.g., `http://127.0.0.1:11434`)
- Configuration: `OLLAMA_URL`, `OLLAMA_MODEL` (default: `qwen3:4b`)
- API: POST `/api/chat` (streaming and non-streaming)
- Purpose: AI-powered prompt expansion for better Wan results
- Implementation: `packages/pipeline_core/enhance.py::OllamaEnhancer`
- Fallback: Heuristic enhancer if Ollama unavailable (no breakage)
- File: `packages/pipeline_core/enhance.py`
- Takes precedence over `QWEN_MODEL_PATH` when set

**Qwen3.5-4B (CPU-based LLM):**
- Model: Qwen3.5-4B GGUF quantization (Apache 2.0 license)
- Framework: llama-cpp-python (optional `[enhance]` extra)
- Configuration: `QWEN_MODEL_PATH` - path to .gguf file
- Purpose: CPU-only prompt enhancement (no GPU required)
- Implementation: `packages/pipeline_core/enhance.py` (lazy load)
- Fallback: Heuristic enhancer if path not configured or model unavailable
- Note: Ollama `OLLAMA_URL` takes precedence if both configured

**Heuristic Enhancer (fallback):**
- Always available; deterministic, no API calls
- Adds camera language + motion frame + quality vocabulary to prompts
- Implementation: `packages/pipeline_core/enhance.py::HeuristicEnhancer`

## Monitoring & Observability

**Error Tracking:** Not detected (no Sentry/error tracking service configured)

**Logs:**
- Framework: structlog 24.1+
- Output: Structured JSON to stdout (configured in api/worker modules)
- Rotation/storage: External log aggregation expected in production

**Metrics:**
- Not detected (no built-in analytics service)
- Dashboard probe: `/metrics` endpoint not detected

## CI/CD & Deployment

**Hosting:**
- Not specified (self-hosted assumed; workstation or rented GPU box)
- Supports Tailscale/WireGuard for remote GPU worker networking

**CI Pipeline:**
- Not detected (no GitHub Actions or CI service integration found)

**Development Workflow:**
- Local setup: `scripts/setup.sh` (configures .env, picks free ports for docker-compose)
- Testing: pytest (Python), vitest (JavaScript)
- API dev server: `uvicorn api.main:app --reload`
- Frontend dev server: `npm run dev` (Vite dev server)

## Environment Configuration

**Required env vars (core infrastructure):**
- `DATABASE_URL` - PostgreSQL connection
- `REDIS_URL` - Redis connection
- `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` - Object storage

**Optional env vars (external providers - no key = provider unavailable):**
- `FAL_API_KEY` - fal.ai
- `ELEVENLABS_API_KEY` - ElevenLabs TTS/SFX/music
- `OPENAI_API_KEY` - Sora text-to-video
- `GEMINI_API_KEY` - Google Veo text-to-video
- `PEXELS_API_KEY` - Pexels stock media
- `PIXABAY_API_KEY` - Pixabay stock media

**Optional env vars (YouTube publishing):**
- `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`

**Optional env vars (prompt enhancement):**
- `OLLAMA_URL` - Ollama server endpoint
- `OLLAMA_MODEL` - Ollama model name (default: `qwen3:4b`)
- `QWEN_MODEL_PATH` - Path to Qwen3.5-4B GGUF file

**Optional env vars (local generation):**
- `COMFY_URL` - ComfyUI headless server
- `COMFY_POLL_INTERVAL_S` - Poll frequency (default: 2.0)
- `COMFY_TIMEOUT_S` - Job timeout (default: 3600)

**Optional env vars (GPU rental providers - for scripts/rent_gpu.sh):**
- `VAST_API_KEY` - Vast.ai
- `RUNPOD_API_KEY` - RunPod
- `LAMBDA_API_KEY` - Lambda Labs
- `TENSORDOCK_API_KEY`, `TENSORDOCK_API_TOKEN` - TensorDock (both required)

**Secrets location:**
- `.env` file (git-ignored, never committed)
- Environment variables at deployment time (production)
- OAuth flows: refresh token stored in `YOUTUBE_REFRESH_TOKEN` env var

## Webhooks & Callbacks

**Incoming:** None detected (no webhook endpoints)

**Outgoing:**
- YouTube Upload: Publishes private video to user's channel (authenticated via OAuth refresh token)
- No outgoing webhooks to external services detected

## MCP (Model Context Protocol)

**MCP Server:**
- Optional extra: `[mcp]` (requires `mcp>=1.2`)
- Package: `studio_mcp` (agent-facing control surface)
- Purpose: Drive the video studio from any MCP-capable LLM
- File: `studio_mcp/` module (when installed with `[mcp]` extra)
- Configuration: Not separately configured; enabled via dependency

---

*Integration audit: 2026-08-02*
