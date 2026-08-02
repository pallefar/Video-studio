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
    "wan2.1-vace-1.3b", "wan2.1-t2v-1.3b", "wan2.2-ti2v-5b", "z-image-turbo",
    "qwen-image", "sdxl", "ace-step", "musetalk-image", "chatterbox", "uni3c",
    "recammaster",
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
    from pipeline_core.comfy import input_mapping_paths

    for model in COMFY_MODELS:
        template = load_template(model)
        graph = template["graph"]
        assert template["output"]["node"] in graph, model
        assert template["output"]["kind"] in ("video", "image", "audio"), model
        for param, mapping in template["inputs"].items():
            for path in input_mapping_paths(mapping):
                node = graph
                for step in path[:-1]:
                    assert step in node, f"{model}: {param} path breaks at {step}"
                    node = node[step]
                assert path[-1] in node, f"{model}: {param} final field missing"


def test_structural_audit_validates_both_single_and_multi_path_mappings():
    """A template using either mapping shape is validated by the same
    audit — proven against small fixture templates of each shape, not
    just by the shipped templates (which today are all single-path)."""
    from pipeline_core.comfy import input_mapping_paths

    single_path_template = {
        "output": {"node": "1", "kind": "video"},
        "inputs": {"width": ["1", "inputs", "width"]},
        "graph": {"1": {"class_type": "Stub", "inputs": {"width": 0}}},
    }
    multi_path_template = {
        "output": {"node": "1", "kind": "video"},
        "inputs": {"length": [["1", "inputs", "length"], ["2", "inputs", "num_frames"]]},
        "graph": {
            "1": {"class_type": "Stub", "inputs": {"length": 0}},
            "2": {"class_type": "Other", "inputs": {"num_frames": 0}},
        },
    }
    for template in (single_path_template, multi_path_template):
        graph = template["graph"]
        for param, mapping in template["inputs"].items():
            for path in input_mapping_paths(mapping):
                node = graph
                for step in path[:-1]:
                    assert step in node, f"{param} path breaks at {step}"
                    node = node[step]
                assert path[-1] in node, f"{param} final field missing"


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


# --- multi-path input mapping (inject()) --------------------------------


def test_inject_backward_compatible_with_single_path_mappings():
    """Every existing single-path template must inject exactly as before —
    the single-path walk-and-assign is the same code multi-path now
    shares, not a parallel implementation."""
    for model in ("wan2.2-t2v", "wan2.1-t2v-1.3b"):
        template = load_template(model)
        graph = inject(template, {"prompt": "hello", "seed": 7})

        prompt_path = template["inputs"]["prompt"]
        node = graph
        for step in prompt_path[:-1]:
            node = node[step]
        assert node[prompt_path[-1]] == "hello", model

        seed_path = template["inputs"]["seed"]
        node = graph
        for step in seed_path[:-1]:
            node = node[step]
        assert node[seed_path[-1]] == 7, model


def _multi_path_fixture(required=None):
    return {
        "output": {"node": "3", "kind": "video"},
        "defaults": {},
        "inputs": {"length": [["40", "inputs", "length"], ["45", "inputs", "length"]]},
        "required": required or [],
        "graph": {
            "40": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {"length": 33}},
            "45": {"class_type": "WanCameraEmbedding", "inputs": {"length": 33}},
            "3": {"class_type": "KSampler", "inputs": {}},
        },
    }


def test_inject_multi_path_patches_both_locations_in_one_call():
    """A template mapping one parameter to a list of two paths — the
    camera-embedding-versus-latent frame-count case — patches BOTH
    locations with the same value, in one inject() call."""
    template = _multi_path_fixture()
    graph = inject(template, {"length": 81})
    assert graph["40"]["inputs"]["length"] == 81
    assert graph["45"]["inputs"]["length"] == 81


def test_inject_multi_path_unresolvable_path_raises_without_partial_patch():
    """A multi-path entry where one of the paths does not resolve raises a
    clear error naming the param and the failing path, rather than
    silently patching one of the two — a half-patched graph desynchronises
    a latent and a camera embedding, which is worse than a rejected one."""
    template = {
        "output": {"node": "3", "kind": "video"},
        "defaults": {},
        "inputs": {"length": [["40", "inputs", "length"], ["99", "inputs", "length"]]},
        "required": [],
        "graph": {
            "40": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {"length": 33}},
            "3": {"class_type": "KSampler", "inputs": {}},
        },
    }
    with pytest.raises(ComfyUIError, match="length") as exc_info:
        inject(template, {"length": 81})
    assert "99" in str(exc_info.value)
    # the template's own graph was never mutated (inject deep-copies)
    assert template["graph"]["40"]["inputs"]["length"] == 33


