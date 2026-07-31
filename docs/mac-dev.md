# Running the studio on an Apple Silicon Mac (M-series)

The production GPU host is an RTX 3090 (sm_86) — the real Chatterbox,
MuseTalk, and Wan models only run there. Everything else in the system is
plain Python + ffmpeg + Postgres/Redis/MinIO and runs natively on macOS
arm64. **Dev-engines mode** fills the model gap with placeholders so the
entire pipeline is testable on a MacBook: same stages, same queues, same
compliance gates, same artefact layout — placeholder model output.

## Quick start

```bash
brew install python@3.12 node          # once
open -a Docker                          # or OrbStack

./scripts/dev_up.sh
```

Then open http://localhost:5173. Ctrl-C stops everything; `docker compose
down` stops the infrastructure.

## What dev-engines mode does

`DEV_ENGINES=1` (the script's default) swaps the two render-lane engines:

| Real engine | Dev stand-in | Fidelity |
|---|---|---|
| Chatterbox TTS | macOS `say` (real speech; emotion presets map to speaking rate) | Real timing, robotic voice |
| MuseTalk lipsync | Base loop cycled to each chunk window | Static avatar, exact durations |

Everything downstream is the **real implementation**: sentence segmentation
with pinned seeds, chunk windows, the full M4 assembly chain (−14 LUFS
loudnorm, captions from word timings, B-roll cutaways, C1 watermark, CRF 18
encode), review gating, preview, and the private-only publish worker. An
avatar job submitted in the panel goes `queued → tts → lipsync → assemble →
review` unattended and gives you a watchable MP4 in the preview player.

Also fully functional on the Mac: projects, the asset library and stock
ingest, storyboards + the real export renderer with live progress, the
timeline editor, effects/upscale/image/music **request** flows (generations
queue and wait — executing them needs the wan-lane executor on a GPU host or
a configured API provider like fal), identities with the C6 consent gate,
and every compliance rule.

## What still needs the 3090 (or an API key)

- Real voice + lipsync (M3), Wan/VACE/image/music model execution
  (M9/M10-13/M18), identity LoRA training (M17), the latent cache (M2), and
  `scripts/verify_gpu.py` / `bench.py` — the sm_86 checks are for the GPU
  host and are expected to fail on a Mac.
- Alternatively: set `FAL_API_KEY` in `.env` and the `fal` provider appears
  in every engine picker — generations then execute for real via the API
  (network jobs on the CPU lane), no GPU needed.

## Manual startup (what the script does)

```bash
docker compose up -d --wait
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -c "from pipeline_core.storage import ObjectStore; ObjectStore().ensure_bucket()"

DEV_ENGINES=1 ./.venv/bin/python worker_gpu/run.py   &  # render lane, dev engines
./.venv/bin/python worker_cpu/run.py                 &  # ffmpeg lane
./.venv/bin/python -m uvicorn api.main:app --port 8000 &
(cd web && npm ci && npm run dev)
```

Defaults in `pipeline_core/settings.py` match docker-compose (Postgres 5432,
Redis 6379, MinIO 9000), so no `.env` is needed for a stock setup.

## Notes

- Dev engines announce themselves with a warning at boot and are opt-in via
  env — they can never silently become the production path.
- `ffmpeg` is bundled through `imageio-ffmpeg` (arm64 build); a Homebrew
  ffmpeg is used when present on PATH.
- Apple's `say` writes AIFF; the dev engine transcodes to the pipeline's
  48 kHz stereo WAV so loudnorm and the C3 probe behave identically.
- The GPU worker stays a single process with concurrency 1 even in dev mode
  — queue semantics on the Mac match the workstation exactly.
