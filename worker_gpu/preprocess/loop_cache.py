"""Latent cache builder for base loops (M2, GPU half).

Bridges MuseTalk's own local-disk preparation cache (`coords.pkl`,
`latents.pt`, optionally `mask_coords.pkl`) to ObjectStore. The expensive
model call — face detection + landmark extraction + VAE encode — never
happens in this module; it lives entirely behind the `prepare(source, out)`
seam passed into `build_loop_cache`, so this file has no CUDA dependency and
is fully exercised on a CUDA-less machine with a fake preparer.

Cache layout (locked 02-01 Task 1, option-a — no schema migration, no
`export_ts.py` regen; this phase stays worker-only code):

    loops/{loop_id}/cache/latents.pt        <- BaseLoop.latents_uri (a FILE)
    loops/{loop_id}/cache/bbox/coords.pkl        \\
    loops/{loop_id}/cache/bbox/mask_coords.pkl   /  <- BaseLoop.bbox_uri (a PREFIX,
                                                       not a single object — the two
                                                       URI columns do not mean the
                                                       same kind of thing. mask_coords
                                                       is optional; coords is not)

Idempotent on the loop's own persisted state: `cache_is_present` is the one
place that question is answered, everywhere in this codebase — a build call
against a loop with a live cache never touches the store's write path or a
model.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Callable, Optional

from pipeline_core.db import open_session
from pipeline_core.storage import ObjectStore
from schema.models import BaseLoop

# MuseTalk's own filenames — its contract, not ours. Keep separate from the
# key functions below: the filenames are what the pinned MuseTalk commit
# writes into a local avatar directory; the keys are this phase's S3 layout
# choice and could change independently.
LATENTS_FILENAME = "latents.pt"
COORDS_FILENAME = "coords.pkl"
MASK_COORDS_FILENAME = "mask_coords.pkl"

# The seam where CUDA enters: writes MuseTalk's own filenames into out_dir,
# reading the downloaded source video at source_path. Returns nothing.
PrepareFn = Callable[[Path, Path], None]


def cache_prefix(loop_id: str) -> str:
    return f"loops/{loop_id}/cache"


def latents_key(loop_id: str) -> str:
    """The single object backing BaseLoop.latents_uri."""
    return f"{cache_prefix(loop_id)}/{LATENTS_FILENAME}"


def bbox_prefix(loop_id: str) -> str:
    """The prefix backing BaseLoop.bbox_uri. Unlike latents_key, this names a
    PREFIX holding multiple members (coords_key, and optionally
    mask_coords_key), not a single object — a reader of the schema should not
    assume bbox_uri resolves with `store.exists()` the way latents_uri does."""
    return f"{cache_prefix(loop_id)}/bbox"


def coords_key(loop_id: str) -> str:
    return f"{bbox_prefix(loop_id)}/{COORDS_FILENAME}"


def mask_coords_key(loop_id: str) -> str:
    """Optional bbox-prefix member — see MASK_COORDS_FILENAME's P1-C note in
    02-RESEARCH.md. Uploaded only if the preparer wrote it; downloaded only if
    the key exists."""
    return f"{bbox_prefix(loop_id)}/{MASK_COORDS_FILENAME}"


def cache_is_present(store: ObjectStore, loop: BaseLoop) -> bool:
    """Is this loop cached? Both halves matter: the column must be set AND
    the object it names must actually be present in the store — a column
    pointing at a deleted blob must read as a miss, or the loop looks cached
    forever and silently skips its own rebuild (ingest_stage's `store.exists`
    check before treating derivatives as present is the same precedent)."""
    if not loop.latents_uri:
        return False
    _, key = store.parse_uri(loop.latents_uri)
    return store.exists(key)


def build_loop_cache(store: ObjectStore, loop_id: str, prepare: PrepareFn) -> bool:
    """Idempotent: a loop with a live cache is a no-op that never downloads
    the source, never calls `prepare`, and never touches the columns.
    Returns whether a build actually happened.

    On a miss: download the source into a tempfile scratch dir, hand `prepare`
    a fresh empty subdirectory to write MuseTalk's own filenames into, upload
    the required files (and the optional mask-coords file if present), and
    only after every upload has returned, record both URI columns in one
    commit. A crash or a raised exception at any point before that commit
    leaves both columns null — never pointing at a partially-uploaded cache.
    Everything local lives inside the tempfile scratch and is gone when this
    function returns, on every path.
    """
    with open_session() as session:
        loop = session.get(BaseLoop, uuid.UUID(loop_id))
        if loop is None:
            raise ValueError(f"loop {loop_id} not found")
        if cache_is_present(store, loop):
            return False
        source_uri = loop.source_uri

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _, source_key = store.parse_uri(source_uri)
        source_path = tmp_path / "source"
        store.get_file(source_key, source_path)

        out_dir = tmp_path / "prepared"
        out_dir.mkdir()
        prepare(source_path, out_dir)

        latents_path = out_dir / LATENTS_FILENAME
        coords_path = out_dir / COORDS_FILENAME
        if not latents_path.exists() or not coords_path.exists():
            preparer_name = getattr(prepare, "__qualname__", repr(prepare))
            raise RuntimeError(
                f"prepare callable {preparer_name!r} did not produce the required "
                f"cache files ({LATENTS_FILENAME}, {COORDS_FILENAME}) for loop {loop_id}"
            )

        # Only the required filenames plus the one optional filename are ever
        # uploaded — anything else the preparer leaves behind (including
        # MuseTalk's own per-frame PNG directories, full_imgs/ and mask/) is
        # discarded with the scratch dir. No per-frame image is ever
        # persisted to ObjectStore.
        store.put_file(latents_key(loop_id), latents_path)
        store.put_file(coords_key(loop_id), coords_path)

        mask_path = out_dir / MASK_COORDS_FILENAME
        if mask_path.exists():
            store.put_file(mask_coords_key(loop_id), mask_path)

    with open_session() as session:
        loop = session.get(BaseLoop, uuid.UUID(loop_id))
        if loop is None:
            raise ValueError(f"loop {loop_id} not found")
        loop.latents_uri = store.uri_for(latents_key(loop_id))
        loop.bbox_uri = store.uri_for(bbox_prefix(loop_id))
        session.add(loop)
        session.commit()

    return True


def load_loop_cache(store: ObjectStore, loop_id: str, dest_dir: Path) -> Optional[Path]:
    """The reverse bridge: restores MuseTalk's own flat filenames into
    dest_dir's root — not our S3 key layout. That asymmetry is deliberate:
    the S3 key layout is this phase's choice and may change, while the flat
    directory layout is MuseTalk's own `Avatar` contract and must mirror it
    exactly, so a future caller can point MuseTalk's own preparation-skipping
    code path straight at dest_dir.

    Returns dest_dir on a hit, None on a miss. A miss never raises and never
    touches dest_dir — no partial files are ever created. Skips the optional
    mask-coords file when its key is absent.
    """
    if not store.exists(latents_key(loop_id)):
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    store.get_file(latents_key(loop_id), dest_dir / LATENTS_FILENAME)
    store.get_file(coords_key(loop_id), dest_dir / COORDS_FILENAME)
    if store.exists(mask_coords_key(loop_id)):
        store.get_file(mask_coords_key(loop_id), dest_dir / MASK_COORDS_FILENAME)
    return dest_dir