def test_inject_required_check_unaffected_by_multi_path_shape():
    """A required param with a multi-path mapping and no supplied value
    still raises — the shape of a param's mapping does not change
    `required` handling."""
    template = _multi_path_fixture(required=["length"])
    with pytest.raises(ComfyUIError, match="length"):
        inject(template, {})


def test_wan_frames_4n_plus_1():
    assert wan_frames(2.0, 16) == 33
    assert wan_frames(0.1, 16) == 5
    for seconds in (1.0, 2.5, 5.0):
        assert (wan_frames(seconds, 16) - 1) % 4 == 0


# --- signature-driven graph audit (comfy_nodes.py) ---------------------------


def test_signature_driven_audit_passes_the_proven_templates():
    """The two templates whose every node class carries a verified
    NodeSignature — the M30-proven wan2.1-t2v-1.3b and the new
    wan2.2-ti2v-5b fallback arm — must audit clean. A failure here means
    either a real wiring regression or a wrong signature; the message lists
    the defects so it reads as a diagnosis, not a bare assertion error."""
    from pipeline_core.comfy_nodes import audit_graph

    for model in ("wan2.1-t2v-1.3b", "wan2.2-ti2v-5b"):
        template = load_template(model)
        defects = audit_graph(template["graph"], output_node=template["output"]["node"])
        assert defects == [], f"{model}: {defects}"


# Ten-plus-one templates independently verified broken today (2026-08-02),
# every entry re-checked against the actual node-pack source rather than
# assumed from research notes. This list is shrink-only: plans 03-02 and
# 03-04 own repairing these templates and emptying it; nothing else may
# grow it back. Two tests below assert both directions — every entry here
# audits dirty, and every template NOT here audits clean — so a repair
# that forgets to shrink the list, or a list entry that silently starts
# passing, fails the suite either way.
#
# Defect classes carried by each entry:
#   wan2.2-t2v/i2v/fun-camera/vace-fun, wan2.1-vace-1.3b, qwen-image:
#     UnetLoaderGGUF wired clip/vae from output indices 1/2 of a node with
#     one output, AND its required key is `unet_name`, not the `ckpt_name`
#     every one of these six passes (city96/ComfyUI-GGUF nodes.py). The
#     five video templates in this group also omit VHS_VideoCombine's
#     three required fields; qwen-image outputs to SaveImage so it does
#     not carry that second defect.
#   wan2.2-i2v, wan2.2-vace-fun, wan2.1-vace-1.3b, wan2.2-fun-camera, sdxl:
#     an unreachable node that is the target of the template's own
#     `inputs` map — source_image, source_video (x2), camera_motion,
#     lora_name are each silently discarded (three of these five are
#     already counted above for the loader-wiring defect too).
#   musetalk-image: VHS_VideoCombine's three missing fields, AND
#     MuseTalkRun's real upstream signature (chaojie/ComfyUI-MuseTalk
#     nodes.py) takes `video_path`/`audio_path`/`bbox_shift`/`batch_size`
#     path strings — not the `image`/`audio`/`seed`/`fps` IMAGE/AUDIO graph
#     connections this template wires. The node-pack manifest's class-name
#     probe (comfy_nodes.py) never caught this; only reading the source did.
#   uni3c, recammaster: VHS_VideoCombine's three missing fields. Their
#     WanVideoWrapper nodes are a declared blind spot (see
#     test_declared_blind_spots_are_visible_and_bounded below), not a
#     defect this audit can currently see — Phase 4 owns verifying that
#     wiring on hardware.
#   ace-step: NOT on this phase's research-time list — found only by
#     reading comfy_extras/nodes_ace.py directly. TextEncodeAceStepAudio
#     declares `lyrics_strength` required regardless of its default value
#     (the exact same rule as VHS_VideoCombine's three fields: a default
#     only sets the client's starting value, ComfyUI's /prompt validation
#     still requires the key present in the submitted graph), and
#     ace-step.json's node 6 does not supply it. This is exactly the kind
#     of latent bug the audit exists to surface — the critical_requirement
#     is to record what is ACTUALLY dirty, not what research anticipated.
AWAITING_REPAIR = frozenset({
    "wan2.2-t2v", "wan2.2-i2v", "wan2.2-fun-camera", "wan2.2-vace-fun",
    "wan2.1-vace-1.3b", "qwen-image", "sdxl", "musetalk-image", "uni3c",
    "recammaster", "ace-step",
})


