"""Flow-oriented operations: what conversations are happening right now."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings, get_settings
from ..dependencies import get_client
from ..mappers import humanize_bytes, to_flow, to_protocols
from ..ntopng import NtopngClient, NtopngError, NtopngUnavailable
from ..schemas import FlowList, ProtocolList

router = APIRouter(prefix="/v1", tags=["flows"])


@router.get(
    "/flows/active",
    response_model=FlowList,
    operation_id="GetActiveFlows",
    summary="List the active network conversations",
    description=(
        "Returns currently active flows (client, server, application protocol and "
        "volume), heaviest first, optionally filtered to one host or one protocol. "
        "Use this to answer 'who is my laptop talking to', 'what is this device "
        "downloading', or 'show me current connections'."
    ),
)
async def active_flows(
    limit: int = Query(20, ge=1, le=200, description="How many flows to return."),
    host: str | None = Query(None, description="Restrict to flows involving this IP address or host name."),
    l7_protocol: str | None = Query(None, description="Restrict to one application protocol, e.g. HTTPS, DNS, Netflix."),
    interface_id: int | None = Query(None, description="ntopng interface id. Defaults to the configured one."),
    client: NtopngClient = Depends(get_client),
    settings: Settings = Depends(get_settings),
) -> FlowList:
    ifid = settings.ntopng_ifid if interface_id is None else interface_id
    try:
        rows = await client.active_flows(ifid, per_page=settings.max_page_size)
    except NtopngUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NtopngError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    flows = [to_flow(row) for row in rows]

    if host:
        needle = host.lower()
        flows = [
            flow
            for flow in flows
            if needle in flow.client_ip.lower()
            or needle in flow.server_ip.lower()
            or needle in (flow.client_name or "").lower()
            or needle in (flow.server_name or "").lower()
        ]
    if l7_protocol:
        wanted = l7_protocol.lower()
        flows = [flow for flow in flows if wanted in (flow.l7_protocol or "").lower()]

    flows = sorted(flows, key=lambda flow: flow.bytes_total, reverse=True)[:limit]

    total = sum(flow.bytes_total for flow in flows)
    summary = (
        f"{len(flows)} active flow(s) carrying {humanize_bytes(total)}."
        if flows
        else "No active flows matched the request."
    )
    return FlowList(summary=summary, interface_id=ifid, count=len(flows), flows=flows)


@router.get(
    "/protocols/top",
    response_model=ProtocolList,
    operation_id="GetTopProtocols",
    summary="Break traffic down by application protocol",
    description=(
        "Returns the heaviest application protocols detected by nDPI, with each "
        "one's share of total traffic. Use this for 'what kind of traffic is on my "
        "network', 'how much is streaming', or 'what protocol is dominant'."
    ),
)
async def top_protocols(
    limit: int = Query(10, ge=1, le=50, description="How many protocols to return."),
    interface_id: int | None = Query(None, description="ntopng interface id. Defaults to the configured one."),
    client: NtopngClient = Depends(get_client),
    settings: Settings = Depends(get_settings),
) -> ProtocolList:
    ifid = settings.ntopng_ifid if interface_id is None else interface_id
    try:
        rows = await client.l7_stats(ifid)
    except NtopngUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NtopngError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    protocols = to_protocols(rows, limit)
    summary = (
        f"Top protocol is {protocols[0].name} at {protocols[0].share_percent}% of traffic."
        if protocols
        else "ntopng reported no protocol breakdown for this interface."
    )
    return ProtocolList(summary=summary, interface_id=ifid, protocols=protocols)
