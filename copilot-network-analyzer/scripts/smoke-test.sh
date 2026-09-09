#!/usr/bin/env bash
# Exercise every gateway operation the way Copilot Studio will.
#
# Usage: GATEWAY_API_KEY=... ./scripts/smoke-test.sh [gateway-url]

set -uo pipefail

BASE="${1:-http://127.0.0.1:8800}"
KEY="${GATEWAY_API_KEY:-}"
HDR=()
[[ -n "$KEY" ]] && HDR=(-H "X-API-Key: ${KEY}")

fail=0

call() {
  local label="$1" path="$2"
  local body code
  body=$(curl -sS -m 20 "${HDR[@]}" -w '\n%{http_code}' "${BASE}${path}" 2>/dev/null)
  code=$(printf '%s' "$body" | tail -n1)
  body=$(printf '%s' "$body" | sed '$d')

  if [[ "$code" == "200" ]]; then
    printf '  ok   %-22s %s\n' "$label" "$(printf '%s' "$body" | jq -r '.summary // .status // "-"' 2>/dev/null)"
  else
    printf '  FAIL %-22s HTTP %s %s\n' "$label" "${code:-none}" "$(printf '%s' "$body" | jq -r '.detail // ""' 2>/dev/null)"
    fail=1
  fi
}

printf 'Smoke-testing %s\n\n' "$BASE"
call "GetHealth"         "/v1/health"
call "ListInterfaces"    "/v1/interfaces"
call "GetNetworkSummary" "/v1/summary?top=3"
call "GetTopTalkers"     "/v1/hosts/top?limit=5&order_by=throughput&scope=local"
call "FindHost"          "/v1/hosts/search?query=10."
call "GetActiveFlows"    "/v1/flows/active?limit=5"
call "GetTopProtocols"   "/v1/protocols/top?limit=5"
call "GetRecentAlerts"   "/v1/alerts/recent?hours=24&limit=5"

echo
if [[ "$fail" -eq 0 ]]; then
  echo "All operations responded."
else
  echo "Some operations failed — check the gateway logs and run scripts/probe-ntopng.sh."
fi
exit "$fail"
