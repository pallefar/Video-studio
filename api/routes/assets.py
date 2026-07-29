from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from schema.models import Asset, AssetCreate, AssetRead

router = APIRouter(prefix="/assets", tags=["assets"])


def _get_or_404(session: Session, asset_id: uuid.UUID) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


@router.post("", response_model=AssetRead, status_code=201)
async def create_asset(body: AssetCreate, session: Session = Depends(get_session)):
    asset = Asset.model_validate(body)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get("", response_model=list[AssetRead])
async def list_assets(session: Session = Depends(get_session)):
    return session.exec(select(Asset).order_by(Asset.created_at)).all()


@router.get("/{asset_id}", response_model=AssetRead)
async def get_asset(asset_id: uuid.UUID, session: Session = Depends(get_session)):
    return _get_or_404(session, asset_id)


@router.post("/{asset_id}/approve", response_model=AssetRead)
async def approve_asset(asset_id: uuid.UUID, session: Session = Depends(get_session)):
    """Human approval gate: clears the identifiable-people flag hold and makes
    the asset selectable by the resolver (M8)."""
    asset = _get_or_404(session, asset_id)
    asset.approved = True
    asset.has_identifiable_people = False
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/{asset_id}/flag", response_model=AssetRead)
async def flag_asset(asset_id: uuid.UUID, session: Session = Depends(get_session)):
    asset = _get_or_404(session, asset_id)
    asset.approved = False
    asset.has_identifiable_people = True
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset
