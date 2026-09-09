"""Host-oriented operations: who is on the network and who is busiest."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings, get_settings
from ..dependencies import get_client
from ..mappers import humanize_bps, to_host
from ..ntopng import NtopngClient, NtopngError, NtopngUnavailable
from ..schemas import Host, HostList

router = APIRouter(prefix="/v1/hosts", tags=["hosts"])


async def _load_hosts(client: NtopngClient, ifid: int, per_page: int, sort_column: str) -> list[Host]:
    try:
        rows = await client.active_hosts(ifid, per_page=per_page, sort_column=sort_column)
    except NtopngUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NtopngError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [to_host(row) for row in rows]


@router.get(
    "/top",
    response_model=HostList,
    operation_id="GetTopTalkers",
    summary="Get the busiest hosts on the network right now",
    description=(
        "Returns the hosts currently generating the most traffic, ordered by live "
        "throughput or by total bytes. Use this to answer questions like 'what is "
        "using all the bandwidth', 'who are the top talkers', or 'what is the "
        "busiest device right now'."
    ),
)
async def top_talkers(
    limit: int = Query(10, ge=1, le=100, description="How many hosts to return."),
    order_by: str = Query(
        "throughput",
        pattern="^(throughput|bytes)$",
        description="Rank by live throughput or by cumulative bytes.",
    ),
    scope: str = Query(
        "all",
        pattern="^(all|local|remote)$",
        description="Limit to local hosts, remote hosts, or return both.",
    ),
    interface_id: int | None = Query(None, description="ntopng interface id. Defaults to the configured one."),
    client: NtopngClient = Depends(get_client),
    settings: Settings = Depends(get_settings),
) -> HostList:
    ifid = settings.ntopng_ifid if interface_id is None else interface_id
    sort_column = "thpt" if order_by == "throughput" else "traffic"
    # Over-fetch so scope filtering still leaves `limit` rows to return.
    hosts = await _load_hosts(client, ifid, min(settings.max_page_size, limit * 5 + 50), sort_column)

    if scope == "local":
        hosts = [host for host in hosts if host.is_local]
    elif scope == "remote":
        hosts = [host for host in hosts if not host.is_local]

    key = (lambda host: host.throughput_bps) if order_by == "throughput" else (lambda host: host.bytes_total)
    hosts = sorted(hosts, key=key, reverse=True)[:limit]

    if hosts:
        leader = hosts[0]
        summary = (
            f"Top {len(hosts)} {scope} host(s) by {order_by}: "
            f"{leader.name} leads at {humanize_bps(leader.throughput_bps)}."
        )
    else:
        summary = "No active hosts matched the request."

    return HostList(summary=summary, interface_id=ifid, count=len(hosts), hosts=hosts)


@router.get(
    "/search",
    response_model=HostList,
    operation_id="FindHost",
    summary="Find an active host by name or IP address",
    description=(
        "Case-insensitive substring search over the names and IP addresses of "
        "currently active hosts. Use this when the user names a device, for "
        "example 'is the living room TV online' or 'show me 10.9.1.50'."
    ),
)
async def find_host(
    query: str = Query(..., min_length=1, description="Part of a host name or IP address, e.g. 'iphone' or '10.9.1.'."),
    limit: int = Query(10, ge=1, le=100, description="How many matches to return."),
    interface_id: int | None = Query(None, description="ntopng interface id. Defaults to the configured one."),
    client: NtopngClient = Depends(get_client),
    settings: Settings = Depends(get_settings),
) -> HostList:
    ifid = settings.ntopng_ifid if interface_id is None else interface_id
    hosts = await _load_hosts(client, ifid, settings.max_page_size, "thpt")

    needle = query.lower()
    matches = [host for host in hosts if needle in host.name.lower() or needle in host.ip.lower()][:limit]

    summary = (
        f"Found {len(matches)} active host(s) matching '{query}'."
        if matches
        else f"No active host matches '{query}'. It may be offline or idle."
    )
    return HostList(summary=summary, interface_id=ifid, count=len(matches), hosts=matches)
