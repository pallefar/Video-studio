"""M10 acceptance: the ComfyUI headless executor, CPU-proven against a fake
ComfyUI (httpx MockTransport) — submit/poll/fetch, source uploads, template
injection, and a structural audit of every shipped workflow template."""

from __future__ import annotations

import json

import httpx
import pytest
from moto import mock_aws

from pipeline_core.comfy import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUINotConfiguredError,
    build_values,
    inject,
    load_template,
    run_comfy_generation,
    wan_frames,
)
from pipeline_core.providers import LOCAL_PROVIDER, build_registry
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import Generation, GenerationKind

COMFY_MODELS = [
    "wan2.2-t2v", "wan2.2-i2v", "wan2.2-fun-camera", "wan2.2-vace-fun",
    "wan2.1-vace-1.3b", "z-image-turbo", "qwen-image", "sdxl", "ace-step",
    "musetalk-image", "chatterbox",
]


class FakeComfy:
    """Minimal ComfyUI over MockTransport: /prompt, /history, /view, /upload."""

    def __init__(self, output_key="videos", pending_polls=1, fail=False):
        self.output_key = output_key
        self.pending_polls = pending_polls
        self.fail = fail
        self.graphs: list[dict] = []
        self.uploads: dict[str, bytes] = {}
        self._polls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/prompt":
            self.graphs.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": "p-1", "node_errors": {}})
        if path.startswith("/history/"):
            self._polls += 1
            if self._polls <= self.pending_polls:
                return httpx.Response(200, json={})
            if self.fail:
                return httpx.Response(200, json={"p-1": {
                    "status": {"status_str": "error",
                               "messages": [["execution_error", {"node": "3", "exception_message": "OOM"}]]},
                }})
            return httpx.Response(200, json={"p-1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"60": {self.output_key: [
                    {"filename": "studio_00001.mp4", "subfolder": "", "type": "output"}
                ]}},
            }})
        if path == "/view":
            return httpx.Response(200, content=b"comfy-output-bytes")
        if path == "/object_info":
            return httpx.Response(200, json={"KSampler": {}, "CLIPTextEncode": {}})
        if path == "/upload/image":
            # crude multipart name extraction is enough for the fake
            name = request.content.split(b'filename="')[1].split(b'"')[0].decode()
            self.uploads[name] = request.content
            return httpx.Response(200, json={"name": name})
        return httpx.Response(404)


def _client(fake: FakeComfy, **kwargs) -> ComfyUIClient:
    transport = httpx.MockTransport(fake.handler)
    return ComfyUIClient("http://comfy.test", client=httpx.Client(transport=transport),
                         poll_interval_s=0, **kwargs)


def _generation(model="wan2.2-t2v", kind=GenerationKind.text_to_video, **params) -> Generation:
    return Generation(provider="local", model=model, kind=kind,
                      prompt="a fox in the snow", params=params)


# --- client -----------------------------------------------------------------


def test_submit_poll_fetch_round_trip():
    fake = FakeComfy()
    client = _client(fake)
    prompt_id = client.submit({"1": {}})
    entry = client.wait(prompt_id)
    data = client.collect_output(entry, "60")
    assert data == b"comfy-output-bytes"
    assert fake.graphs == [{"1": {}}]


def test_execution_error_raises_with_node_detail():
    client = _client(FakeComfy(fail=True))
    client.submit({})
    with pytest.raises(ComfyUIError, match="OOM"):
        client.wait("p-1")


def test_timeout_bounds_the_gpu_lock():
    client = _client(FakeComfy(pending_polls=10_000), timeout_s=0)
    client.submit({})
    with pytest.raises(ComfyUIError, match="COMFY_TIMEOUT_S"):
        client.wait("p-1")


def test_output_key_variants():
    for key in ("videos", "gifs", "images", "audio"):
        fake = FakeComfy(output_key=key)
        client = _client(fake)
        client.submit({})
        assert client.collect_output(client.wait("p-1"), "60") == b"comfy-output-bytes"


# --- templates ---------------------------------------------------------------


def test_every_model_has_a_structurally_valid_template():
    for model in COMFY_MODELS:
        template = load_template(model)
        graph = template["graph"]
        assert template["output"]["node"] in graph, model
        assert template["output"]["kind"] in ("video", "image", "audio"), model
        for param, path in template["inputs"].items():
            node = graph
            for step in path[:-1]:
                assert step in node, f"{model}: {param} path breaks at {step}"
                node = node[step]
            assert path[-1] in node, f"{model}: {param} final field missing"


def test_missing_template_raises_clear_error():
    with pytest.raises(ComfyUIError, match="real-esrgan"):
        load_template("real-esrgan")


