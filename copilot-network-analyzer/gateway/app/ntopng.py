"""Thin async client for ntopng's REST v2 API.

ntopng wraps every response in {"rc": 0, "rc_str": "OK", "rsp": ...} and its
list endpoints page their payload as {"rsp": {"data": [...], "totalRows": N}}.
This module hides both, plus the field-name drift between ntopng versions, so
the routers only ever see plain dicts.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class NtopngError(RuntimeError):
    """ntopng was reachable but refused or failed the request."""


class NtopngUnavailable(RuntimeError):
    """ntopng could not be reached at all."""


def dig(record: dict[str, Any], *paths: str, default: Any = None) -> Any:
    """Return the first present value among dotted `paths`.

    ntopng renames fields between releases (bytes.recvd vs bytes.rcvd, for
    one), so every read names the alternatives it accepts.
    """
    for path in paths:
        cursor: Any = record
        for part in path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                cursor = None
                break
            cursor = cursor[part]
        if cursor is not None:
            return cursor
    return default


class NtopngClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.ntopng_url,
            timeout=settings.ntopng_timeout,
            auth=settings.ntopng_auth,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Call a REST v2 endpoint and return its unwrapped `rsp` payload."""
        try:
            response = await self._client.get(path, params=params or {})
        except httpx.HTTPError as exc:  # DNS, connect, timeout, TLS
            raise NtopngUnavailable(f"cannot reach ntopng at {self._settings.ntopng_url}: {exc}") from exc

        if response.status_code == 401:
            raise NtopngError("ntopng rejected the credentials (set NTOPNG_USER/NTOPNG_PASSWORD)")
        if response.status_code == 404:
            raise NtopngError(f"ntopng has no endpoint {path} (check your ntopng version)")
        if response.status_code >= 400:
            raise NtopngError(f"ntopng returned HTTP {response.status_code} for {path}")

        try:
            body = response.json()
        except ValueError as exc:
            # A login redirect serving HTML is the usual cause here.
            raise NtopngError(f"ntopng returned a non-JSON body for {path}") from exc

        if isinstance(body, dict) and body.get("rc") not in (None, 0):
            raise NtopngError(f"ntopng error for {path}: {body.get('rc_str_hr') or body.get('rc_str')}")

        return body.get("rsp", body) if isinstance(body, dict) else body

    async def get_rows(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Call a paged endpoint and return just its rows."""
        payload = await self.get(path, params)
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            rows = payload.get("data", [])
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    # --- endpoints -------------------------------------------------------

    async def interfaces(self) -> list[dict[str, Any]]:
        payload = await self.get("/lua/rest/v2/get/ntopng/interfaces.lua")
        return payload if isinstance(payload, list) else []

    async def interface_data(self, ifid: int) -> dict[str, Any]:
        payload = await self.get("/lua/rest/v2/get/interface/data.lua", {"ifid": ifid})
        return payload if isinstance(payload, dict) else {}

    async def active_hosts(
        self,
        ifid: int,
        per_page: int,
        sort_column: str = "thpt",
        sort_order: str = "desc",
    ) -> list[dict[str, Any]]:
        return await self.get_rows(
            "/lua/rest/v2/get/host/active.lua",
            {
                "ifid": ifid,
                "perPage": per_page,
                "currentPage": 1,
                "sortColumn": sort_column,
                "sortOrder": sort_order,
            },
        )

    async def active_flows(self, ifid: int, per_page: int, host: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"ifid": ifid, "perPage": per_page, "currentPage": 1}
        if host:
            params["host"] = host
        return await self.get_rows("/lua/rest/v2/get/flow/active.lua", params)

    async def l7_stats(self, ifid: int) -> list[dict[str, Any]]:
        return await self.get_rows(
            "/lua/rest/v2/get/interface/l7/stats.lua",
            {"ifid": ifid, "ndpistats_mode": "count", "breed": "true"},
        )

    async def alerts(self, ifid: int, epoch_begin: int, epoch_end: int, per_page: int) -> list[dict[str, Any]]:
        return await self.get_rows(
            "/lua/rest/v2/get/host/alert/list.lua",
            {
                "ifid": ifid,
                "epoch_begin": epoch_begin,
                "epoch_end": epoch_end,
                "perPage": per_page,
                "currentPage": 1,
                "status": "historical",
            },
        )