def test_templates_off_the_ratchet_audit_clean():
    """Every template NOT on AWAITING_REPAIR must audit clean. This is the
    positive half of the ratchet: a template that starts failing without
    being added to the list is a real regression."""
    from pipeline_core.comfy_nodes import audit_graph

    for model in COMFY_MODELS:
        if model in AWAITING_REPAIR:
            continue
        template = load_template(model)
        defects = audit_graph(template["graph"], output_node=template["output"]["node"])
        assert defects == [], f"{model}: {defects}"


def test_templates_on_the_ratchet_audit_dirty():
    """Every template ON AWAITING_REPAIR must audit dirty. This is the
    shrink-only half: a repaired template must be removed from the list,
    not left to silently pass while still listed as broken."""
    from pipeline_core.comfy_nodes import audit_graph

    for model in AWAITING_REPAIR:
        template = load_template(model)
        defects = audit_graph(template["graph"], output_node=template["output"]["node"])
        assert defects, (
            f"{model} now audits clean — remove it from AWAITING_REPAIR "
            f"(tests/test_comfy.py) now that it has been repaired"
        )


def test_every_edge_source_class_has_a_signature_entry():
    """Signature coverage: every class type used as the source of an edge,
    in any shipped template, has an entry in NODE_SIGNATURES — verified or
    explicitly declared unverified. An uncovered class is a class the audit
    is blind to, which is itself a defect (Wave 0 gap this phase closes)."""
    from pipeline_core.comfy_nodes import NODE_SIGNATURES

    for model in COMFY_MODELS:
        template = load_template(model)
        graph = template["graph"]
        for node_id, node in graph.items():
            for field, value in (node.get("inputs") or {}).items():
                if not (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)):
                    continue
                src_id = value[0]
                if src_id not in graph:
                    continue
                src_class = graph[src_id]["class_type"]
                assert src_class in NODE_SIGNATURES, (
                    f"{model}: {src_class} (node {src_id}) is used as an edge "
                    f"source with no NODE_SIGNATURES entry — record its "
                    f"signature from source, or add it with "
                    f"outputs=None/required_inputs=None and a provenance "
                    f"string naming what is and isn't known"
                )


def test_declared_blind_spots_are_visible_and_bounded():
    """Every signature entry recorded as unverified (outputs or
    required_inputs is None) must be exactly the WanVideoWrapper classes
    uni3c/recammaster use — the manifest's own notes already record that
    only their class NAMES were schema-verified against a running
    ComfyUI's /object_info (M11), not their wiring (research Pitfall 4).
    Adding a new unverified entry must be a deliberate act that fails this
    test until the expectation is updated — an audit that silently grows
    its own blind spot is not an audit."""
    from pipeline_core.comfy_nodes import NODE_PACKS, NODE_SIGNATURES

    wanvideo_pack = next(p for p in NODE_PACKS if p.name == "ComfyUI-WanVideoWrapper")
    expected_unverified = frozenset(wanvideo_pack.provides)

    actual_unverified = frozenset(
        class_type for class_type, sig in NODE_SIGNATURES.items()
        if sig.outputs is None or sig.required_inputs is None
    )
    assert actual_unverified == expected_unverified