def test_inject_patches_and_ignores_unmapped():
    template = load_template("wan2.2-t2v")
    graph = inject(template, {"prompt": "hello", "seed": 42, "source_image": "ignored.png"})
    assert graph["6"]["inputs"]["text"] == "hello"
    assert graph["3"]["inputs"]["seed"] == 42
    # defaults applied
    assert graph["7"]["inputs"]["text"] == template["defaults"]["negative"]


def test_inject_requires_required_inputs():
    template = load_template("wan2.2-i2v")
    with pytest.raises(ComfyUIError, match="source_image"):
        inject(template, {"prompt": "hello"})


def test_wan_frames_4n_plus_1():
    assert wan_frames(2.0, 16) == 33
    assert wan_frames(0.1, 16) == 5
    for seconds in (1.0, 2.5, 5.0):
        assert (wan_frames(seconds, 16) - 1) % 4 == 0


# --- generation values -------------------------------------------------------


def test_build_values_camera_motion_and_frames(store_env=None):
    fake = FakeComfy()
    client = _client(fake)
    template = load_template("wan2.2-fun-camera")
    generation = _generation(model="wan2.2-fun-camera",
                             camera_motion=["Zoom In", "Pan Left"], duration_s=2, seed=9)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="comfy-test"))
        values = build_values(generation, template, client, store)
    assert values["camera_motion"] == "Zoom In, Pan Left"
    assert values["length"] == 33
    assert values["seed"] == 9


def test_build_values_uploads_source_asset():
    fake = FakeComfy()
    client = _client(fake)
    template = load_template("wan2.2-vace-fun")
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="comfy-test"))
        store.ensure_bucket()
        uri = store.put_bytes("clips/source.mp4", b"src-bytes")
        generation = _generation(model="wan2.2-vace-fun", kind=GenerationKind.video_to_video,
                                 source_asset_uri=uri, effects=["glitch"])
        values = build_values(generation, template, client, store)
    assert values["source_video"] in fake.uploads
    assert str(generation.id) in values["source_video"]


def test_music_length_is_seconds_not_frames():
    fake = FakeComfy(output_key="audio")
    client = _client(fake)
    template = load_template("ace-step")
    generation = _generation(model="ace-step", kind=GenerationKind.music, duration_s=45)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="comfy-test"))
        values = build_values(generation, template, client, store)
    assert values["length"] == 45


# --- end to end --------------------------------------------------------------


def test_run_comfy_generation_end_to_end():
    fake = FakeComfy()
    client = _client(fake)
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="comfy-test"))
        store.ensure_bucket()
        data, content_type, prompt_id = run_comfy_generation(
            _generation(duration_s=1), client=client, store=store
        )
    assert data == b"comfy-output-bytes"
    assert content_type == "video/mp4"
    assert prompt_id == "p-1"
    # the submitted graph carried the injected prompt
    submitted = fake.graphs[0]
    assert submitted["6"]["inputs"]["text"] == "a fox in the snow"


def test_unconfigured_raises_config_hint():
    with pytest.raises(ComfyUINotConfiguredError, match="COMFY_URL"):
        run_comfy_generation(_generation(), settings=Settings(comfy_url="", _env_file=None))


def test_unconfigured_local_falls_back_to_declared_api_target(client, engine, dispatcher, monkeypatch):
    """run_generation's existing fallback chain: local unconfigured -> the
    declared fal target is re-dispatched to the cpu lane."""
    import pipeline_core.db as core_db
    from pipeline_core.generation import run_generation
    from pipeline_core.providers import ProviderRegistry
    from tests.test_providers import FakeApiProvider

    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    monkeypatch.delenv("DEV_ENGINES", raising=False)
    monkeypatch.delenv("COMFY_URL", raising=False)

    registry = build_registry(Settings(dev_engines=False, comfy_url="", _env_file=None))
    registry.register(FakeApiProvider())

    from sqlmodel import Session

    with Session(engine) as session:
        generation = Generation(
            provider="local", model="wan2.2-t2v", kind=GenerationKind.text_to_video,
            prompt="fallback me",
            fallback=[{"provider": "fake", "model": "fake-t2v"}],
        )
        session.add(generation)
        session.commit()
        generation_id = str(generation.id)

    class RecordingDispatcher:
        def __init__(self):
            self.calls = []

        def enqueue(self, queue, func, *args, job_key=None):
            self.calls.append((queue, func, args))

    recorder = RecordingDispatcher()
    run_generation(generation_id, registry=registry, dispatcher=recorder)

    (queue, func, args), = recorder.calls
    assert queue == "cpu"  # the fal-class fake is a network job
    assert args == (generation_id,)


# --- node-pack manifest (comfy_nodes.py) -------------------------------------


