"""ComfyUI headless executor (M10 decision: ComfyUI over diffusers).

The wan-lane executor is a headless ComfyUI sidecar service, configured by
env exactly like MinIO: COMFY_URL from Settings, unconfigured -> a clear
config hint. The worker submits an "API format" node graph (POST /prompt),
polls /history/{prompt_id}, and downloads outputs via /view — the same
submit->poll->fetch shape as the fal provider.

Workflow templates ship as package data (pipeline_core/workflows/*.json),
one per local model, in a sidecar path-map format:

    {"output": {"node": "<id>", "kind": "video|image|audio"},
     "defaults": {...},
     "inputs": {"<param>": ["<node id>", "inputs", "<field>"], ...},
     "required": ["prompt", ...],
     "graph": { ...ComfyUI API-format export... }}

`inject` deep-copies the graph and patches supplied values at their paths;
params without a mapping are ignored (t2v has no source_image). Exporting a
new template: ComfyUI "Save (API Format)" -> wrap with output/inputs ->
`pytest tests/test_comfy.py` validates every path structurally.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from importlib import resources
from typing import Optional

import httpx

from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Generation, GenerationKind

# Wan generates in 4n+1 frame counts — a hard model rule.
WAN_FRAME_STEP = 4

_OUTPUT_CONTENT_TYPES = {
    "video": "video/mp4",
    "image": "image/png",
    "audio": "audio/wav",
}


class ComfyUINotConfiguredError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "local generation is not configured: set COMFY_URL to a headless "
            "ComfyUI (docs/workstation.md) or DEV_ENGINES=1 for placeholder output"
        )


class ComfyUIError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------


def load_template(model: str) -> dict:
    name = f"{model}.json"
    package = resources.files("pipeline_core") / "workflows" / name
    if not package.is_file():
        raise ComfyUIError(
            f"no workflow template for local/{model} — add "
            f"packages/pipeline_core/workflows/{name} (docs/workstation.md)"
        )
    return json.loads(package.read_text())


def inject(template: dict, values: dict) -> dict:
    """Patch supplied values into a deep copy of the template's graph.

    Unmapped values are ignored; required inputs missing from `values`
    (after defaults) raise."""
    merged = {**template.get("defaults", {}), **{k: v for k, v in values.items() if v is not None}}
    for required in template.get("required", []):
        if merged.get(required) in (None, "", []):
            raise ComfyUIError(f"workflow requires input {required!r}")

    graph = copy.deepcopy(template["graph"])
    for param, path in template.get("inputs", {}).items():
        if param not in merged:
            continue
        node = graph
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = merged[param]
    return graph


def wan_frames(duration_s: float, fps: int) -> int:
    """Nearest 4n+1 frame count for a target duration."""
    frames = max(1, round(duration_s * fps))
    return max(5, ((frames - 1 + WAN_FRAME_STEP // 2) // WAN_FRAME_STEP) * WAN_FRAME_STEP + 1)


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


class ComfyUIClient:
    def __init__(
        self,
        base_url: str,
        client: Optional[httpx.Client] = None,
        poll_interval_s: float = 2.0,
        timeout_s: int = 3600,
    ):
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120)
        self._poll_interval_s = poll_interval_s
        self._timeout_s = timeout_s

    def submit(self, graph: dict) -> str:
        response = self._client.post(
            f"{self._base}/prompt", json={"prompt": graph, "client_id": str(uuid.uuid4())}
        )
        response.raise_for_status()
        body = response.json()
        if body.get("node_errors"):
            raise ComfyUIError(f"ComfyUI rejected the graph: {body['node_errors']}")
        return body["prompt_id"]

    def wait(self, prompt_id: str) -> dict:
        """Poll history until the prompt completes. The deadline bounds how
        long the wan lane's exclusive GPU lock is held."""
        deadline = time.monotonic() + self._timeout_s
        while True:
            response = self._client.get(f"{self._base}/history/{prompt_id}")
            response.raise_for_status()
            entry = response.json().get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    messages = [
                        m for m in status.get("messages", [])
                        if m and m[0] == "execution_error"
                    ]
                    raise ComfyUIError(f"ComfyUI execution failed: {messages or status}")
                if entry.get("outputs"):
                    return entry
                if status.get("completed"):
                    raise ComfyUIError(f"ComfyUI produced no outputs for {prompt_id}")
            if time.monotonic() > deadline:
                raise ComfyUIError(
                    f"ComfyUI prompt {prompt_id} exceeded {self._timeout_s}s "
                    "(COMFY_TIMEOUT_S) — the GPU lock must not be held open-ended"
                )
            time.sleep(self._poll_interval_s)

    def download(self, filename: str, subfolder: str = "", type_: str = "output") -> bytes:
        response = self._client.get(
            f"{self._base}/view",
            params={"filename": filename, "subfolder": subfolder, "type": type_},
        )
        response.raise_for_status()
        return response.content

    def upload(self, data: bytes, name: str) -> str:
        """Put a source file into ComfyUI's input dir (accepts video too)."""
        response = self._client.post(
            f"{self._base}/upload/image",
            files={"image": (name, data)},
            data={"overwrite": "true"},
        )
        response.raise_for_status()
        return response.json()["name"]

    def collect_output(self, entry: dict, output_node: str) -> bytes:
        outputs = entry.get("outputs", {}).get(output_node)
        if not outputs:
            raise ComfyUIError(f"no outputs on node {output_node}")
        for key in ("videos", "gifs", "images", "audio"):
            files = outputs.get(key)
            if files:
                file = files[0]
                return self.download(
                    file["filename"], file.get("subfolder", ""), file.get("type", "output")
                )
        raise ComfyUIError(f"unrecognised output shape on node {output_node}: {list(outputs)}")


