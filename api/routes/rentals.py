"""GPU-rental provider status + usage (Settings tab, Dashboard).

Read-only: which providers have keys in env, whether their APIs answer,
and the money that matters (balance, running instances, burn per hour).
Never returns key material — asserted in tests/test_rentals.py.
"""

from __future__ import annotations

from fastapi import APIRouter

from pipeline_core.rentals import probe_rentals
from schema.models import RentalProviderStatus

router = APIRouter(prefix="/rentals", tags=["rentals"])


@router.get("", response_model=list[RentalProviderStatus])
async def rental_status() -> list[RentalProviderStatus]:
    return probe_rentals()