def test_audit_graph_mutation_guard_output_index_reads_the_signature():
    """Mutation guard: audit_graph's output-index check must read the
    recorded signature, not hardcode a class name. A one-output class
    wired from index 1 is a defect; the same graph against a doctored
    two-output signature for that class is not."""
    from pipeline_core.comfy_nodes import NodeSignature, audit_graph

    graph = {
        "1": {"class_type": "OneOutputLoader", "inputs": {}},
        "2": {"class_type": "Consumer", "inputs": {"model": ["1", 1]}},
    }
    real = {"OneOutputLoader": NodeSignature(outputs=("MODEL",), required_inputs=None, provenance="test")}
    defects = audit_graph(graph, signatures=real, output_node="2")
    assert any("output index 1" in d for d in defects), defects

    doctored = {"OneOutputLoader": NodeSignature(outputs=("MODEL", "CLIP"), required_inputs=None, provenance="test")}
    defects = audit_graph(graph, signatures=doctored, output_node="2")
    assert not any("output index" in d for d in defects), defects


def test_audit_graph_mutation_guard_required_input_reads_the_signature():
    """Mutation guard: a hand-built VHS_VideoCombine node missing
    loop_count produces a defect naming it; the same graph audits clean
    once the key is added."""
    from pipeline_core.comfy_nodes import audit_graph

    graph = {
        "8": {"class_type": "UpstreamStub", "inputs": {}},
        "60": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["8", 0], "frame_rate": 16, "filename_prefix": "x",
            "format": "video/h264-mp4", "pingpong": False, "save_output": True,
        }},
    }
    defects = audit_graph(graph, output_node="60")
    assert any("loop_count" in d for d in defects), defects

    graph["60"]["inputs"]["loop_count"] = 0
    defects = audit_graph(graph, output_node="60")
    assert not any("loop_count" in d for d in defects), defects


def test_audit_graph_flags_dangling_edge_reference():
    """A typo in a node reference — an edge pointing at a node id absent
    from the graph — is reported as a defect."""
    from pipeline_core.comfy_nodes import audit_graph

    graph = {"3": {"class_type": "KSampler", "inputs": {"model": ["99", 0]}}}
    defects = audit_graph(graph)
    assert any("99" in d for d in defects), defects


def test_audit_graph_mutation_guard_reachability_and_inert_param_naming():
    """Mutation guard: a node nothing reads from is a defect; wiring its
    output into the chain makes the same graph audit clean. When the
    orphan is the target of the template's own `inputs` map, the defect
    names the inert studio parameter — that message is the whole value of
    the check."""
    from pipeline_core.comfy_nodes import audit_graph

    orphaned = {
        "1": {"class_type": "Sink", "inputs": {}},
        "2": {"class_type": "Orphan", "inputs": {}},
    }
    defects = audit_graph(orphaned, output_node="1")
    assert any("2" in d and "unreachable" in d for d in defects), defects

    connected = {
        "1": {"class_type": "Sink", "inputs": {"upstream": ["2", 0]}},
        "2": {"class_type": "Orphan", "inputs": {}},
    }
    defects = audit_graph(connected, output_node="1")
    assert not any("unreachable" in d for d in defects), defects

    template_inputs = {"widget_name": ["2", "inputs", "value"]}
    defects = audit_graph(orphaned, output_node="1", template_inputs=template_inputs)
    assert any("widget_name" in d for d in defects), defects


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


def test_build_values_trajectory_serialises_to_json():
    """Uni3C waypoints ride into the embeds node as a JSON string (M11)."""
    fake = FakeComfy()
    client = _client(fake)
    template = load_template("uni3c")
    waypoints = [{"pan": 0.0, "zoom": 1.0}, {"pan": 45.0, "zoom": 1.5}]
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="comfy-test"))
        store.ensure_bucket()
        uri = store.put_bytes("stills/frame.png", b"png-bytes")
        generation = _generation(model="uni3c", kind=GenerationKind.image_to_video,
                                 trajectory=waypoints, image_uri=uri, duration_s=2)
        values = build_values(generation, template, client, store)
    assert json.loads(values["trajectory"]) == waypoints
    assert values["source_image"] in fake.uploads
    graph = inject(template, values)
    assert json.loads(graph["23"]["inputs"]["trajectory"]) == waypoints
    assert graph["12"]["inputs"]["image"] == values["source_image"]


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

    core_prefixes = ("VHS_", "MuseTalk", "FL_Chatterbox", "UnetLoaderGGUF", "WanVideo")
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
    # M11 advanced templates (uni3c/recammaster) made the wrapper required
    assert status["ComfyUI-WanVideoWrapper"]["optional"] is False
    assert status["ComfyUI-WanVideoWrapper"]["installed"] is False


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
