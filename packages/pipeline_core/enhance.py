"""Prompt enhancement (M18) — Wan prompts benefit hugely from expansion.

Qwen3.5-4B via llama.cpp on CPU is the real enhancer (workstation install,
[enhance] extra); until it lands, a deterministic heuristic appends the
quality/production vocabulary the Wan family responds to. Either way the
contract is fixed here: an enhanced generation records BOTH prompts —
`prompt_raw` in params, the enhanced text as the generation prompt.
"""

from __future__ import annotations

from typing import Protocol

import structlog

log = structlog.get_logger()

QUALITY_SUFFIX = (
    "highly detailed, cinematic lighting, natural motion, "
    "professional color grading, sharp focus, coherent composition"
)


class PromptEnhancer(Protocol):
    name: str

    def enhance(self, prompt: str) -> str: ...


class HeuristicEnhancer:
    """Deterministic fallback: appends Wan-friendly quality vocabulary once."""

    name = "heuristic"

    def enhance(self, prompt: str) -> str:
        if QUALITY_SUFFIX in prompt:
            return prompt
        return f"{prompt}, {QUALITY_SUFFIX}"


class QwenEnhancer:
    """Qwen3.5-4B GGUF via llama-cpp-python (CPU). Loads once per process."""

    name = "qwen3.5-4b"

    def __init__(self, model_path: str):
        self._model_path = model_path
        self._llm = None

    def enhance(self, prompt: str) -> str:
        if self._llm is None:
            from llama_cpp import Llama  # lazy: [enhance] extra, workstation

            self._llm = Llama(model_path=self._model_path, n_ctx=2048, verbose=False)
        response = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": (
                    "Rewrite the user's video-generation prompt to be vivid and "
                    "specific: subject, motion, lighting, lens, mood. One "
                    "paragraph, no preamble."
                )},
                {"role": "user", "content": prompt},
            ],
            max_tokens=256,
        )
        return response["choices"][0]["message"]["content"].strip()


_enhancer: PromptEnhancer | None = None


def get_enhancer() -> PromptEnhancer:
    global _enhancer
    if _enhancer is None:
        try:
            import llama_cpp  # noqa: F401
            from pipeline_core.settings import Settings

            model_path = getattr(Settings(), "qwen_model_path", "")
            _enhancer = QwenEnhancer(model_path) if model_path else HeuristicEnhancer()
        except ImportError:
            _enhancer = HeuristicEnhancer()
        log.info("prompt_enhancer_selected", enhancer=_enhancer.name)
    return _enhancer


def apply_enhancement(prompt: str, params: dict | None) -> tuple[str, dict]:
    """Enhance and record: returns (enhanced_prompt, params-with-raw)."""
    enhancer = get_enhancer()
    enhanced = enhancer.enhance(prompt)
    return enhanced, {**(params or {}), "prompt_raw": prompt, "enhancer": enhancer.name}
