#!/bin/zsh
# check-health.sh — post-reboot verification for the docker-monitoring stack.
#
# Checks:
#   1. Docker daemon + all 12 compose containers
#   2. Native components: goflow2, netflow-relay LaunchAgents, Netdata
#   3. HTTP liveness of every service endpoint
#   4. Prometheus scrape targets
#   5. Grafana datasource health (custom datasources)
#   6. End-to-end data freshness in both NetFlow pipelines
#
# Exit code: 0 if everything passed, 1 if any check failed.

PASS=0
FAIL=0

ok()   { printf "  \033[32m✔\033[0m %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  \033[31m✘\033[0m %s\n" "$1"; FAIL=$((FAIL+1)); }
section() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }

EXPECTED_CONTAINERS=(grafana prometheus loki promtail influxdb influxdb-ntopng telegraf netflow2ng ntopng redis-ntopng node_exporter snmp_exporter)

section "Docker"
if ! docker info >/dev/null 2>&1; then
  bad "Docker daemon not running — start Docker Desktop: open --background -a Docker"
else
  ok "Docker daemon running"
  running=$(docker ps --format '{{.Names}}')
  for c in "${EXPECTED_CONTAINERS[@]}"; do
    if echo "$running" | grep -qx "$c"; then
      ok "container $c"
    else
      bad "container $c NOT running (try: docker compose up -d $c)"
    fi
  done
fi

section "Native components (launchd)"
if launchctl list | grep -q com.netsampler.goflow2; then
  ok "goflow2 LaunchAgent loaded"
else
  bad "goflow2 missing (launchctl load ~/Library/LaunchAgents/com.netsampler.goflow2.plist)"
fi
if launchctl list | grep -q com.netmon.netflow-relay; then
  ok "netflow-relay LaunchAgent loaded"
else
  bad "netflow-relay missing (launchctl load ~/Library/LaunchAgents/com.netmon.netflow-relay.plist)"
fi
if brew services list 2>/dev/null | grep netdata | grep -q started; then
  ok "netdata (brew service) started"
else
  bad "netdata not started (brew services start netdata)"
fi

section "UDP listeners"
for port in 2055 2057; do
  if lsof -nP -iUDP:$port >/dev/null 2>&1; then
    ok "UDP :$port bound"
  else
    bad "nothing listening on UDP :$port"
  fi
done

section "HTTP endpoints"
# name|url|acceptable_codes (regex)
endpoints=(
  "grafana|http://localhost:3000/api/health|200"
  "prometheus|http://localhost:9090/-/healthy|200"
  "loki|http://localhost:3100/ready|200|503"          # 503 w/ 'waiting after ready' is a benign startup hold
  "influxdb-v2|http://localhost:8086/health|200"
  "influxdb-ntopng|http://localhost:8087/ping|204"
  "ntopng|http://localhost:3001/lua/rest/v2/get/host/active.lua?ifid=0&perPage=1|200"
  "netdata|http://localhost:19999/api/v1/info|200"
  "netflow2ng|http://localhost:8091/metrics|200"
  "snmp-exporter|http://localhost:9116/|200"
  "node-exporter|http://localhost:9100/metrics|200"
)
for e in "${endpoints[@]}"; do
  name="${e%%|*}"
  rest="${e#*|}"
  url="${rest%%|*}"
  codes="${rest#*|}"
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url")
  if echo "$code" | grep -qE "^(${codes//|/|})$"; then
    ok "$name ($code)"
  else
    bad "$name returned $code ($url)"
  fi
done

section "Prometheus scrape targets"
targets_json=$(curl -s --max-time 5 http://localhost:9090/api/v1/targets)
if [ -n "$targets_json" ]; then
  echo "$targets_json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for t in d['data']['activeTargets']:
    job = t['labels'].get('job')
    health = t['health']
    mark = '\033[32m✔\033[0m' if health == 'up' else '\033[31m✘\033[0m'
    print(f'  {mark} target {job} -> {health}')
" 
  down=$(echo "$targets_json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(sum(1 for t in d['data']['activeTargets'] if t['health'] != 'up'))")
  PASS=$((PASS+1))
  [ "$down" != "0" ] && FAIL=$((FAIL+1))
else
  bad "could not fetch Prometheus targets"
fi

section "Grafana datasources"
for uid in influxdb-netflow influxdb-ntopng infinity-ntopng; do
  ds_status=$(curl -s -u admin:admin --max-time 10 -X POST "http://localhost:3000/api/datasources/uid/$uid/health" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','ERR'))" 2>/dev/null)
  if [ "$ds_status" = "OK" ]; then
    ok "datasource $uid"
  else
    bad "datasource $uid -> $ds_status"
  fi
done

section "Data freshness"
# ntopng -> InfluxDB 1.8: newest iface:hosts point should be < 5 min old
ntopng_age=$(docker exec influxdb-ntopng influx -database ntopng -format json \
  -execute 'SELECT last("num_hosts") FROM "iface:hosts"' 2>/dev/null | python3 -c "
import json, sys, time
try:
    d = json.load(sys.stdin)
    ts_ns = d['results'][0]['series'][0]['values'][0][0]
    print(int(time.time() - ts_ns / 1e9))
except Exception:
    print(-1)")
if [ "$ntopng_age" -ge 0 ] && [ "$ntopng_age" -lt 300 ]; then
  ok "ntopng InfluxDB data fresh (${ntopng_age}s old)"
else
  bad "ntopng InfluxDB data stale or missing (age: ${ntopng_age}s)"
fi

# goflow2 flows.log: modified within last 10 min
if [ -f "$HOME/Library/Logs/goflow2/flows.log" ]; then
  log_age=$(( $(date +%s) - $(stat -f %m "$HOME/Library/Logs/goflow2/flows.log") ))
  if [ "$log_age" -lt 600 ]; then
    ok "goflow2 flows.log fresh (${log_age}s old)"
  else
    bad "goflow2 flows.log stale (${log_age}s old) — check router export + relay"
  fi
else
  bad "goflow2 flows.log not found"
fi

printf "\n\033[1m== Summary: %d passed, %d failed ==\033[0m\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