def test_node_pack_manifest_is_audited():
    """Registry-as-data audit: every pack carries repo/licence/probes, and
    every template it claims to serve actually references one of its nodes."""
    from pipeline_core.comfy_nodes import NODE_PACKS, template_node_types

    templates = template_node_types()
    for pack in NODE_PACKS:
        assert pack.repo.startswith("https://github.com/"), pack.name
        assert pack.license, pack.name
        assert pack.provides, pack.name
        for model in pack.needed_for:
            assert model in templates, f"{pack.name} claims unknown template {model}"
            assert templates[model] & set(pack.provides), (
                f"{pack.name} claims {model} but the template uses none of its nodes"
            )


def test_every_custom_node_type_maps_to_a_pack():
    """Every non-core node class our templates use must be attributable to a
    manifest pack — otherwise the Settings check can't say what to install."""
    from pipeline_core.comfy_nodes import pack_for_type, template_node_types

    core_prefixes = ("VHS_", "MuseTalk", "FL_Chatterbox", "UnetLoaderGGUF")
    for model, types in template_node_types().items():
        for class_type in types:
            if class_type.startswith(core_prefixes) or class_type == "UnetLoaderGGUF":
                assert pack_for_type(class_type) is not None, (
                    f"{model} uses custom node {class_type} with no manifest pack"
                )


def test_missing_node_types_diffs_templates_against_object_info():
    from pipeline_core.comfy_nodes import missing_node_types, template_node_types

    everything = set().union(*template_node_types().values())
    assert missing_node_types(everything) == []

    without_musetalk = everything - {"MuseTalkRun"}
    missing = missing_node_types(without_musetalk)
    assert len(missing) == 1
    assert missing[0]["type"] == "MuseTalkRun"
    assert missing[0]["pack"] == "ComfyUI-MuseTalk"
    assert missing[0]["models"] == ["musetalk-image"]


def test_pack_status_probes_installed_packs():
    from pipeline_core.comfy_nodes import pack_status

    status = {p["name"]: p for p in pack_status({"VHS_VideoCombine", "UnetLoaderGGUF"})}
    assert status["ComfyUI-VideoHelperSuite"]["installed"] is True
    assert status["ComfyUI-GGUF"]["installed"] is True
    assert status["ComfyUI-MuseTalk"]["installed"] is False
    assert status["ComfyUI-WanVideoWrapper"]["optional"] is True


def test_install_script_clones_every_manifest_pack():
    """Drift guard: scripts/install_comfyui.sh must clone the exact repos the
    manifest declares — the two lists can never diverge silently."""
    from pathlib import Path

    from pipeline_core.comfy_nodes import NODE_PACKS

    script = Path(__file__).parent.parent / "scripts" / "install_comfyui.sh"
    text = script.read_text()
    for pack in NODE_PACKS:
        assert pack.repo in text, f"install_comfyui.sh is missing {pack.repo}"
    # and it exports the studio's workflow templates into ComfyUI's UI
    assert "user/default/workflows" in text


def test_client_object_info_returns_node_types():
    client = _client(FakeComfy())
    assert client.object_info() == {"KSampler", "CLIPTextEncode"}


# --- GET /config/comfy -------------------------------------------------------


def test_config_comfy_unconfigured(client, monkeypatch):
    monkeypatch.delenv("COMFY_URL", raising=False)
    body = client.get("/config/comfy").json()
    assert body == {"configured": False, "online": False, "packs": [], "missing": []}


def test_config_comfy_reports_missing_packs(client, monkeypatch):
    from pipeline_core.comfy_nodes import template_node_types

    monkeypatch.setenv("COMFY_URL", "http://comfy-host:8188")
    everything = set().union(*template_node_types().values())

    class FakeInfoClient:
        def __init__(self, *args, **kwargs):
            pass

        def object_info(self):
            return everything - {"FL_ChatterboxTTS"}

    monkeypatch.setattr("pipeline_core.comfy.ComfyUIClient", FakeInfoClient)
    body = client.get("/config/comfy").json()
    assert body["online"] is True
    assert [m["type"] for m in body["missing"]] == ["FL_ChatterboxTTS"]
    assert body["missing"][0]["pack"] == "ComfyUI_Fill-ChatterBox"
    packs = {p["name"]: p["installed"] for p in body["packs"]}
    assert packs["ComfyUI_Fill-ChatterBox"] is False
    assert packs["ComfyUI-VideoHelperSuite"] is True


def test_config_comfy_offline_degrades(client, monkeypatch):
    monkeypatch.setenv("COMFY_URL", "http://127.0.0.1:1")
    body = client.get("/config/comfy").json()
    assert body["configured"] is True
    assert body["online"] is False
