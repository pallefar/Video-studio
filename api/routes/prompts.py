"""M27 prompt intelligence: the curated catalog (data, with source
attribution), the user's saved-prompt library, and reverse prompt
engineering — turn any library asset back into a reusable prompt via the
M24 Florence-2 caption + the M18 enhancer."""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from pipeline_core.captioner import is_placeholder_caption
from pipeline_core.enhance import get_enhancer
from pipeline_core.prompts import CATEGORIES, catalog
from schema.models import (
    Asset,
    SavedPrompt,
    SavedPromptCreate,
    SavedPromptRead,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])

_STANDARD_NEGATIVE_VIDEO = next(
    e.template for e in catalog(category="negative", kind="video")
)
_STANDARD_NEGATIVE_IMAGE = next(
    e.template for e in catalog(category="negative", kind="image")
)
_IMAGE_SUFFIXES = ("png", "jpg", "jpeg", "webp")


@router.get("/catalog")
async def prompt_catalog(category: str | None = None, kind: str | None = None):
    return {
        "categories": list(CATEGORIES),
        "entries": [asdict(entry) for entry in catalog(category, kind)],
    }


@router.post("", response_model=SavedPromptRead, status_code=201)
async def save_prompt(body: SavedPromptCreate, session: Session = Depends(get_session)):
    prompt = SavedPrompt.model_validate(body)
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


@router.get("", response_model=list[SavedPromptRead])
async def list_prompts(session: Session = Depends(get_session)):
    return session.exec(
        select(SavedPrompt).order_by(SavedPrompt.created_at.desc())
    ).all()


@router.delete("/{prompt_id}", status_code=204)
async def delete_prompt(prompt_id: uuid.UUID, session: Session = Depends(get_session)):
    prompt = session.get(SavedPrompt, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="prompt not found")
    session.delete(prompt)
    session.commit()


@router.post("/reverse/{asset_id}")
async def reverse_prompt(
    asset_id: uuid.UUID,
    save: bool = False,
    session: Session = Depends(get_session),
):
    """Reverse prompt engineering: caption -> structured prompt + standard
    negative. Uses the asset's Florence-2 caption (M24); a placeholder
    caption means there is nothing visual to reverse yet."""
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    if is_placeholder_caption(asset.caption):
        raise HTTPException(
            status_code=409,
            detail="asset has no real caption yet — POST /assets/{id}/caption first (M24)",
        )

    is_image = asset.uri.rsplit(".", 1)[-1].lower() in _IMAGE_SUFFIXES
    prompt = get_enhancer().enhance(asset.caption)
    negative = _STANDARD_NEGATIVE_IMAGE if is_image else _STANDARD_NEGATIVE_VIDEO
    result = {
        "asset_id": str(asset.id),
        "caption": asset.caption,
        "prompt": prompt,
        "negative_prompt": negative,
        "kind": "image" if is_image else "video",
    }
    if save:
        saved = SavedPrompt(
            title=(asset.caption or "reverse prompt")[:60],
            text=prompt,
            kind=result["kind"],
            negative=negative,
            source="reverse",
            asset_id=asset.id,
        )
        session.add(saved)
        session.commit()
        session.refresh(saved)
        result["saved_id"] = str(saved.id)
    return result
