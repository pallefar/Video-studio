#!/usr/bin/env bash
# Install the render lane's two GPU-resident engines on the workstation —
# Chatterbox (TTS) and MuseTalk (lip-sync) — in the exact order that decides
# which torch survives (docs/workstation.md;
# .planning/phases/01-render-engines-live/01-RESEARCH.md "Pitfall 1"):
# Chatterbox's newer torch floor goes in FIRST, then the mmlab stack MuseTalk
# needs is resolved UNPINNED via openmim against whatever torch that left
# installed. Copying MuseTalk's own README pins (mmcv==2.0.1 / torch==2.0.1)
# verbatim forces a torch downgrade that breaks Chatterbox in the same
# process — both models load in ONE python process (worker_gpu, concurrency 1).
#
#   bash scripts/install_engines.sh              # real install, GPU host only
#   bash scripts/install_engines.sh --dry-run     # echoes the commands, exits 0 anywhere
#
# Env overrides:
#   CHATTERBOX_VERSION   default 0.1.7   (confirmed live on PyPI, RESEARCH.md)
#   MUSETALK_COMMIT      default main    (pin to a 40-char SHA after Task 4/5
#                                         standardizes the resolution)
set -euo pipefail

STUDIO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
  esac
done

CHATTERBOX_VERSION="${CHATTERBOX_VERSION:-0.1.7}"
MUSETALK_COMMIT="${MUSETALK_COMMIT:-main}"
MUSETALK_DIR="${STUDIO_DIR}/third_party/MuseTalk"
WEIGHTS_DIR="${STUDIO_DIR}/weights/musetalk"

# In --dry-run mode every side-effecting command is echoed, never executed,
# so this script stays exercisable (and CI-testable) from a non-CUDA Mac.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ $*"
  else
    "$@"
  fi
}

if ! command -v nvidia-smi >/dev/null 2>&1 && [ "$DRY_RUN" -eq 0 ]; then
  echo "scripts/install_engines.sh is a GPU-host script — nvidia-smi not found." >&2
  echo "Run with --dry-run to exercise it on a non-CUDA machine (authoring/CI)." >&2
  exit 1
fi

echo "==> [1/7] installing the project's [gpu] extra (establishes the torch floor)"
run pip install -e "${STUDIO_DIR}[gpu]"

echo "==> [2/7] installing chatterbox-tts==${CHATTERBOX_VERSION} (allowed to move torch)"
run pip install "chatterbox-tts==${CHATTERBOX_VERSION}"

echo "==> [3/7] pinning MuseTalk (TMElyralab/MuseTalk) at ${MUSETALK_COMMIT}"
# MuseTalk is not on PyPI — it is a vendored research repo (RESEARCH.md
# Pitfall 5). Skip the clone if it already exists, but always fetch+checkout
# so the pin is authoritative rather than whatever was cloned previously.
if [ ! -d "$MUSETALK_DIR" ]; then
  run git clone https://github.com/TMElyralab/MuseTalk.git "$MUSETALK_DIR"
fi
run git -C "$MUSETALK_DIR" fetch
run git -C "$MUSETALK_DIR" checkout "$MUSETALK_COMMIT"

echo "==> [4/7] installing the mmlab stack via openmim, UNPINNED"
# openmim must resolve mmengine/mmcv/mmdet/mmpose against whatever torch step 2
# actually left installed. Copying MuseTalk README's own pins (mmcv==2.0.1)
# forces a torch downgrade that breaks Chatterbox's torch>=2.6.0 floor — see
# RESEARCH.md Pitfall 1. Do NOT add version specifiers to the mim line below.
run pip install -U openmim
MMCV_START=$(date +%s)
run mim install mmengine mmcv mmdet mmpose
MMCV_END=$(date +%s)

echo "==> [5/7] downloading MuseTalk weights (v1.5 preferred) into ${WEIGHTS_DIR}"
# weights/ is already gitignored — never committed.
run mkdir -p "$WEIGHTS_DIR"
DOWNLOAD_SCRIPT=""
for candidate in \
  "$MUSETALK_DIR/download_weights.sh" \
  "$MUSETALK_DIR/scripts/download_weights.sh"; do
  if [ -f "$candidate" ]; then
    DOWNLOAD_SCRIPT="$candidate"
    break
  fi
done
if [ -z "$DOWNLOAD_SCRIPT" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ (dry-run) MuseTalk not cloned yet — weight download entrypoint cannot be resolved from a Mac"
  else
    echo "MuseTalk's weight download entrypoint was not found at any of:" >&2
    echo "  $MUSETALK_DIR/download_weights.sh" >&2
    echo "  $MUSETALK_DIR/scripts/download_weights.sh" >&2
    exit 1
  fi
else
  run bash "$DOWNLOAD_SCRIPT"
fi

echo "==> [6/7] RESOLVED VERSIONS"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "+ (dry-run) pip show torch torchaudio chatterbox-tts mmengine mmcv mmdet mmpose"
  echo "+ (dry-run) git -C $MUSETALK_DIR rev-parse HEAD"
else
  for pkg in torch torchaudio chatterbox-tts mmengine mmcv mmdet mmpose; do
    pip show "$pkg" 2>/dev/null | grep -E "^(Name|Version): " \
      || printf 'Name: %s\nVersion: NOT INSTALLED\n' "$pkg"
  done
  echo "MuseTalk commit: $(git -C "$MUSETALK_DIR" rev-parse HEAD)"
  ELAPSED=$((MMCV_END - MMCV_START))
  if [ "$ELAPSED" -gt 60 ]; then
    echo "mim install took ${ELAPSED}s — likely built mmcv from source (a wheel install is usually well under 60s)"
  else
    echo "mim install took ${ELAPSED}s — likely a pre-built mmcv wheel"
  fi
fi

echo "==> [7/7] verifying GPU capability"
run python "${STUDIO_DIR}/scripts/verify_gpu.py"
