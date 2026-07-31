#!/usr/bin/env bash
# Install ComfyUI (the M10 wan-lane executor) next to the studio and print
# the wiring steps. Works on the GPU workstation (CUDA torch) and on
# CPU-only machines (--cpu flag at runtime; fine for connection testing,
# too slow for real generation).
#
#   ./scripts/install_comfyui.sh [target-dir]     # default: ../ComfyUI
set -euo pipefail

TARGET="${1:-$(dirname "$0")/../../ComfyUI}"

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

CPU_FLAG=""
command -v nvidia-smi >/dev/null 2>&1 || CPU_FLAG=" --cpu"

cat <<EOF

ComfyUI installed at: $TARGET

Run it:
  cd $TARGET && ./.venv/bin/python main.py$CPU_FLAG --listen 127.0.0.1 --port 8188 --disable-auto-launch

Connect the studio:
  echo 'COMFY_URL=http://127.0.0.1:8188' >> .env    # in the studio repo
  # restart the API + wan worker; the Settings tab shows "online" when reachable

Custom nodes + model weights for the real render roster: docs/workstation.md
EOF
