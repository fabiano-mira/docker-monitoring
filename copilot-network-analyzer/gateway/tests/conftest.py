"""Test fixtures.

The gateway is exercised against a stub ntopng whose payloads copy the real
response shapes (rc/rsp envelope, rsp.data rows) so the mappers are tested on
what ntopng actually sends.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.ntopng import NtopngClient

HOSTS = [
    {
        "ip": "10.9.1.50",
        "name": "samsung-familyhub",
        "is_localhost": True,
        "country": "",
        "bytes": {"total": 5_000_000, "sent": 3_000_000, "recvd": 2_000_000},
        "num_flows": {"total": 12},
        "thpt": {"bps": 8_500_000.0},
        "last_seen": 1_757_000_000,
    },
    {
        "ip": "10.9.1.10",
        "name": "mac.localdomain",
        "is_localhost": True,
        "country": "",
        "bytes": {"total": 2_000_000, "sent": 1_500_000, "recvd": 500_000},
        "num_flows": {"total": 30},
        "thpt": {"bps": 1_200_000.0},
        "last_seen": 1_757_000_010,
    },
    {
        "ip": "142.250.185.78",
        "name": "google.com",
        "is_localhost": False,
        "country": "US",
        "bytes": {"total": 9_000_000, "sent": 1_000_000, "recvd": 8_000_000},
        "num_flows": {"total": 4},
        "thpt": {"bps": 400_000.0},
        "last_seen": 1_757_000_020,
    },
]

FLOWS = [
    {
        "key": "1",
        "client": {"ip": "10.9.1.50", "name": "samsung-familyhub"},
        "server": {"ip": "142.250.185.78", "name": "google.com", "port": 443},
        "protocol": {"l7": "HTTPS", "l4": "TCP"},
        "bytes": 4_000_000,
    },
    {
        "key": "2",
        "client": {"ip": "10.9.1.10", "name": "mac.localdomain"},
        "server": {"ip": "10.9.1.1", "name": "router", "port": 53},
        "protocol": {"l7": "DNS", "l4": "UDP"},
        "bytes": 12_000,
    },
]

L7 = [
    {"proto": "HTTPS", "bytes": 8_000_000},
    {"proto": "DNS", "bytes": 2_000_000},
]

IFACE = {
    "ifname": "netflow2ng",
    "num_hosts": 3,
    "num_local_hosts": 2,
    "num_flows": 2,
    "throughput_bps": 10_100_000.0,
}


def _wrap(payload: Any) -> httpx.Response:
    return httpx.Response(200, json={"rc": 0, "rc_str": "OK", "rsp": payload})


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/ntopng/interfaces.lua"):
        return _wrap([{"ifid": 0, "ifname": "netflow2ng"}])
    if path.endswith("/interface/data.lua"):
        return _wrap(IFACE)
    if path.endswith("/host/active.lua"):
        return _wrap({"data": HOSTS, "totalRows": len(HOSTS)})
    if path.endswith("/flow/active.lua"):
        return _wrap({"data": FLOWS, "totalRows": len(FLOWS)})
    if path.endswith("/interface/l7/stats.lua"):
        return _wrap({"data": L7})
    if path.endswith("/host/alert/list.lua"):
        return httpx.Response(404, text="not found")
    return httpx.Response(404, text=json.dumps({"rc": 1, "rc_str": "NOT FOUND"}))


@pytest.fixture
def settings() -> Settings:
    config = Settings()
    config.ntopng_url = "http://ntopng.test"
    config.api_keys = ["test-key"]
    return config


@pytest.fixture
def client(settings: Settings) -> TestClient:
    transport = httpx.MockTransport(_handler)

    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        test_client.app.state.ntopng = NtopngClient(
            settings,
            client=httpx.AsyncClient(base_url=settings.ntopng_url, transport=transport),
        )
        test_client.headers.update({"X-API-Key": "test-key"})
        yield test_client
    app.dependency_overrides.clear()
