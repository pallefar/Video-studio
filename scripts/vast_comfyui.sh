#!/usr/bin/env bash
# Bootstrap a rented GPU box (vast.ai or any Ubuntu + CUDA host) as the
# studio's wan-lane executor: ComfyUI + node packs + the model roster for
# the shipped, schema-verified template (wan2.1-t2v-1.3b).
#
# Run ON the instance (root or sudo-capable user):
#
#   curl -fsSLO https://raw.githubusercontent.com/pallefar/Video-studio/claude/app-improvement-tsomi4/scripts/vast_comfyui.sh
#   bash vast_comfyui.sh
#
# Then, from the machine running the studio, open the tunnel (NEVER map
# port 8188 publicly — ComfyUI has no auth; the tunnel is the auth):
#
#   ssh -p <ssh-port> root@<instance-host> -N -L 8188:localhost:8188
#
# The studio's .env keeps COMFY_URL=http://127.0.0.1:8188 unchanged, and
# generations execute on the rented card. The wan2.2 14B templates still
# need their workstation schema-verification pass (docs/workstation.md)
# before their weights are worth downloading — this script sticks to the
# roster that is proven end to end.
set -euo pipefail

REPO_URL="https://github.com/pallefar/Video-studio.git"
BRANCH="${STUDIO_BRANCH:-claude/app-improvement-tsomi4}"
DIR="${STUDIO_DIR:-$HOME/Video-studio}"

echo "==> GPU sanity"
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "!! nvidia-smi not found — this script is for the CUDA instance, not the Mac" >&2
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo "==> system packages"
if command -v apt-get >/dev/null 2>&1; then
  SUDO=""
  [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq git python3-venv python3-pip ffmpeg curl
fi

echo "==> studio repo (single source of truth for node packs + templates)"
if [ ! -d "$DIR/.git" ]; then
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$DIR"
fi

echo "==> ComfyUI + node packs"
"$DIR/scripts/install_comfyui.sh"
COMFY="$(cd "$DIR/../ComfyUI" && pwd)"

echo "==> model roster for wan2.1-t2v-1.3b (Apache-2.0 throughout)"
fetch() { # fetch <url> <target> — resumable, skipped when complete
  mkdir -p "$(dirname "$2")"
  curl -fL -C - --progress-bar -o "$2" "$1"
}
HF="https://huggingface.co"
fetch "$HF/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors" \
      "$COMFY/models/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors"
fetch "$HF/city96/umt5-xxl-encoder-gguf/resolve/main/umt5-xxl-encoder-Q5_K_M.gguf" \
      "$COMFY/models/text_encoders/umt5-xxl-encoder-Q5_K_M.gguf"
fetch "$HF/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" \
      "$COMFY/models/vae/wan_2.1_vae.safetensors"

echo "==> starting ComfyUI on 127.0.0.1:8188 (tunnel-only by design)"
if ! curl -sf http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
  nohup "$COMFY/.venv/bin/python" "$COMFY/main.py" \
    --listen 127.0.0.1 --port 8188 --disable-auto-launch \
    > "$HOME/comfyui.log" 2>&1 &
  for _ in $(seq 1 60); do
    curl -sf http://127.0.0.1:8188/system_stats >/dev/null 2>&1 && break
    sleep 2
  done
fi
curl -sf http://127.0.0.1:8188/system_stats >/dev/null 2>&1 \
  || { echo "!! ComfyUI did not come up — see ~/comfyui.log" >&2; exit 1; }

cat <<EOF

ComfyUI is up on this instance (log: ~/comfyui.log).

From the machine running the studio:
  1. ssh -p <ssh-port> root@<instance-host> -N -L 8188:localhost:8188
  2. keep COMFY_URL=http://127.0.0.1:8188 in the studio's .env
  3. restart the API + wan worker — Settings shows ComfyUI online

Generations (Create tab, camera presets, image studio) now run on:
  $(nvidia-smi --query-gpu=name --format=csv,noheader)
EOF