# ---------------------------------------------------------------------------
# generation -> workflow values
# ---------------------------------------------------------------------------


def build_values(generation: Generation, template: dict, client: ComfyUIClient,
                 store: ObjectStore) -> dict:
    params = generation.params or {}
    defaults = template.get("defaults", {})

    width = params.get("width")
    height = params.get("height")
    if not (width and height):
        width = defaults.get("width")
        height = defaults.get("height")
        if params.get("aspect") == "9:16" and width and height and width > height:
            width, height = height, width

    values: dict = {
        "prompt": generation.prompt,
        # seed derived from the generation id when unset: retries reproduce
        "seed": params.get("seed", generation.id.int % (2**31)),
        "width": width,
        "height": height,
    }

    if params.get("duration_s"):
        if generation.kind == GenerationKind.music:
            values["length"] = int(float(params["duration_s"]))  # seconds for audio
        else:
            fps = defaults.get("fps", 16)
            values["length"] = wan_frames(float(params["duration_s"]), fps)

    motion = params.get("camera_motion") or params.get("motion_codes")
    if motion:
        values["camera_motion"] = ", ".join(motion)

    if params.get("identity_lora_uri"):
        values["lora_name"] = params["identity_lora_uri"].rsplit("/", 1)[-1]

    if params.get("source_asset_uri"):
        _, key = store.parse_uri(params["source_asset_uri"])
        data = store.get_bytes(key)
        name = f"{generation.id}-{key.rsplit('/', 1)[-1]}"
        uploaded = client.upload(data, name)
        target = "source_video" if generation.kind in (
            GenerationKind.video_to_video, GenerationKind.upscale
        ) else "source_image"
        values[target] = uploaded
    if params.get("audio_asset_uri"):
        _, key = store.parse_uri(params["audio_asset_uri"])
        data = store.get_bytes(key)
        values["source_audio"] = client.upload(data, f"{generation.id}-audio-{key.rsplit('/', 1)[-1]}")
    if params.get("script"):
        values["script"] = params["script"]

    if not params.get("source_asset_uri") and params.get("image_uri"):
        _, key = store.parse_uri(params["image_uri"])
        values["source_image"] = client.upload(
            store.get_bytes(key), f"{generation.id}-{key.rsplit('/', 1)[-1]}"
        )

    return values


def run_comfy_generation(
    generation: Generation,
    settings: Optional[Settings] = None,
    client: Optional[ComfyUIClient] = None,
    store: Optional[ObjectStore] = None,
) -> tuple[bytes, str, str]:
    """Execute one generation on the configured ComfyUI: returns
    (bytes, content_type, prompt_id)."""
    settings = settings or Settings()
    if client is None:
        if not settings.comfy_url:
            raise ComfyUINotConfiguredError()
        client = ComfyUIClient(
            settings.comfy_url,
            poll_interval_s=settings.comfy_poll_interval_s,
            timeout_s=settings.comfy_timeout_s,
        )
    store = store or ObjectStore()

    template = load_template(generation.model)
    values = build_values(generation, template, client, store)
    graph = inject(template, values)
    prompt_id = client.submit(graph)
    entry = client.wait(prompt_id)
    data = client.collect_output(entry, template["output"]["node"])
    content_type = _OUTPUT_CONTENT_TYPES.get(template["output"]["kind"], "video/mp4")
    return data, content_type, prompt_id
