"""Translate raw ntopng records into the flat models the agent consumes.

Field paths come from what this deployment's Grafana panels already read out
of ntopng (grafana/dashboards/cc-live-flows.json and
ntopng-live-hosts-dashboard.json in the parent repo), with alternates for the
names other ntopng releases use. Anything missing degrades to a neutral
default rather than failing the whole request.
"""

from __future__ import annotations

from typing import Any

from .ntopng import dig
from .schemas import Alert, Flow, Host, Protocol


def _scalar(value: Any, *keys: str) -> Any:
    """ntopng sometimes returns a display object where a scalar is expected."""
    if isinstance(value, dict):
        for key in (*keys, "value", "label", "name"):
            if key in value:
                return value[key]
        return None
    return value


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_host(row: dict[str, Any]) -> Host:
    ip = str(_scalar(dig(row, "ip", "address", "host"), "ip") or "")
    name = str(_scalar(dig(row, "name", "label"), "name") or ip)
    return Host(
        ip=ip,
        name=name,
        is_local=bool(dig(row, "is_localhost", "localhost", "is_local", default=False)),
        country=(_scalar(dig(row, "country"), "country") or None),
        throughput_bps=_float(dig(row, "thpt.bps", "throughput_bps", "thpt")),
        bytes_total=_int(dig(row, "bytes.total", "bytes", "traffic.total")),
        bytes_sent=_int(dig(row, "bytes.sent", "bytes_sent", "sent.bytes")),
        bytes_received=_int(dig(row, "bytes.recvd", "bytes.rcvd", "bytes_rcvd", "rcvd.bytes")),
        active_flows=_int(dig(row, "num_flows.total", "num_flows", "active_flows")),
        last_seen=_int(dig(row, "last_seen", "seen.last")) or None,
    )


def to_flow(row: dict[str, Any]) -> Flow:
    client_ip = str(_scalar(dig(row, "client.ip", "cli.ip", "cli_ip"), "ip") or "")
    server_ip = str(_scalar(dig(row, "server.ip", "srv.ip", "srv_ip"), "ip") or "")
    client_name = _scalar(dig(row, "client.name", "cli.name", "cli_name"), "name")
    server_name = _scalar(dig(row, "server.name", "srv.name", "srv_name"), "name")
    port = dig(row, "server.port", "srv.port", "srv_port", "dst_port")
    return Flow(
        client_ip=client_ip,
        client_name=str(client_name) if client_name else None,
        server_ip=server_ip,
        server_name=str(server_name) if server_name else None,
        server_port=_int(port) or None,
        l7_protocol=(_scalar(dig(row, "protocol.l7", "l7_proto", "proto.l7"), "name") or None),
        l4_protocol=(_scalar(dig(row, "protocol.l4", "l4_proto", "proto.l4"), "name") or None),
        bytes_total=_int(dig(row, "bytes", "bytes.total", "traffic.total")),
        throughput_bps=_float(dig(row, "throughput_bps", "thpt.bps", "thpt")),
    )


def to_protocols(rows: list[dict[str, Any]], limit: int) -> list[Protocol]:
    tallies: list[tuple[str, int]] = []
    for row in rows:
        name = _scalar(dig(row, "proto", "protocol", "name", "label"), "name")
        total = _int(dig(row, "bytes", "bytes.total", "traffic", "value"))
        if name and total:
            tallies.append((str(name), total))

    grand_total = sum(total for _, total in tallies)
    tallies.sort(key=lambda item: item[1], reverse=True)
    return [
        Protocol(
            name=name,
            bytes_total=total,
            share_percent=round(total * 100 / grand_total, 1) if grand_total else 0.0,
        )
        for name, total in tallies[:limit]
    ]


def to_alert(row: dict[str, Any]) -> Alert:
    message = _scalar(dig(row, "msg", "message", "description", "alert_name"), "name")
    return Alert(
        time=_int(dig(row, "tstamp", "time", "first_seen")) or None,
        severity=(_scalar(dig(row, "severity", "alert_severity"), "label") or None),
        alert_type=(_scalar(dig(row, "alert_type", "alert_id", "type"), "label") or None),
        entity=(_scalar(dig(row, "entity_val", "entity", "host"), "value") or None),
        message=str(message) if message else None,
    )


def humanize_bps(bps: float) -> str:
    for unit in ("bps", "Kbps", "Mbps", "Gbps"):
        if bps < 1000 or unit == "Gbps":
            return f"{bps:.1f} {unit}"
        bps /= 1000
    return f"{bps:.1f} Gbps"


def humanize_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if count < 1024 or unit == "TB":
            return f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} TB"
