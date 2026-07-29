# Pipeline Spec — hardware, models, ffmpeg chains, failure modes

Companion to `docs/psd.md`. This is the technical reference the PSD points at.
Performance figures below are **PLACEHOLDER estimates** until M0's `scripts/bench.py`
replaces them with measurements from the actual card (§6).

---

## 1. Hardware

| Item | Value | Consequence |
|---|---|---|
| GPU | RTX 3090, 24 GB GDDR6X | One model lane at a time; render and B-roll generation are mutually exclusive |
| Compute capability | `sm_86` (Ampere) | **No FP8.** FP8 needs Ada (`sm_89`) / Hopper (`sm_90`). Use BF16 for inference, GGUF/INT8 for quantised checkpoints |
| VRAM budget (render lane) | Chatterbox + MuseTalk resident together, peak **< 20 GB** | Leaves headroom for CUDA fragmentation and decode buffers; asserted by `bench.py --smoke` |
| VRAM budget (B-roll lane) | Wan 2.2 quantised ≈ full card | Separate queue, exclusive GPU lock (`tests/test_gpu_exclusivity.py`) |
| Thermals | Long renders throttle | Every stage logs duration to the metrics table; throughput regression = first throttling symptom |

`scripts/verify_gpu.py` asserts `torch.cuda.get_device_capability() == (8, 6)` and exits
non-zero with a loud message otherwise. Run it before debugging anything GPU-shaped.

## 2. Models

| Role | Model | Licence | Precision | Notes |
|---|---|---|---|---|
| TTS + voice clone | Chatterbox | MIT | BF16 | Emits an inaudible audio watermark — **must survive the encode chain** (compliance C3) |
| Lip-sync | MuseTalk | MIT | BF16 | Latent-space inpainting; benefits hugely from the per-loop latent cache (M2) |
| Generative B-roll | Wan 2.2 | Apache 2.0 | GGUF / INT8 — **never FP8** | Separate lane only, see §1 |
| Captions | faster-whisper | MIT | int8 on CPU is fine | Word-level timings feed caption burn-in |

Rejected (recorded so the decision isn't relitigated — full reasoning in psd.md §4.1):
XTTS v2 (CPML, non-commercial), F5-TTS (CC-BY-NC), Wav2Lip (research-only),
HunyuanVideo (Tencent community licence), LTX-2.3 (FP8 + 32 GB), Mochi 1 (viable fallback,
weaker feature set).

Weights: pinned versions, scripted download (script lands with M3's worker image work).
Never committed to git; local path configured via `CLAUDE.local.md` / env.

## 3. RenderJob — canonical JSON

The API representation of one video's lifecycle (single source of truth:
`packages/schema/models.py`; this example is illustrative, the schema is normative).

```json
{
  "id": "8f7c9c2e-6a1b-4f0e-9a3d-2b5f8d1c4e77",
  "title": "Why your backlog is lying to you",
  "script": "Full script text; split into segments at ingest.",
  "status": "review",
  "voice_profile_id": "d2a4...",
  "base_loop_id": "77b1...",
  "watermark": { "text": "Made with AI", "position": "bottom_right", "persistent": true },
  "publish": { "altered_content": true, "visibility": "private" },
  "segments": [
    { "idx": 0, "text": "First sentence.", "pause_after_ms": 300,
      "audio_uri": "s3://avatar-pipeline/jobs/8f7c.../tts/0.wav",
      "duration_ms": 2140, "seed": 421337 }
  ],
  "error": null,
  "created_at": "2026-07-29T10:00:00Z",
  "updated_at": "2026-07-29T10:14:12Z"
}
```

State machine: `queued → tts → lipsync → assemble → review → publishing → published`,
with `failed` reachable from any active stage (`failed → queued` retries),
`review → queued` for per-segment re-renders, and `cancelled` terminal.
Every stage is idempotent on `(job_id, stage)`; segment-level TTS uses `tts:{idx}`.

## 4. ffmpeg chains (CPU worker, M4)

Ingest rule: **constant frame rate only** — probe with `ffprobe`; reject VFR sources
at loop ingest rather than discovering drift at assembly.

Assembly chain, in order:

1. **Loudness**: two-pass `loudnorm` to **−14 LUFS** (YouTube's normalisation target),
   `I=-14:TP=-1.5:LRA=11`.
2. **Watermark burn-in**: "Made with AI" text overlay, bottom-right, full duration —
   never a timed overlay. Compliance C1; frame-sampled at 10/50/90% by M5's test.
3. **Caption burn-in**: subtitles filter from faster-whisper word timings (ASS styling).
4. **B-roll insertion**: overlay/concat at beat timestamps from the asset resolver;
   avatar audio continues underneath.
5. **Encode**: `libx264 -crf 18 -pix_fmt yuv420p -movflags +faststart`, AAC 192k audio.

Encode-chain constraint (C3): Chatterbox's audio watermark must survive loudnorm + AAC;
the M4/M5 test round-trips a rendered clip and asserts the watermark is still detectable.

Lip-sync is chunked at **60–90 s windows** to bound VRAM and make retries cheap;
chunks are stitched at assembly.

## 5. Failure modes

| Failure | Symptom | Handling |
|---|---|---|
| VFR source footage | A/V drift at assembly | Reject at ingest (ffprobe check), never mid-pipeline |
| CUDA OOM | Lip-sync chunk dies | Chunked windows + segment-level retry; never widen the window on retry |
| One bad TTS sentence | Garbled audio in one segment | Segment is the retry unit — re-render `tts:{idx}` alone with its pinned seed |
| Thermal throttling | Stage durations creep up | Metrics table per stage; alert on regression, not on absolute numbers |
| Spot/rented box vanishes | Job stuck in an active stage | Stages idempotent on `(job_id, stage)`; re-enqueue is always safe |
| YouTube quota exhaustion | Uploads fail late in the day | Distinguish quota errors from real failures; back off to next quota window, don't retry-hammer |
| Seam pop in base loop | Visible jump at loop boundary | Perceptual-hash seam detection at ingest; ping-pong playback fallback (M2) |

## 6. Performance budget — PLACEHOLDERS, replace at M0

> **Every number below is an estimate, not a measurement.** M0's
> `python scripts/bench.py --smoke` prints the real figures for this card;
> paste them here and delete this banner. Do not reason from these numbers
> downstream — that's how V100-era folklore gets baked into scheduling.

| Stage | Placeholder estimate (8-min video) |
|---|---|
| TTS (Chatterbox, ~90 segments) | ~2–3 min |
| Lip-sync (MuseTalk, cached latents) | ~6–8 min |
| Lip-sync (first run, no cache) | ~10–14 min |
| Assembly + encode (CPU) | ~2–3 min |
| **Total wall clock target** | **< 20 min** (PSD success criterion) |
| Wan 2.2, 5 s clip (B-roll lane) | ~3–6 min |

## 7. Service topology

Local: docker-compose provides Postgres 16 (:5432), Redis 7 (:6379), MinIO (:9000, console :9001).
API and workers run natively. All addresses flow from env (`.env.example`) through
`pipeline_core.settings.Settings`; the worker packages contain no service literals
(`tests/test_portability.py` enforces this).

Remote (later): same worker code, env pointed at rented box over Tailscale/WireGuard;
MinIO swapped for S3/R2 by changing `S3_ENDPOINT`. Workers drain the queue and shut
down — never one box per video.
