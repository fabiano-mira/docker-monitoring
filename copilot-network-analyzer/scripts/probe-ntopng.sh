#!/usr/bin/env bash
# Probe which ntopng REST v2 endpoints this deployment actually serves.
#
# ntopng's REST surface varies by version and by Community vs Enterprise, so
# run this on a machine with a route to ntopng *before* trusting the gateway's
# alert and protocol endpoints. Endpoints marked "REQUIRED" back the core
# actions; the others degrade gracefully when missing.
#
# Usage: ./scripts/probe-ntopng.sh [ntopng-url] [ifid]

set -uo pipefail

NTOPNG_URL="${1:-${NTOPNG_URL:-http://10.9.1.241:3001}}"
IFID="${2:-${NTOPNG_IFID:-0}}"
AUTH=()
if [[ -n "${NTOPNG_USER:-}" ]]; then
  AUTH=(-u "${NTOPNG_USER}:${NTOPNG_PASSWORD:-}")
fi

printf 'Probing %s (ifid=%s)\n\n' "$NTOPNG_URL" "$IFID"

probe() {
  local label="$1" path="$2"
  local url="${NTOPNG_URL}${path}"
  local body code rc rows

  body=$(curl -sS -m 10 "${AUTH[@]}" -w '\n%{http_code}' "$url" 2>/dev/null)
  code=$(printf '%s' "$body" | tail -n1)
  body=$(printf '%s' "$body" | sed '$d')

  if [[ "$code" != "200" ]]; then
    printf '  %-42s HTTP %s\n' "$label" "${code:-no response}"
    return
  fi

  rc=$(printf '%s' "$body" | jq -r '.rc // "n/a"' 2>/dev/null)
  rows=$(printf '%s' "$body" | jq -r '(.rsp.data // .rsp | if type=="array" then length else 1 end)' 2>/dev/null)
  printf '  %-42s HTTP 200  rc=%s  rows=%s\n' "$label" "$rc" "${rows:-?}"
}

echo "REQUIRED — core actions"
probe "interfaces"          "/lua/rest/v2/get/ntopng/interfaces.lua"
probe "interface data"      "/lua/rest/v2/get/interface/data.lua?ifid=${IFID}"
probe "active hosts"        "/lua/rest/v2/get/host/active.lua?ifid=${IFID}&perPage=5"
probe "active flows"        "/lua/rest/v2/get/flow/active.lua?ifid=${IFID}&perPage=5"

echo
echo "OPTIONAL — degrade gracefully if absent"
probe "L7 protocol stats"   "/lua/rest/v2/get/interface/l7/stats.lua?ifid=${IFID}&ndpistats_mode=count"
probe "host alerts"         "/lua/rest/v2/get/host/alert/list.lua?ifid=${IFID}&status=historical&perPage=5"
probe "flow alerts"         "/lua/rest/v2/get/flow/alert/list.lua?ifid=${IFID}&status=historical&perPage=5"

echo
echo "Sample host record (field names the mappers read):"
curl -sS -m 10 "${AUTH[@]}" "${NTOPNG_URL}/lua/rest/v2/get/host/active.lua?ifid=${IFID}&perPage=1" 2>/dev/null \
  | jq '.rsp.data[0] // .rsp[0] // "no rows returned"' 2>/dev/null \
  || echo "  (could not parse a sample record)"
