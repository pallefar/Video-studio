#!/usr/bin/env bash
# Continue this project locally with Claude Code on an Apple Silicon Mac.
#
#   curl -fsSLO https://raw.githubusercontent.com/pallefar/Video-studio/claude/app-improvement-tsomi4/scripts/continue_mac.sh
#   bash continue_mac.sh
#
# (Or just run ./scripts/continue_mac.sh from an existing checkout.)
#
# What it does, idempotently:
#   1. clone/update the repo on the working branch
#   2. bootstrap the studio (./scripts/setup.sh — deps, docker services, DB)
#   3. install + start Ollama and pull the enhancer model; wire OLLAMA_URL
#   4. start the whole studio in Mac dev mode (placeholder GPU engines)
#   5. launch Claude Code with the continuation context
set -euo pipefail

REPO_URL="https://github.com/pallefar/Video-studio.git"
BRANCH="claude/app-improvement-tsomi4"
DIR="${STUDIO_DIR:-$HOME/Video-studio}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:4b}"

echo "==> repo"
if [ ! -d "$DIR/.git" ]; then
  git clone "$REPO_URL" "$DIR"
fi
cd "$DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "==> studio bootstrap (deps, docker services, database, bucket)"
./scripts/setup.sh

echo "==> ollama (prompt enhancement / reverse prompting)"
if ! command -v ollama >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install ollama
  else
    echo "!! install Homebrew (https://brew.sh) or Ollama (https://ollama.com) manually, then re-run"
    exit 1
  fi
fi
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "    starting ollama service"
  (brew services start ollama >/dev/null 2>&1) || (nohup ollama serve >/tmp/ollama.log 2>&1 &)
  sleep 3
fi
ollama pull "$OLLAMA_MODEL"
touch .env
grep -q "^OLLAMA_URL=http" .env || printf '\nOLLAMA_URL=http://127.0.0.1:11434\nOLLAMA_MODEL=%s\n' "$OLLAMA_MODEL" >> .env

echo "==> starting the studio (Mac dev mode — placeholder GPU engines)"
./scripts/dev_up.sh || true

echo "==> claude code"
if ! command -v claude >/dev/null 2>&1; then
  echo "!! Claude Code not found — install it first:"
  echo "     npm install -g @anthropic-ai/claude-code   (or: brew install claude-code)"
  echo "   then re-run this script."
  exit 1
fi

PROMPT=$(cat <<'EOF'
Continue work on this AI video studio on my M4 Mac. Read CLAUDE.md and
docs/milestones.md first — they are the source of truth.

Where things stand: everything through M29 is shipped and merged; release
v0.29.0 is published (macOS/Windows bundles via .github/workflows/release.yml,
one release per milestone — docs/ops.md §Releases). The suite is ~470 pytest
+ 21 vitest, all green. Providers: local ComfyUI, fal.ai, ElevenLabs, Sora,
Veo; Ollama is wired as the prompt-enhancement backend and should show
"online" in the Settings tab of this machine.

This Mac has no CUDA, so the studio runs with DEV_ENGINES=1 placeholder
voice/lipsync/generation — every flow works end to end with watchable
placeholder output. The 15 unchecked milestone boxes are GPU-workstation
tasks (RTX 3090): docs/workstation.md §5 is the ordered runbook — do NOT
attempt them here.

Good next work on this machine: verify the panel end to end in a real
browser (Chrome plays the H.264 proxies natively), M11 advanced-mode wiring
(Uni3C / ReCamMaster params + templates), and anything I ask for. Rules
that always hold: licence register in docs/roadmap-v2.md §6, compliance
C1–C6 are structural, full pytest + npm test + build green before any
commit, releases only after a big milestone.
EOF
)

echo
echo "Studio: http://localhost:5173 (dev) — Settings tab shows what's connected."
echo "Launching Claude Code..."
exec claude "$PROMPT"
