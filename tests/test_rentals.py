"""GPU-rental provider probes: configured/online semantics, usage parsing,
graceful degradation, and the no-secrets guarantee on /rentals."""

from __future__ import annotations

import json

import httpx

from pipeline_core.rentals import (
    probe_lambda,
    probe_rentals,
    probe_runpod,
    probe_tensordock,
    probe_vast,
)
from pipeline_core.settings import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_unconfigured_providers_do_no_network():
    def explode(request):  # any request is a test failure
        raise AssertionError(f"unexpected request to {request.url}")

    statuses = probe_rentals(_settings(), _transport(explode))
    assert [s.name for s in statuses] == ["vast", "runpod", "lambda", "tensordock"]
    assert all(not s.configured and not s.online for s in statuses)
    assert all(s.note for s in statuses)  # every one says what to set


def test_vast_probe_parses_balance_and_burn():
    def handler(request):
        assert "api_key=k-vast" in str(request.url)
        if "users/current" in request.url.path:
            return httpx.Response(200, json={"credit": 12.345})
        return httpx.Response(200, json={"instances": [
            {"actual_status": "running", "dph_total": 0.099},
            {"actual_status": "running", "dph_total": 0.2},
            {"actual_status": "exited", "dph_total": 0.5},
        ]})

    status = probe_vast(_settings(vast_api_key="k-vast"), _transport(handler))
    assert status.configured and status.online
    assert status.balance_usd == 12.35
    assert status.running_instances == 2
    assert status.burn_usd_per_hr == 0.299


def test_runpod_probe_parses_graphql_shape():
    def handler(request):
        body = json.loads(request.content)
        assert "myself" in body["query"]
        return httpx.Response(200, json={"data": {"myself": {
            "clientBalance": 25.0,
            "pods": [
                {"desiredStatus": "RUNNING", "costPerHr": 0.22},
                {"desiredStatus": "EXITED", "costPerHr": 0.22},
            ],
        }}})

    status = probe_runpod(_settings(runpod_api_key="k-rp"), _transport(handler))
    assert status.online and status.balance_usd == 25.0
    assert status.running_instances == 1
    assert status.burn_usd_per_hr == 0.22


def test_lambda_probe_counts_active_instances():
    def handler(request):
        return httpx.Response(200, json={"data": [
            {"status": "active", "instance_type": {"price_cents_per_hour": 75}},
            {"status": "terminated", "instance_type": {"price_cents_per_hour": 75}},
        ]})

    status = probe_lambda(_settings(lambda_api_key="k-l"), _transport(handler))
    assert status.online and status.running_instances == 1
    assert status.burn_usd_per_hr == 0.75
    assert status.balance_usd is None  # Lambda has no balance API


def test_unreachable_provider_degrades_not_raises():
    def handler(request):
        raise httpx.ConnectError("down")

    status = probe_vast(_settings(vast_api_key="k"), _transport(handler))
    assert status.configured and not status.online
    assert "ConnectError" in status.note


def test_tensordock_requires_both_key_and_token():
    assert not probe_tensordock(_settings(tensordock_api_key="k")).configured
    assert probe_tensordock(
        _settings(tensordock_api_key="k", tensordock_api_token="t")
    ).configured


def test_rentals_route_never_leaks_key_material(client, monkeypatch):
    secret = "sk-rental-secret-abc123"
    for var in ("VAST_API_KEY", "RUNPOD_API_KEY", "LAMBDA_API_KEY"):
        monkeypatch.setenv(var, secret)

    # probes will fail to reach real APIs from CI — that's the point:
    # configured=True, online=False, and no secret anywhere in the body
    import pipeline_core.rentals as rentals_module

    monkeypatch.setattr(
        rentals_module.httpx, "Client",
        lambda **kw: _transport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("no net"))),
    )
    response = client.get("/rentals")
    assert response.status_code == 200
    body = response.text
    assert secret not in body
    providers = {p["name"]: p for p in response.json()}
    assert providers["vast"]["configured"] is True
    assert providers["vast"]["online"] is False
