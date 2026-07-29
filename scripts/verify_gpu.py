#!/usr/bin/env python3
"""M0 capability check. Run this before debugging anything GPU-related.

Asserts the device is Ampere sm_86 (RTX 3090) — the whole pipeline is built
around BF16-no-FP8 on that capability. Fails loudly on anything else.
"""

from __future__ import annotations

import sys

REQUIRED_CAPABILITY = (8, 6)


def fail(message: str) -> int:
    print("=" * 72, file=sys.stderr)
    print("GPU VERIFICATION FAILED", file=sys.stderr)
    print(message, file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    return 1


def main() -> int:
    try:
        import torch
    except ImportError:
        return fail(
            "torch is not installed. This script must run on the GPU host:\n"
            '    pip install -e ".[gpu]"\n'
            "It is expected to fail on CPU-only machines (CI, cloud sessions)."
        )

    if not torch.cuda.is_available():
        return fail("torch is installed but no CUDA device is available.")

    name = torch.cuda.get_device_name(0)
    capability = torch.cuda.get_device_capability(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3

    if capability != REQUIRED_CAPABILITY:
        return fail(
            f"device is {name} with capability {capability}, expected sm_86 {REQUIRED_CAPABILITY}.\n"
            "This pipeline targets Ampere (RTX 3090): BF16 inference, no FP8.\n"
            "Do not proceed with mismatched quantised checkpoints."
        )

    print(f"OK: {name} — sm_{capability[0]}{capability[1]}, {vram_gb:.1f} GB VRAM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
