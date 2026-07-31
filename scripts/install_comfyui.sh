#!/usr/bin/env bash
# Install ComfyUI (the M10 wan-lane executor) next to the studio and print
# the wiring steps. Works on the GPU workstation (CUDA torch) and on
# CPU-only machines (--cpu flag at runtime; fine for connection testing,
# too slow for real generation).
#
#   ./scripts/install_comfyui.sh [target-dir]     # default: ../ComfyUI
set -euo pipefail

STUDIO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-$(dirname "$0")/../../ComfyUI}"

# Custom-node packs the studio's workflow templates need. Single source of
# truth: packages/pipeline_core/comfy_nodes.py — tests/test_comfy.py keeps
# this list in sync with it. GPL packs are fine here: ComfyUI is a sidecar
# service over HTTP, never linked into the studio (comfy_nodes.py docstring).
NODE_PACKS=(
  "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite"
  "https://github.com/city96/ComfyUI-GGUF"
  "https://github.com/chaojie/ComfyUI-MuseTalk"
  "https://github.com/filliptm/ComfyUI_Fill-ChatterBox"
  "https://github.com/kijai/ComfyUI-WanVideoWrapper"
  "https://github.com/kijai/ComfyUI-KJNodes"
)

if [ ! -d "$TARGET" ]; then
  echo "==> cloning ComfyUI -> $TARGET"
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$TARGET"
fi
cd "$TARGET"

if [ ! -d .venv ]; then
  echo "==> creating venv"
  python3 -m venv .venv
fi
./.venv/bin/pip install --quiet --upgrade pip

echo "==> installing torch"
if command -v nvidia-smi >/dev/null 2>&1; then
  ./.venv/bin/pip install --quiet torch torchvision torchaudio
else
  # CPU-only box: same wheels work; generation is impractical but the
  # server runs and the studio can verify its connection end-to-end.
  ./.venv/bin/pip install --quiet torch torchvision torchaudio
fi

echo "==> installing ComfyUI requirements"
./.venv/bin/pip install --quiet -r requirements.txt

echo "==> installing custom-node packs"
mkdir -p custom_nodes
for repo in "${NODE_PACKS[@]}"; do
  dir="custom_nodes/$(basename "$repo")"
  if [ ! -d "$dir" ]; then
    echo "    + $(basename "$repo")"
    git clone --depth 1 "$repo" "$dir"
  fi
  if [ -f "$dir/requirements.txt" ]; then
    ./.venv/bin/pip install --quiet -r "$dir/requirements.txt" \
      || echo "    ! $(basename "$repo") requirements failed — finish by hand (docs/workstation.md)"
  fi
done
# ComfyUI-MuseTalk imports `ffmpeg` (ffmpeg-python) without declaring it.
./.venv/bin/pip install --quiet ffmpeg-python

echo "==> exporting the studio's workflow templates into ComfyUI"
# The studio drives ComfyUI through the API, but having the same graphs
# loadable in ComfyUI's own UI makes tuning them hands-on. Our templates wrap
# an API-format graph under a "graph" key — unwrap each into the user
# workflow dir (the modern ComfyUI frontend imports API-format JSON).
WORKFLOW_DIR="$TARGET/user/default/workflows"
mkdir -p "$WORKFLOW_DIR"
python3 - "$STUDIO_DIR" "$WORKFLOW_DIR" <<'PY'
import json, pathlib, sys
studio, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
for template in sorted((studio / "packages/pipeline_core/workflows").glob("*.json")):
    graph = json.loads(template.read_text())["graph"]
    target = out / f"studio-{template.stem}.json"
    target.write_text(json.dumps(graph, indent=2))
    print(f"    + {target.name}")
PY

CPU_FLAG=""
command -v nvidia-smi >/dev/null 2>&1 || CPU_FLAG=" --cpu"

cat <<EOF

ComfyUI installed at: $TARGET

Run it:
  cd $TARGET && ./.venv/bin/python main.py$CPU_FLAG --listen 127.0.0.1 --port 8188 --disable-auto-launch

Connect the studio:
  echo 'COMFY_URL=http://127.0.0.1:8188' >> .env    # in the studio repo
  # restart the API + wan worker; the Settings tab shows "online" when
  # reachable and flags any node pack a workflow template still misses

Model weights for the real render roster: docs/workstation.md
EOF
