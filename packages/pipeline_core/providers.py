"""The generation provider layer (roadmap-v2 §3, M10).

One interface over three provider classes: `local` (this workstation's wan
lane), `remote-gpu` (the same executor on a rented box — a queue-config
change), and `api` (proprietary hosted models). Every output enters the
pipeline as an Asset with origin='generated' — no path around the compliance
gates. API keys come from Settings; an unconfigured provider is not
registered.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol

import httpx

from pipeline_core.settings import Settings
from schema.models import Generation, GenerationKind

LOCAL_PROVIDER = "local"

# Provider class determines the execution lane: local runs on the wan queue
# under the exclusive GPU lock; api runs as a network job on the cpu queue.
CLASS_LOCAL = "local"
CLASS_API = "api"


# GPU lanes for local models (roadmap-v2 §5): "wan" is the exclusive-lock
# lane for the 14B-class models; "shared" rides the render lane alongside the
# resident Chatterbox/MuseTalk (ACE-Step base, VACE 1.3B previews, ...).
LANE_WAN = "wan"
LANE_SHARED = "shared"


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    kinds: frozenset[GenerationKind]
    provider_class: str
    notes: str = ""
    lane: str = LANE_WAN
    # Estimated $ per generation: 0.0 = local/free, None = unpriced. The
    # single-user replacement for Higgsfield's credit system (roadmap §3).
    est_cost: float | None = None


@dataclass
class ProviderResult:
    download_url: Optional[str] = None
    data: Optional[bytes] = None
    content_type: str = "video/mp4"
    external_id: Optional[str] = None
    cost: Optional[float] = None


class UnknownModelError(Exception):
    pass


class GenerationProvider(Protocol):
    name: str
    provider_class: str

    def models(self) -> list[ModelSpec]: ...

    def generate(self, generation: Generation) -> ProviderResult: ...


class LocalWanProvider:
    """The wan-lane executor on this machine. Model roster per roadmap-v2 §2.
    Execution order: DEV_ENGINES placeholder synthesis, else the headless
    ComfyUI configured by COMFY_URL (the M10 decision), else a config hint —
    which surfaces inside run_generation's fallback handling, so a declared
    API fallback still completes the request."""

    name = LOCAL_PROVIDER
    provider_class = CLASS_LOCAL

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings
        self._dev_executor = None

    def models(self) -> list[ModelSpec]:
        video = frozenset({GenerationKind.text_to_video, GenerationKind.image_to_video})
        image = frozenset({GenerationKind.image})
        return [
            ModelSpec(self.name, "wan2.2-t2v", frozenset({GenerationKind.text_to_video}), CLASS_LOCAL, est_cost=0.0),
            ModelSpec(self.name, "wan2.2-i2v", frozenset({GenerationKind.image_to_video}), CLASS_LOCAL, est_cost=0.0),
            ModelSpec(self.name, "wan2.2-fun-camera", video, CLASS_LOCAL, "camera presets, M11", est_cost=0.0),
            # Image studio roster (M12, roadmap-v2 §2) — all commercially clean.
            ModelSpec(self.name, "z-image-turbo", image, CLASS_LOCAL, "image daily driver, M12", est_cost=0.0),
            ModelSpec(self.name, "qwen-image", image, CLASS_LOCAL, "text-heavy thumbnails, M12", est_cost=0.0),
            ModelSpec(self.name, "sdxl", image, CLASS_LOCAL, "style LoRAs + identity training, M12", est_cost=0.0),
            # VFX & finishing lane (M13). FILM is the interpolation pick —
            # RIFE stays out per the licence register's training-data caveat.
            ModelSpec(self.name, "wan2.2-vace-fun", frozenset({GenerationKind.video_to_video}),
                      CLASS_LOCAL, "effect presets, M13", est_cost=0.0),
            ModelSpec(self.name, "wan2.1-vace-1.3b", frozenset({GenerationKind.video_to_video}),
                      CLASS_LOCAL, "fast effect preview, M13", est_cost=0.0),
            ModelSpec(self.name, "seedvr2-3b", frozenset({GenerationKind.upscale}),
                      CLASS_LOCAL, "hero-shot upscale, M13", est_cost=0.0),
            ModelSpec(self.name, "real-esrgan", frozenset({GenerationKind.upscale}),
                      CLASS_LOCAL, "cheap upscale lane, M13", lane=LANE_SHARED, est_cost=0.0),
            ModelSpec(self.name, "film", frozenset({GenerationKind.upscale}),
                      CLASS_LOCAL, "frame interpolation, M13", lane=LANE_SHARED, est_cost=0.0),
            # Audio suite (M18): ACE-Step base fits the render lane's headroom.
            ModelSpec(self.name, "ace-step", frozenset({GenerationKind.music}),
                      CLASS_LOCAL, "music beds, M18 (Apache 2.0)", lane=LANE_SHARED, est_cost=0.0),
            # Talking/singing photos + voiceovers (M28) ride the render lane:
            # MuseTalk and Chatterbox are its residents (both MIT).
            ModelSpec(self.name, "musetalk-image", frozenset({GenerationKind.talking_image}),
                      CLASS_LOCAL, "talking/singing photo, M28 (MIT)", lane=LANE_SHARED, est_cost=0.0),
            ModelSpec(self.name, "chatterbox", frozenset({GenerationKind.voice}),
                      CLASS_LOCAL, "voiceover lines, M28 (MIT)", lane=LANE_SHARED, est_cost=0.0),
        ]

    def generate(self, generation: Generation) -> ProviderResult:
        settings = self._settings or Settings()
        if settings.dev_engines:
            from pipeline_core.dev_generation import DevGenerationExecutor

            if self._dev_executor is None:
                self._dev_executor = DevGenerationExecutor()
            return self._dev_executor.generate(generation)

        from pipeline_core.comfy import ComfyUINotConfiguredError, run_comfy_generation

        if not settings.comfy_url:
            raise ComfyUINotConfiguredError()
        data, content_type, prompt_id = run_comfy_generation(generation, settings=settings)
        # cost 0.0, not None: local generation is free, distinct from unpriced
        return ProviderResult(
            data=data, content_type=content_type, external_id=prompt_id, cost=0.0
        )


class FalProvider:
    """fal.ai queue API — the aggregator gateway that covers most of the
    Higgsfield roster (Kling, Seedance, Hailuo/Minimax, hosted Wan, ...) with
    one integration. submit -> poll -> fetch, run as a network job."""

    name = "fal"
    provider_class = CLASS_API

    # Curated roster; grows as models are vetted. Model ids are fal endpoint
    # ids; costs are flat per-generation estimates (data, revised over time —
    # the actual billed amount wins whenever the response ever carries one).
    ROSTER: list[tuple[str, frozenset[GenerationKind], float]] = [
        ("fal-ai/kling-video/v2/master/text-to-video", frozenset({GenerationKind.text_to_video}), 1.40),
        ("fal-ai/kling-video/v2/master/image-to-video", frozenset({GenerationKind.image_to_video}), 1.40),
        ("fal-ai/bytedance/seedance/v1/pro", frozenset({GenerationKind.text_to_video, GenerationKind.image_to_video}), 0.74),
        ("fal-ai/minimax/hailuo-02/standard/text-to-video", frozenset({GenerationKind.text_to_video}), 0.48),
        ("fal-ai/flux/schnell", frozenset({GenerationKind.image}), 0.003),
    ]

    def __init__(self, api_key: str, client: Optional[httpx.Client] = None, poll_interval_s: float = 3.0):
        self._client = client or httpx.Client(timeout=60)
        self._headers = {"Authorization": f"Key {api_key}"}
        self._poll_interval_s = poll_interval_s

    def models(self) -> list[ModelSpec]:
        return [
            ModelSpec(self.name, model, kinds, CLASS_API, est_cost=cost)
            for model, kinds, cost in self.ROSTER
        ]

    def generate(self, generation: Generation) -> ProviderResult:
        payload = {"prompt": generation.prompt, **(generation.params or {})}
        submit = self._client.post(
            f"https://queue.fal.run/{generation.model}", json=payload, headers=self._headers
        )
        submit.raise_for_status()
        job = submit.json()
        request_id = job["request_id"]
        status_url = job.get("status_url") or f"https://queue.fal.run/{generation.model}/requests/{request_id}/status"
        response_url = job.get("response_url") or f"https://queue.fal.run/{generation.model}/requests/{request_id}"

        while True:
            status = self._client.get(status_url, headers=self._headers)
            status.raise_for_status()
            state = status.json().get("status")
            if state == "COMPLETED":
                break
            if state in ("FAILED", "CANCELLED", "ERROR"):
                raise RuntimeError(f"fal generation {request_id} ended {state}")
            time.sleep(self._poll_interval_s)

        response = self._client.get(response_url, headers=self._headers)
        response.raise_for_status()
        body = response.json()
        media = body.get("video") or body.get("image") or {}
        if isinstance(media, list):
            media = media[0] if media else {}
        url = media.get("url")
        if not url:
            raise RuntimeError(f"fal generation {request_id} returned no media url")
        est = next((cost for model, _, cost in self.ROSTER if model == generation.model), None)
        return ProviderResult(
            download_url=url,
            content_type=media.get("content_type", "video/mp4"),
            external_id=request_id,
            cost=body.get("billed_cost", est),  # billed wins over the estimate
        )


class ElevenLabsProvider:
    """ElevenLabs direct API (roadmap-v2 §3 "direct APIs where it matters").

    Voice beyond Chatterbox, plus sound effects and music. Synchronous HTTP —
    the response body IS the audio — run as a network job on the cpu lane
    like every API provider. ToS recorded at integration (roadmap §3 rule):
    commercial use of generated audio requires a paid ElevenLabs plan; the
    licence string on each generated asset says so, and the owner's
    data-egress decision is configuring ELEVENLABS_API_KEY."""

    name = "elevenlabs"
    provider_class = CLASS_API

    BASE = "https://api.elevenlabs.io"
    # Default voice: "Rachel", ElevenLabs' stock premade voice. Override per
    # request with params.voice_id.
    DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
    DEFAULT_TTS_MODEL = "eleven_multilingual_v2"
    SFX_MAX_S = 22.0  # API cap on /v1/sound-generation duration

    # Flat per-generation cost estimates (data, revised over time); a billed
    # amount from the API would win, but ElevenLabs bills by monthly credits.
    ROSTER: list[tuple[str, frozenset[GenerationKind], float, str]] = [
        ("eleven-tts", frozenset({GenerationKind.voice}), 0.15,
         "TTS / voiceovers, 70+ languages"),
        ("eleven-sfx", frozenset({GenerationKind.music}), 0.08,
         f"sound effects, <= {int(SFX_MAX_S)} s"),
        ("eleven-music", frozenset({GenerationKind.music}), 0.50,
         "full music tracks (Eleven Music)"),
    ]

    def __init__(self, api_key: str, client: Optional[httpx.Client] = None):
        self._client = client or httpx.Client(timeout=300)
        self._headers = {"xi-api-key": api_key}

    def models(self) -> list[ModelSpec]:
        return [
            ModelSpec(self.name, model, kinds, CLASS_API,
                      notes=f"{notes} — paid-plan commercial licence", est_cost=cost)
            for model, kinds, cost, notes in self.ROSTER
        ]

    def generate(self, generation: Generation) -> ProviderResult:
        params = generation.params or {}
        if generation.model == "eleven-tts":
            voice_id = params.get("voice_id") or self.DEFAULT_VOICE_ID
            response = self._client.post(
                f"{self.BASE}/v1/text-to-speech/{voice_id}",
                params={"output_format": "mp3_44100_128"},
                json={
                    "text": generation.prompt,
                    "model_id": params.get("tts_model", self.DEFAULT_TTS_MODEL),
                },
                headers=self._headers,
            )
        elif generation.model == "eleven-sfx":
            payload: dict = {"text": generation.prompt}
            if params.get("duration_s"):
                payload["duration_seconds"] = min(float(params["duration_s"]), self.SFX_MAX_S)
            response = self._client.post(
                f"{self.BASE}/v1/sound-generation", json=payload, headers=self._headers
            )
        elif generation.model == "eleven-music":
            response = self._client.post(
                f"{self.BASE}/v1/music",
                json={
                    "prompt": generation.prompt,
                    "music_length_ms": int(float(params.get("duration_s", 60)) * 1000),
                },
                headers=self._headers,
            )
        else:
            raise UnknownModelError(f"unknown elevenlabs model {generation.model!r}")
        response.raise_for_status()
        est = next((cost for model, _, cost, _ in self.ROSTER if model == generation.model), None)
        return ProviderResult(
            data=response.content,
            content_type=response.headers.get("content-type", "audio/mpeg").split(";")[0],
            cost=est,
        )


@dataclass
class ProviderRegistry:
    providers: dict[str, GenerationProvider] = field(default_factory=dict)

    def register(self, provider: GenerationProvider) -> None:
        self.providers[provider.name] = provider

    def resolve(self, provider_name: str, model: str, kind: GenerationKind) -> tuple[GenerationProvider, ModelSpec]:
        provider = self.providers.get(provider_name)
        if provider is None:
            raise UnknownModelError(f"unknown provider {provider_name!r}")
        for spec in provider.models():
            if spec.model == model:
                if kind not in spec.kinds:
                    raise UnknownModelError(f"{provider_name}/{model} does not support {kind.value}")
                return provider, spec
        raise UnknownModelError(f"unknown model {provider_name}/{model}")

    def catalog(self) -> list[ModelSpec]:
        return [spec for provider in self.providers.values() for spec in provider.models()]


def build_registry(settings: Optional[Settings] = None) -> ProviderRegistry:
    settings = settings or Settings()
    registry = ProviderRegistry()
    registry.register(LocalWanProvider())
    if settings.fal_api_key:
        registry.register(FalProvider(settings.fal_api_key))
    if settings.elevenlabs_api_key:
        registry.register(ElevenLabsProvider(settings.elevenlabs_api_key))
    return registry
