"""GPU-rental provider probes (Settings tab + Dashboard usage).

One probe per provider, all shaped the same: configured = key in env,
online = the provider's API answered, money fields when the API exposes
them. Probes never raise — an unreachable provider degrades to
online=False with the error class in `note`, so Settings can distinguish
"configured but unreachable" from "not set up". Keys travel only in the
outbound request; the API response model carries no secrets.
"""

from __future__ import annotations

from typing import Optional

import httpx
import structlog

from pipeline_core.settings import Settings
from schema.models import RentalProviderStatus

log = structlog.get_logger()

_TIMEOUT = 5.0


def _client(client: Optional[httpx.Client]) -> httpx.Client:
    return client or httpx.Client(timeout=_TIMEOUT)


def probe_vast(settings: Settings, client: Optional[httpx.Client] = None) -> RentalProviderStatus:
    status = RentalProviderStatus(
        name="vast", label="vast.ai", configured=bool(settings.vast_api_key)
    )
    if not status.configured:
        status.note = "set VAST_API_KEY in .env"
        return status
    try:
        http = _client(client)
        user = http.get(
            "https://console.vast.ai/api/v0/users/current",
            params={"api_key": settings.vast_api_key},
        )
        user.raise_for_status()
        status.balance_usd = round(float(user.json().get("credit", 0.0)), 2)
        instances = http.get(
            "https://console.vast.ai/api/v0/instances",
            params={"owner": "me", "api_key": settings.vast_api_key},
        )
        instances.raise_for_status()
        running = [
            i for i in instances.json().get("instances", [])
            if i.get("actual_status") == "running"
        ]
        status.running_instances = len(running)
        status.burn_usd_per_hr = round(
            sum(float(i.get("dph_total", 0.0)) for i in running), 3
        )
        status.online = True
    except Exception as exc:
        status.note = f"probe failed: {type(exc).__name__}"
        log.warning("rental_probe_failed", provider="vast", error=str(exc))
    return status


def probe_runpod(settings: Settings, client: Optional[httpx.Client] = None) -> RentalProviderStatus:
    status = RentalProviderStatus(
        name="runpod", label="RunPod", configured=bool(settings.runpod_api_key)
    )
    if not status.configured:
        status.note = "set RUNPOD_API_KEY in .env"
        return status
    try:
        http = _client(client)
        response = http.post(
            "https://api.runpod.io/graphql",
            params={"api_key": settings.runpod_api_key},
            json={
                "query": "query { myself { clientBalance pods { desiredStatus costPerHr } } }"
            },
        )
        response.raise_for_status()
        myself = response.json()["data"]["myself"]
        status.balance_usd = round(float(myself.get("clientBalance", 0.0)), 2)
        running = [
            p for p in myself.get("pods", []) if p.get("desiredStatus") == "RUNNING"
        ]
        status.running_instances = len(running)
        status.burn_usd_per_hr = round(
            sum(float(p.get("costPerHr", 0.0)) for p in running), 3
        )
        status.online = True
    except Exception as exc:
        status.note = f"probe failed: {type(exc).__name__}"
        log.warning("rental_probe_failed", provider="runpod", error=str(exc))
    return status


def probe_lambda(settings: Settings, client: Optional[httpx.Client] = None) -> RentalProviderStatus:
    status = RentalProviderStatus(
        name="lambda", label="Lambda Cloud", configured=bool(settings.lambda_api_key)
    )
    if not status.configured:
        status.note = "set LAMBDA_API_KEY in .env"
        return status
    try:
        http = _client(client)
        response = http.get(
            "https://cloud.lambdalabs.com/api/v1/instances",
            auth=(settings.lambda_api_key, ""),
        )
        response.raise_for_status()
        instances = response.json().get("data", [])
        running = [i for i in instances if i.get("status") == "active"]
        status.running_instances = len(running)
        status.burn_usd_per_hr = round(
            sum(
                float(i.get("instance_type", {}).get("price_cents_per_hour", 0)) / 100
                for i in running
            ),
            3,
        )
        status.online = True
        status.note = "no balance API — billed to card"
    except Exception as exc:
        status.note = f"probe failed: {type(exc).__name__}"
        log.warning("rental_probe_failed", provider="lambda", error=str(exc))
    return status


def probe_tensordock(settings: Settings, client: Optional[httpx.Client] = None) -> RentalProviderStatus:
    configured = bool(settings.tensordock_api_key and settings.tensordock_api_token)
    return RentalProviderStatus(
        name="tensordock",
        label="TensorDock",
        configured=configured,
        note=(
            "no usage probe wired — dashboard.tensordock.com"
            if configured
            else "set TENSORDOCK_API_KEY + TENSORDOCK_API_TOKEN in .env"
        ),
    )


def probe_rentals(
    settings: Optional[Settings] = None, client: Optional[httpx.Client] = None
) -> list[RentalProviderStatus]:
    settings = settings or Settings()
    return [
        probe_vast(settings, client),
        probe_runpod(settings, client),
        probe_lambda(settings, client),
        probe_tensordock(settings, client),
    ]
