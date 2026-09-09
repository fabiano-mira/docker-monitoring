"""End-to-end tests against a stub ntopng (see conftest)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_requires_api_key(client: TestClient) -> None:
    response = client.get("/v1/summary", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_health_reports_reachable(client: TestClient) -> None:
    body = client.get("/v1/health").json()
    assert body["status"] == "ok"
    assert body["ntopng_reachable"] is True


def test_interfaces(client: TestClient) -> None:
    body = client.get("/v1/interfaces").json()
    assert body["interfaces"] == [{"id": 0, "name": "netflow2ng"}]


def test_summary_aggregates_interface_and_hosts(client: TestClient) -> None:
    body = client.get("/v1/summary", params={"top": 2}).json()
    assert body["active_hosts"] == 3
    assert body["local_hosts"] == 2
    assert body["active_flows"] == 2
    assert [host["name"] for host in body["top_talkers"]] == ["samsung-familyhub", "mac.localdomain"]
    assert body["top_protocols"][0]["name"] == "HTTPS"
    assert body["top_protocols"][0]["share_percent"] == 80.0
    assert "samsung-familyhub" in body["summary"]


def test_top_talkers_orders_by_throughput(client: TestClient) -> None:
    body = client.get("/v1/hosts/top", params={"limit": 2}).json()
    assert [host["ip"] for host in body["hosts"]] == ["10.9.1.50", "10.9.1.10"]
    assert body["hosts"][0]["bytes_received"] == 2_000_000


def test_top_talkers_orders_by_bytes_and_scope(client: TestClient) -> None:
    body = client.get("/v1/hosts/top", params={"order_by": "bytes", "scope": "remote"}).json()
    assert [host["ip"] for host in body["hosts"]] == ["142.250.185.78"]
    assert body["hosts"][0]["country"] == "US"


def test_find_host_matches_name_and_ip(client: TestClient) -> None:
    by_name = client.get("/v1/hosts/search", params={"query": "FAMILY"}).json()
    assert by_name["count"] == 1
    assert by_name["hosts"][0]["ip"] == "10.9.1.50"

    by_ip = client.get("/v1/hosts/search", params={"query": "10.9.1."}).json()
    assert by_ip["count"] == 2

    missing = client.get("/v1/hosts/search", params={"query": "nosuchdevice"}).json()
    assert missing["count"] == 0
    assert "No active host" in missing["summary"]


def test_active_flows_filters(client: TestClient) -> None:
    body = client.get("/v1/flows/active").json()
    assert body["count"] == 2
    assert body["flows"][0]["l7_protocol"] == "HTTPS"
    assert body["flows"][0]["server_port"] == 443

    filtered = client.get("/v1/flows/active", params={"l7_protocol": "dns"}).json()
    assert filtered["count"] == 1
    assert filtered["flows"][0]["client_name"] == "mac.localdomain"

    by_host = client.get("/v1/flows/active", params={"host": "familyhub"}).json()
    assert by_host["count"] == 1


def test_top_protocols_shares_sum_sensibly(client: TestClient) -> None:
    body = client.get("/v1/protocols/top").json()
    assert [proto["name"] for proto in body["protocols"]] == ["HTTPS", "DNS"]
    assert sum(proto["share_percent"] for proto in body["protocols"]) == 100.0


def test_missing_alerts_endpoint_is_reported_not_silently_empty(client: TestClient) -> None:
    body = client.get("/v1/alerts/recent").json()
    assert body["supported"] is False
    assert body["count"] == 0
    assert "does not expose" in body["summary"]
