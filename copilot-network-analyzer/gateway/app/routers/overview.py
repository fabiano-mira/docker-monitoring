"""Whole-network operations: the snapshot an agent opens a conversation with."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import __version__
from ..config import Settings, get_settings
from ..dependencies import get_client
from ..mappers import humanize_bps, to_alert, to_host, to_protocols
from ..ntopng import NtopngClient, NtopngError, NtopngUnavailable, dig
from ..schemas import AlertList, Health, Interface, InterfaceList, NetworkSummary

router = APIRouter(prefix="/v1", tags=["overview"])


@router.get(
    "/health",
    response_model=Health,
    operation_id="GetHealth",
    summary="Check that the gateway can reach ntopng",
    description="Connectivity probe. Use it when another operation fails, to tell the user whether ntopng itself is down.",
)
async def health(
    client: NtopngClient = Depends(get_client),
    settings: Settings = Depends(get_settings),
) -> Health:
    try:
        await client.interfaces()
    except (NtopngError, NtopngUnavailable) as exc:
        return Health(
            status="degraded",
            gateway_version=__version__,
            ntopng_url=settings.ntopng_url,
            ntopng_reachable=False,
            detail=str(exc),
        )
    return Health(
        status="ok",
        gateway_version=__version__,
        ntopng_url=settings.ntopng_url,
        ntopng_reachable=True,
    )


@router.get(
    "/interfaces",
    response_model=InterfaceList,
    operation_id="ListInterfaces",
    summary="List the interfaces ntopng is monitoring",
    description="Returns the interface ids that other operations accept. Most deployments have exactly one.",
)
async def list_interfaces(client: NtopngClient = Depends(get_client)) -> InterfaceList:
    try:
        raw = await client.interfaces()
    except NtopngUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NtopngError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    interfaces: list[Interface] = []
    # ntopng returns either {"0": "iface"} or a list of {ifid, ifname} records.
    if isinstance(raw, dict):
        items = [{"ifid": key, "ifname": value} for key, value in raw.items()]
    else:
        items = raw
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            ifid = int(dig(item, "ifid", "id", default=0))
        except (TypeError, ValueError):
            continue
        interfaces.append(Interface(id=ifid, name=str(dig(item, "ifname", "name", default=f"ifid {ifid}"))))

    return InterfaceList(
        summary=f"ntopng is monitoring {len(interfaces)} interface(s).",
        interfaces=interfaces,
    )


@router.get(
    "/summary",
    response_model=NetworkSummary,
    operation_id="GetNetworkSummary",
    summary="Get an overall snapshot of the network right now",
    description=(
        "One call returning active host and flow counts, aggregate throughput, the "
        "busiest hosts and the heaviest protocols. Prefer this for broad, opening "
        "questions such as 'how is my network doing', 'anything unusual', or "
        "'give me a status update' — it avoids several narrower calls."
    ),
)
async def network_summary(
    top: int = Query(5, ge=1, le=20, description="How many top talkers and protocols to include."),
    interface_id: int | None = Query(None, description="ntopng interface id. Defaults to the configured one."),
    client: NtopngClient = Depends(get_client),
    settings: Settings = Depends(get_settings),
) -> NetworkSummary:
    ifid = settings.ntopng_ifid if interface_id is None else interface_id

    iface_task = client.interface_data(ifid)
    hosts_task = client.active_hosts(ifid, per_page=settings.max_page_size)
    l7_task = client.l7_stats(ifid)
    try:
        iface, host_rows, l7_rows = await asyncio.gather(iface_task, hosts_task, l7_task)
    except NtopngUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NtopngError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    hosts = [to_host(row) for row in host_rows]
    hosts.sort(key=lambda host: host.throughput_bps, reverse=True)
    protocols = to_protocols(l7_rows, top)

    active_hosts = int(dig(iface, "num_hosts", "stats.num_hosts", default=len(hosts)) or len(hosts))
    local_hosts = int(dig(iface, "num_local_hosts", default=sum(1 for host in hosts if host.is_local)) or 0)
    active_flows = int(dig(iface, "num_flows", "stats.num_flows", default=0) or 0)
    throughput = float(dig(iface, "throughput_bps", "thpt.bps", default=sum(h.throughput_bps for h in hosts)) or 0)

    leader = f" Busiest host: {hosts[0].name} at {humanize_bps(hosts[0].throughput_bps)}." if hosts else ""
    protocol_note = f" Dominant protocol: {protocols[0].name} ({protocols[0].share_percent}%)." if protocols else ""
    summary = (
        f"{active_hosts} active host(s) ({local_hosts} local) and {active_flows} active flow(s), "
        f"moving {humanize_bps(throughput)} in total.{leader}{protocol_note}"
    )

    return NetworkSummary(
        summary=summary,
        interface_name=str(dig(iface, "ifname", "name", default="") or "") or None,
        active_hosts=active_hosts,
        local_hosts=local_hosts,
        active_flows=active_flows,
        throughput_bps=throughput,
        top_talkers=hosts[:top],
        top_protocols=protocols,
    )


@router.get(
    "/alerts/recent",
    response_model=AlertList,
    operation_id="GetRecentAlerts",
    summary="List recent ntopng alerts",
    description=(
        "Returns alerts ntopng raised over a recent window. Use this for 'anything "
        "wrong', 'any security alerts', or 'what happened overnight'. Some ntopng "
        "Community builds do not expose the alerts API — the response then has "
        "supported=false, and the agent should say alerting is unavailable rather "
        "than that the network is clean."
    ),
)
async def recent_alerts(
    hours: int = Query(24, ge=1, le=168, description="How far back to look, in hours."),
    limit: int = Query(20, ge=1, le=100, description="How many alerts to return."),
    interface_id: int | None = Query(None, description="ntopng interface id. Defaults to the configured one."),
    client: NtopngClient = Depends(get_client),
    settings: Settings = Depends(get_settings),
) -> AlertList:
    ifid = settings.ntopng_ifid if interface_id is None else interface_id
    now = int(time.time())
    try:
        rows = await client.alerts(ifid, epoch_begin=now - hours * 3600, epoch_end=now, per_page=limit)
    except NtopngUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NtopngError as exc:
        # A build without the alerts endpoint is a normal, reportable state,
        # not a failure: say so explicitly so the agent does not read the
        # empty list as "no alerts".
        return AlertList(
            summary=f"This ntopng build does not expose the alerts API ({exc}).",
            supported=False,
            count=0,
            alerts=[],
        )

    alerts = [to_alert(row) for row in rows][:limit]
    summary = (
        f"{len(alerts)} alert(s) in the last {hours}h."
        if alerts
        else f"No alerts recorded in the last {hours}h."
    )
    return AlertList(summary=summary, supported=True, count=len(alerts), alerts=alerts)
