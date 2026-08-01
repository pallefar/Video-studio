#!/usr/bin/env bash
# Which GPU-rental providers are ready on this machine, and what's missing.
#
#   ./scripts/rent_gpu.sh            # provider status + setup steps
#   ./scripts/rent_gpu.sh --offers   # also list live RTX-3090-class prices
#                                    # from every provider that's reachable
#
# All providers end at the same place: an Ubuntu + CUDA box running
# scripts/vast_comfyui.sh (provider-agnostic despite the name), reached
# through an SSH tunnel — COMFY_URL stays http://127.0.0.1:8188 and the
# wan lane generates on the rented card. Keys are read from env only;
# rental credentials are deliberately NOT studio Settings.
set -euo pipefail

OFFERS=0
[ "${1:-}" = "--offers" ] && OFFERS=1

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
miss() { printf '  \033[31m✗\033[0m %s\n' "$1"; }
hint() { printf '      %s\n' "$1"; }

echo "== vast.ai (RTX 3090 ~\$0.10/hr, the cheapest 3090 market)"
VAST_KEY="${VAST_API_KEY:-}"
[ -z "$VAST_KEY" ] && [ -f "$HOME/.config/vastai/vast_api_key" ] && VAST_KEY=file
[ -z "$VAST_KEY" ] && [ -f "$HOME/.vast_api_key" ] && VAST_KEY=file
if command -v vastai >/dev/null 2>&1; then ok "CLI installed (vastai)"; else
  miss "CLI not installed"; hint "pipx install vastai   (or: pip install vastai)"
fi
if [ -n "$VAST_KEY" ]; then ok "API key configured"; else
  miss "API key not set"
  hint "cloud.vast.ai → Account → API Keys, then: vastai set api-key <KEY>"
fi

echo "== RunPod (RTX 3090 ~\$0.22/hr community, secure cloud pricier)"
if command -v runpodctl >/dev/null 2>&1; then ok "CLI installed (runpodctl)"; else
  miss "CLI not installed"; hint "brew install runpod/runpodctl/runpodctl"
fi
if [ -n "${RUNPOD_API_KEY:-}" ] || [ -f "$HOME/.runpod/config.toml" ]; then
  ok "API key configured"
else
  miss "API key not set"
  hint "runpod.io → Settings → API Keys, then: export RUNPOD_API_KEY=<KEY>"
  hint "pick a pod with 'SSH over exposed TCP' so the 8188 tunnel works"
fi

echo "== Lambda Cloud (no 3090s; A10 24 GB is the same sm_86 Ampere, ~\$0.75/hr)"
if [ -n "${LAMBDA_API_KEY:-}" ]; then ok "API key configured"; else
  miss "API key not set"
  hint "cloud.lambdalabs.com → API keys, then: export LAMBDA_API_KEY=<KEY>"
fi

echo "== TensorDock (RTX 3090 ~\$0.20/hr marketplace)"
if [ -n "${TENSORDOCK_API_KEY:-}" ] && [ -n "${TENSORDOCK_API_TOKEN:-}" ]; then
  ok "API key + token configured"
else
  miss "API key/token not set"
  hint "dashboard.tensordock.com → API, then export TENSORDOCK_API_KEY + TENSORDOCK_API_TOKEN"
fi

[ "$OFFERS" = 1 ] || {
  echo
  echo "Run with --offers to pull live prices from whichever providers are reachable."
  echo "Instance-side bootstrap (any provider): scripts/vast_comfyui.sh — then"
  echo "  ssh -p <port> <user>@<host> -N -L 8188:localhost:8188"
  exit 0
}

echo
echo "== live offers (RTX-3090-class, one GPU)"

if command -v vastai >/dev/null 2>&1; then
  echo "-- vast.ai (works without a key):"
  vastai search offers \
    'gpu_name=RTX_3090 num_gpus=1 disk_space>=40 inet_down>=200 reliability>=0.98 rentable=true' \
    -o 'dph' --raw 2>/dev/null | python3 -c "
import json, sys
try:
    offers = json.load(sys.stdin)[:5]
except Exception:
    sys.exit(0)
for o in offers:
    print(f\"   id={o['id']}  \${o['dph_total']:.3f}/hr  disk={o['disk_space']:.0f}GB\"
          f\"  down={o['inet_down']:.0f}Mbps  rel={o['reliability2']:.3f}\")
" || true
else
  echo "-- vast.ai: install the CLI to see offers"
fi

if [ -n "${RUNPOD_API_KEY:-}" ]; then
  echo "-- RunPod:"
  curl -sf "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H 'Content-Type: application/json' \
    -d '{"query":"query { gpuTypes(input: {id: \"NVIDIA GeForce RTX 3090\"}) { displayName memoryInGb securePrice communityPrice } }"}' \
    | python3 -c "
import json, sys
try:
    for g in json.load(sys.stdin)['data']['gpuTypes']:
        print(f\"   {g['displayName']}  {g['memoryInGb']}GB\"
          f\"  community \${g['communityPrice']}/hr  secure \${g['securePrice']}/hr\")
except Exception:
    print('   (query failed — check RUNPOD_API_KEY)')
" || true
else
  echo "-- RunPod: set RUNPOD_API_KEY to see offers"
fi

if [ -n "${LAMBDA_API_KEY:-}" ]; then
  echo "-- Lambda Cloud (A10 24 GB, sm_86 like the 3090):"
  curl -sf -u "${LAMBDA_API_KEY}:" https://cloud.lambdalabs.com/api/v1/instance-types \
    | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)['data']
except Exception:
    print('   (query failed — check LAMBDA_API_KEY)'); sys.exit(0)
for name, entry in data.items():
    it = entry['instance_type']
    if 'a10' in name:
        avail = 'available' if entry['regions_with_capacity_available'] else 'no capacity'
        print(f\"   {name}  \${it['price_cents_per_hour']/100:.2f}/hr  {avail}\")
" || true
else
  echo "-- Lambda Cloud: set LAMBDA_API_KEY to see offers"
fi

echo "-- TensorDock: no offer probe wired — browse dashboard.tensordock.com"
