# Video Studio

Self-hosted AI video studio (Higgsfield-class, single user): avatar renders,
preset video generation, image studio, multi-track editor, and a model
aggregator over local GPUs and API providers. Python API + workers, React
panel. Full architecture: `CLAUDE.md`, `docs/pipeline-spec.md`,
`docs/roadmap-v2.md`.

## Install from a release (easiest)

Grab `video-studio-<version>-macos.zip` or `-windows.zip` from the
[releases page](https://github.com/pallefar/Video-studio/releases), unzip,
and follow the GETTING-STARTED.txt inside. Release bundles ship the control
panel prebuilt, so the only prerequisites are Docker Desktop and
Python 3.11 — no Node. A release is cut after each big milestone
(`docs/ops.md` §Releases).

## Quick start (from a checkout)

The setup script checks every dependency (git, Python 3.11+, Node 20+,
Docker), installs what's missing, prepares the database/bucket, and can
launch the studio:

```bash
# macOS / Linux
./scripts/setup.sh --start

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Start
```

Already set up? Start the stack any time:

```bash
./scripts/dev_up.sh                          # macOS / Linux
powershell -File scripts\start.ps1           # Windows
```

Then open http://localhost:5173. Machines without an NVIDIA GPU run with
`DEV_ENGINES=1` placeholder engines — the full pipeline works end to end
with watchable placeholder output. Real rendering needs the RTX 3090 host:
`docs/workstation.md`.

## Production mode (no dev server)

```bash
(cd web && npm run build)
./.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The API serves the built panel itself at http://127.0.0.1:8000 — one
process, no Node runtime. Service units for boot-time bring-up are in
`deploy/` (`docs/ops.md`).

## The important docs

| Doc | What's in it |
|---|---|
| `CLAUDE.md` | architecture, hard constraints, licence rules |
| `docs/milestones.md` | what's built, with acceptance criteria |
| `docs/workstation.md` | GPU host: ComfyUI, model weights, COMFY_URL |
| `docs/ops.md` | backup/restore, service units, security posture |
| `docs/mac-dev.md` | Apple Silicon dev mode |
| `docs/mcp.md` | drive the studio from any LLM (`python -m studio_mcp`) |

## Tests

```bash
./.venv/bin/python -m pytest tests    # full suite
(cd web && npm run build)             # panel typecheck + bundle
```
