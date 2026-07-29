from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from api.db import get_session
from schema.models import (
    Asset,
    AssetRead,
    Project,
    ProjectAsset,
    ProjectCreate,
    ProjectRead,
    Storyboard,
    utcnow,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _get_or_404(session: Session, project_id: uuid.UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _read(session: Session, project: Project) -> ProjectRead:
    asset_count = session.exec(
        select(func.count()).select_from(ProjectAsset).where(ProjectAsset.project_id == project.id)
    ).one()
    storyboard_count = session.exec(
        select(func.count()).select_from(Storyboard).where(Storyboard.project_id == project.id)
    ).one()
    return ProjectRead(
        **project.model_dump(), asset_count=asset_count, storyboard_count=storyboard_count
    )


@router.post("", response_model=ProjectRead, status_code=201)
async def create_project(body: ProjectCreate, session: Session = Depends(get_session)):
    project = Project.model_validate(body)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _read(session, project)


@router.get("", response_model=list[ProjectRead])
async def list_projects(session: Session = Depends(get_session)):
    projects = session.exec(select(Project).order_by(Project.created_at)).all()
    return [_read(session, project) for project in projects]


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: uuid.UUID, session: Session = Depends(get_session)):
    return _read(session, _get_or_404(session, project_id))


@router.get("/{project_id}/assets", response_model=list[AssetRead])
async def list_project_assets(project_id: uuid.UUID, session: Session = Depends(get_session)):
    _get_or_404(session, project_id)
    rows = session.exec(
        select(Asset)
        .join(ProjectAsset, ProjectAsset.asset_id == Asset.id)
        .where(ProjectAsset.project_id == project_id)
        .order_by(Asset.created_at)
    ).all()
    return rows


@router.post("/{project_id}/assets/{asset_id}", response_model=list[AssetRead], status_code=201)
async def attach_asset(
    project_id: uuid.UUID, asset_id: uuid.UUID, session: Session = Depends(get_session)
):
    """Attach a library asset to this project. Assets are shared: the same
    asset may be attached to any number of projects."""
    project = _get_or_404(session, project_id)
    if session.get(Asset, asset_id) is None:
        raise HTTPException(status_code=404, detail="asset not found")
    existing = session.exec(
        select(ProjectAsset).where(
            ProjectAsset.project_id == project_id, ProjectAsset.asset_id == asset_id
        )
    ).first()
    if existing is None:
        session.add(ProjectAsset(project_id=project_id, asset_id=asset_id))
        project.updated_at = utcnow()
        session.add(project)
        session.commit()
    return await list_project_assets(project_id, session)


@router.delete("/{project_id}/assets/{asset_id}", response_model=list[AssetRead])
async def detach_asset(
    project_id: uuid.UUID, asset_id: uuid.UUID, session: Session = Depends(get_session)
):
    """Detach from this project only — the asset stays in the library and in
    any other project using it."""
    _get_or_404(session, project_id)
    link = session.exec(
        select(ProjectAsset).where(
            ProjectAsset.project_id == project_id, ProjectAsset.asset_id == asset_id
        )
    ).first()
    if link is None:
        raise HTTPException(status_code=404, detail="asset is not attached to this project")
    session.delete(link)
    session.commit()
    return await list_project_assets(project_id, session)
