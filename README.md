# docker-monitoring

A local observability stack for macOS host metrics, a UniFi Dream Router (SNMP + NetFlow/IPFIX), and general infrastructure monitoring — built on Prometheus, Grafana, Loki, InfluxDB, and ntopng.

## Architecture
There are currently two parallel NetFlow collection paths: the original goflow2 → Loki/InfluxDB(v2) pipeline (per-flow log records, queried via LogQL/InfluxQL) and a newer netflow2ng → ntopng pipeline (live ZMQ flow stream, browsable traffic dashboard with its own historical timeseries store). Both can run side by side since the router can export NetFlow to multiple collector ports.
```mermaid
flowchart LR
  subgraph Host["macOS Host (native)"]
    Netdata["Netdata :19999<br/>host metrics + SNMP poller"]
    goflow2["goflow2 :2055/:8080<br/>NetFlow/IPFIX collector"]
    FlowLog["flows.log<br/>(JSON per-flow records)"]
    goflow2 --> FlowLog
  end

  Router["UniFi Dream Router<br/>10.9.1.1"] -- "SNMP v2c" --> Netdata
  Router -- "NetFlow/IPFIX :2057" --> Relay["netflow-relay.py<br/>(native, LaunchAgent)"]
  Relay -- ":2055" --> goflow2
  Relay -- ":2056" --> netflow2ng
  SNMPExp["snmp_exporter :9116"] -- "SNMP v2c poll" --> Router

  subgraph Docker["Docker Compose stack"]
    Prometheus["Prometheus :9090"]
    Grafana["Grafana :3000"]
    Loki["Loki :3100"]
    Promtail["Promtail"]
    InfluxDB["InfluxDB (v2) :8086<br/>bucket: netflow"]
    Telegraf["Telegraf"]
    NodeExp["node_exporter :9100"]
    netflow2ng["netflow2ng :2056/:8091"]
    ntopng["ntopng :3001"]
    RedisNtopng["redis-ntopng"]
    InfluxNtopng["InfluxDB (v1.8) :8087<br/>db: ntopng"]
  end

  Netdata -- "scrape /allmetrics" --> Prometheus
  SNMPExp -- "scrape /snmp" --> Prometheus
  NodeExp -- "scrape" --> Prometheus
  FlowLog -- "tail" --> Promtail --> Loki
  FlowLog -- "tail (poll)" --> Telegraf --> InfluxDB
  netflow2ng -- "ZMQ tcp://5556" --> ntopng
  ntopng --> RedisNtopng
  ntopng -- "timeseries write" --> InfluxNtopng

  Prometheus --> Grafana
  Loki --> Grafana
  InfluxDB --> Grafana
```

## Services

| Service | Image | Port | Purpose |
|---|---|---|---|
| `prometheus` | `prom/prometheus` | 9090 | Scrapes Netdata, node_exporter, snmp_exporter |
| `grafana` | `grafana/grafana` | 3000 | Dashboards (provisioned from files) |
| `node_exporter` | `prom/node-exporter` | 9100 | Host metrics — **caveat: reports Docker Desktop's internal Linux VM, not real macOS** |
| `snmp_exporter` | `prom/snmp-exporter` | 9116 | Standard IF-MIB metrics for the router via SNMPv2c |
| `loki` | `grafana/loki` | 3100 | Log storage for raw flow records |
| `promtail` | `grafana/promtail` | 9080 | Tails `flows.log`, ships to Loki |
| `influxdb` | `influxdb:2` | 8086 | Time-series store for per-flow records (bucket `netflow`, org `netmon`) |
| `telegraf` | `telegraf` | — | Tails `flows.log`, parses JSON, writes points to InfluxDB |
| `netflow2ng` | `synfinatic/netflow2ng` | 2056 (udp), 8091 | Receives NetFlow/IPFIX, republishes flows to ntopng over ZMQ |
| `ntopng` | `ntop/ntopng` | 3001 | Live traffic dashboard fed by netflow2ng; local networks: `10.9.1.0/24,192.168.3.0/24` |
| `redis-ntopng` | `redis:alpine` | — | Dedicated Redis instance for ntopng's cache/preferences |
| `influxdb-ntopng` | `influxdb:1.8` | 8087 | Dedicated InfluxDB 1.x instance for ntopng's Timeseries driver (db: `ntopng`). ntopng only supports InfluxDB 1.x, so it cannot share the v2 `influxdb` container above |

Three components run natively on the host (not in Docker), since they need direct macOS/network access:
- **Netdata** (Homebrew, `/opt/homebrew/etc/netdata/`) — real host metrics (CPU, RAM, disk, GPU, battery) plus the `go.d/snmp` collector polling the router.
- **goflow2** (`~/bin/goflow2`, managed via LaunchAgent `~/Library/LaunchAgents/com.netsampler.goflow2.plist`) — receives NetFlow/IPFIX on UDP `2055`, writes JSON records to `~/Library/Logs/goflow2/flows.log`, and exposes internal Prometheus metrics on `:8080`.
- **netflow-relay.py** (`scripts/netflow-relay.py`, managed via LaunchAgent `~/Library/LaunchAgents/com.netmon.netflow-relay.plist`) — receives the router's single NetFlow export on UDP `2057` and duplicates each packet to both goflow2 (`2055`) and netflow2ng (`2056`), since the router only supports one export target but two collectors need the data.

## Prerequisites

- Docker Desktop (context `desktop-linux`)
- Homebrew, with `netdata` installed and running (`brew services start netdata`)
- `goflow2` binary running as a LaunchAgent, listening on UDP `2055`
- `scripts/netflow-relay.py` running as a LaunchAgent, listening on UDP `2057`
- Router configured to export SNMP (v2c, community `public`) and NetFlow/IPFIX to this Mac's LAN IP on port `2057` (the relay, not directly to goflow2 or netflow2ng)

## Deployment

```zsh
cd ~/docker-monitoring
docker compose up -d
```

This brings up all 12 containers. Grafana auto-provisions its data sources and dashboards from files on every start — no manual UI setup is required.

### Installing the native NetFlow components (one-time)
`goflow2` and `netflow-relay.py` run natively on the host, not in Docker, since they need direct UDP socket access. Both are managed as LaunchAgents so they survive reboots.

**1. Install the goflow2 binary** (pre-built release, no Go toolchain required):
```zsh
mkdir -p ~/bin
curl -fsSL -o ~/bin/goflow2 \
  https://github.com/netsampler/goflow2/releases/download/v2.2.6/goflow2-2.2.6-darwin-amd64
chmod +x ~/bin/goflow2
```
Use the `darwin-arm64` asset instead on Apple Silicon Macs.

**2. Install both LaunchAgents:**
```zsh
mkdir -p ~/Library/Logs/goflow2 ~/Library/Logs/netflow-relay
cp launchagents/com.netsampler.goflow2.plist ~/Library/LaunchAgents/
cp launchagents/com.netmon.netflow-relay.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.netsampler.goflow2.plist
launchctl load ~/Library/LaunchAgents/com.netmon.netflow-relay.plist
```

**3. Verify the local pipeline** — this works even before the router is configured, using goflow2/netflow2ng's own Prometheus counters. A harmless non-flow test packet will always fail to decode, but the packet-received counter still proves the relay's fan-out reaches both collectors:
```zsh
launchctl list | grep -iE 'goflow2|netflow-relay'  # both should show a PID and exit status 0
lsof -nP -iUDP:2055,2057                           # goflow2 on 2055, python (relay) on 2057
curl -s http://localhost:8080/__health             # goflow2 health -> "OK"
echo probe | nc -u -w1 127.0.0.1 2057               # send a test datagram through the relay
curl -s http://localhost:8080/metrics | grep goflow2_flow_traffic_packets_total  # native goflow2 received it
curl -s http://localhost:8091/metrics | grep goflow2_flow_traffic_packets_total  # netflow2ng received it too
```
Both counters incrementing confirms the relay is correctly duplicating UDP traffic to both collectors, independent of whether the router is sending real flows yet.

### Configuring the UniFi Dream Router for NetFlow export
Point the router's NetFlow/IPFIX exporter at this Mac's **current LAN IP** on **port 2057** (the relay — never point it directly at `2055` or `2056`, since only one collector would then receive data).
1. Find this Mac's current LAN IP (it can change on DHCP renewal — see Known limitations):
   ```zsh
   ipconfig getifaddr en0 || ipconfig getifaddr en1
   ```
2. Check the UniFi Network app first: **Settings → Traffic & Device Identification** or **Settings → System → Advanced**. If a NetFlow/IPFIX toggle exists there for your firmware version, prefer it — UI-set config persists across firmware upgrades, unlike step 3.
3. If no UI option exists, SSH into the router and locate its flow-exporter config (path varies by UDR/UDM firmware, commonly under the `ubios-udapi-server` or `vnstatd` flow-export settings):
   ```zsh
   ssh root@10.9.1.1
   ```
4. Set the exporter's destination to `<mac-lan-ip>:2057`, protocol NetFlow v9 (or IPFIX if v9 isn't offered — this repo's dashboards and Promtail parsing assume the v9 field layout).
5. SSH-applied config on UniFi OS gateways is often **not persistent** across firmware upgrades/reboots unless set via the app UI or an `on_boot.d` script — re-check after any firmware update.
6. Confirm real flows are arriving:
   ```zsh
   tail -f ~/Library/Logs/goflow2/flows.log
   curl -s http://localhost:8091/metrics | grep goflow2_flow_traffic_packets_total
   ```
   The counter's `remote_ip` label should show the router's LAN IP (`10.9.1.1`) once it's exporting to the right target.

Access points:
- Grafana: http://localhost:3000 (`admin` / `admin` — change on first login)
  - Control Center dashboards: `/d/cc-system-health`, `/d/cc-network-router`, `/d/cc-netflow-analytics`, `/d/cc-live-flows`
- Prometheus: http://localhost:9090
- InfluxDB (v2, netflow) UI: http://localhost:8086
- InfluxDB (v1.8, ntopng): http://localhost:8087 (API only, no UI; unauthenticated)
- Netdata: http://localhost:19999
- ntopng: http://localhost:3001 (login disabled)
- netflow2ng metrics: http://localhost:8091/metrics

## Configuration reference

| File | Purpose |
|---|---|
| `docker-compose.yml` | All container definitions, networking, volumes |
| `prometheus/prometheus.yml` | Scrape jobs: `node_exporter`, `prometheus`, `netdata`, `netdata_snmp_gateway`, `snmp_exporter_gateway` |
| `promtail/promtail-config.yml` | Tails `flows.log`, extracts `type`/`proto` as labels and other fields (`src_addr`, `dst_addr`, ports, `in_if`/`out_if`) as parsed fields for LogQL |
| `telegraf/telegraf.conf` | Tails `flows.log` (poll mode — required for Docker Desktop bind mounts), writes tagged points to InfluxDB |
| `grafana/provisioning/datasources/datasources.yml` | Prometheus, Loki, InfluxDB (netflow, v2/Flux), InfluxDB (ntopng, v1/InfluxQL), Infinity (ntopng live REST API) data source definitions (fixed UIDs, referenced by dashboard JSON) |
| `grafana/provisioning/dashboards/dashboards.yml` | Points Grafana at `grafana/dashboards/` for auto-loading |
| `grafana/dashboards/*.json` | The 13 dashboards: 4 "Control Center" dashboards (primary) plus the 9 original single-source dashboards kept as legacy/backup (source of truth — edit these, not via UI, for changes to survive a volume wipe) |
| `scripts/netflow-relay.py` | UDP fan-out relay (LaunchAgent `com.netmon.netflow-relay.plist`) duplicating the router's single NetFlow export to both goflow2 and netflow2ng |
| `launchagents/com.netmon.netflow-relay.plist` | Version-controlled copy of the relay's LaunchAgent definition — copy to `~/Library/LaunchAgents/` and `launchctl load` it (see Deployment) |
| `launchagents/com.netsampler.goflow2.plist` | Version-controlled copy of goflow2's LaunchAgent definition — copy to `~/Library/LaunchAgents/` and `launchctl load` it (see Deployment) |
| `check-health.sh` | Post-reboot verification: containers, LaunchAgents, UDP listeners, HTTP endpoints, Prometheus targets, Grafana datasources, data freshness. Exit 0 = all healthy |

### Dashboards

**Control Center (primary):** four consolidated dashboards merging the legacy per-source dashboards, using modern visualizations (smooth gradient timeseries, gauges, bar gauges, donut charts, state timelines, node graph — no tables).

| Dashboard | Data sources | Content |
|---|---|---|
| Control Center · System Health | Prometheus (Netdata + node_exporter) | KPI gauges (CPU/RAM/disk/GPU/battery), stacked gradient CPU/RAM, load, swap, disk space/IO, en0 throughput, TCP packets, Docker VM row |
| Control Center · Network & Router | Prometheus (SNMP + goflow2-via-Netdata) | Router health stats, per-interface in/out gradient traffic, packets, errors/discards, interface oper-status state timeline, collector ingest/flowsets/templates/delay |
| Control Center · Flow Analytics | InfluxDB v2 (Flux) + Loki + InfluxDB ntopng (InfluxQL) | Hosts/flows KPIs, bytes by port, protocol donut, L4 bytes, top talkers bar gauge + gradient series, ASN/country traffic, interface pairs, TCP anomalies, engine load |
| Control Center · Live Flows | Infinity (ntopng REST) + Prometheus + Loki + InfluxDB ntopng | Live node graph of host-to-host flows (edge = active flow, labels = resolved names), top hosts by live throughput bar gauge, gradient ingest rate, live flow log stream |

**Legacy (kept as backup):**

| Dashboard | Data source | Content |
|---|---|---|
| Netdata Host Metrics (macOS) | Prometheus | CPU/RAM/Load quick overview |
| Netdata Full (macOS Host) | Prometheus | CPU, memory, swap, disk, network, GPU, battery |
| Node Exporter Full | Prometheus | Community dashboard (ID 1860) — reflects the Docker Desktop VM, not the real Mac |
| SNMP Exporter - Gateway | Prometheus | Standard IF-MIB metrics (`ifOperStatus`, `ifHCInOctets`, etc.) via `snmp_exporter` |
| NetFlow/IPFIX Live (Router) | Prometheus | Aggregate goflow2 counters re-exposed via Netdata's prometheus proxy |
| NetFlow Rich Detail | Loki | Per-flow LogQL time series grouped by port/IP/interface + raw log stream |
| NetFlow (InfluxDB) | InfluxDB (netflow, v2/Flux) | Proper time-series panels (bars/lines) grouped by port/IP/interface, backed by real point storage |
| ntopng - Flows, Hosts & Traffic (InfluxDB) | InfluxDB (ntopng, v1/InfluxQL) | Active/local host counts, active/new flows, bytes by L4 protocol, ASN, and country, TCP anomalies, ntopng CPU load |
| ntopng - Live Hosts (Names) | Infinity (ntopng REST API) | Table of currently active hosts with resolved names (e.g. `samsung-familyhub`, `mac.localdomain`), IP, bytes, flows, throughput — queries ntopng's live API directly since per-host data isn't in InfluxDB (see Known limitations) |

## Maintenance

### Updating a dashboard
Edit the corresponding file in `grafana/dashboards/`, then either wait up to 30s (`updateIntervalSeconds` in `dashboards.yml`) or restart Grafana:
```zsh
docker compose restart grafana
```
Avoid editing dashboards via the Grafana UI — changes made there are not saved back to these files and will be lost on a volume wipe unless exported and copied back manually.

### Adding a new Prometheus scrape target
Edit `prometheus/prometheus.yml`, then reload without a full restart:
```zsh
docker kill --signal=HUP prometheus
```

### Adding a new SNMP-monitored device
Add a job to `/opt/homebrew/etc/netdata/go.d/snmp.conf` (native Netdata) and/or a target in the `snmp_exporter_gateway` job in `prometheus/prometheus.yml`, then restart the relevant service (`brew services restart netdata`, or `docker kill --signal=HUP prometheus`).

### Full stack restart (proven persistent)
```zsh
docker compose down    # removes containers, keeps named volumes
docker compose up -d   # recreates everything from config files
```

### Verifying the stack after a reboot
Everything is configured to auto-start (containers via `restart: unless-stopped` once Docker Desktop launches; goflow2/netflow-relay via LaunchAgent `RunAtLoad`; Netdata via `brew services`). To verify all 30+ checks in one shot:
```zsh
./check-health.sh
```
It validates the Docker daemon and all 12 containers, the three native components, UDP listeners (2055/2057), every HTTP endpoint, Prometheus scrape targets, Grafana datasource health, and end-to-end data freshness in both NetFlow pipelines. Exits non-zero if anything fails, with a fix-hint per failed check.

### Configuring ntopng's Timeseries driver (InfluxDB)
By default ntopng stores historical timeseries locally as RRD files. This stack instead points it at the dedicated `influxdb-ntopng` container, via the web UI (Preferences → Timeseries): **Timeseries Driver**: `InfluxDB 1.x`, **InfluxDB URL**: `http://influxdb-ntopng:8086`, **InfluxDB Database**: `ntopng`, authentication disabled. Under the hood this sets two Redis keys read by `ts_utils_core.lua`/`influxdb.lua`:
- `ntopng.prefs.timeseries_driver` = `influxdb`
- `ntopng.prefs.ts_post_data_url` = `http://influxdb-ntopng:8086`

These preferences live in `redis-ntopng` (not a file in this repo), so they aren't provisioned automatically like Grafana's dashboards and must be re-applied if the `redis-ntopng` volume is ever wiped. ntopng caches its active timeseries driver in memory, so a container restart (`docker restart ntopng`) is needed after changing it for the change to take effect.

Verify ingestion with:
```zsh
docker exec influxdb-ntopng influx -database ntopng -execute "SHOW MEASUREMENTS"
docker exec influxdb-ntopng influx -database ntopng -execute 'SELECT * FROM "iface:local_hosts" ORDER BY time DESC LIMIT 3'
```
Confirmed working: ntopng auto-created its retention policies/continuous queries on first save ("InfluxDB CQ migration completed"), `influxdb-ntopng` logs show `POST /write` returning `204`, and measurements such as `iface:local_hosts`, `iface:hosts`, `iface:flows`, `asn:*`, `country:*`, and `system:cpu_load` contain real data points. This is now visualized in Grafana via the "ntopng - Flows, Hosts & Traffic (InfluxDB)" dashboard, backed by the `InfluxDB-ntopng` datasource (InfluxQL mode, `grafana/provisioning/datasources/datasources.yml`).

**Note:** these are interface-level aggregates only — no per-host series (e.g. `host:traffic`) have been observed in `influxdb-ntopng`, even with `ntopng.prefs.hosts_ts_creation=light` and `ntopng.prefs.is_local_host_cache_enabled=1` set. This may be a Community Edition limitation. For per-host visibility with resolved names, use the "ntopng - Live Hosts (Names)" dashboard instead (queries ntopng's live REST API directly, not InfluxDB).

### ntopng Live Hosts dashboard (Infinity datasource)
Since per-host InfluxDB timeseries aren't available (see above), the "ntopng - Live Hosts (Names)" dashboard uses the [Infinity datasource plugin](https://github.com/yesoreyeram/grafana-infinity-datasource) (`GF_INSTALL_PLUGINS` in `docker-compose.yml`) to query ntopng's REST API directly: `http://ntopng:3000/lua/rest/v2/get/host/active.lua`. This returns live host names resolved via mDNS/DHCP/reverse-DNS (e.g. `samsung-familyhub`, `iphone.localdomain`), not just IPs.

Key detail: Infinity query targets must include `"parser": "backend"` for the `columns` selector list to be applied — omitting it silently returns an empty result set with no error.

### Rebuilding Grafana from scratch (disaster recovery test)
```zsh
docker compose stop grafana
docker compose rm -f grafana
docker volume rm docker-monitoring_grafana_data
docker compose up -d grafana
```
Datasources and dashboards will re-provision automatically from the files in `grafana/`.

### Version control
This directory is a git repository. Commit any config changes:
```zsh
git add -A && git commit -m "describe the change"
```

## Known limitations

- **node_exporter metrics reflect Docker Desktop's LinuxKit VM**, not the real Mac (Docker containers can't access macOS `/proc`/`/sys`). Use the Netdata-backed dashboards for real host metrics.
- **ICMP ping sub-checks fail** in Netdata's SNMP collector logs (`operation not permitted`) — macOS restricts raw ICMP sockets for unprivileged processes. This only disables the optional ping-latency chart; SNMP metric collection is unaffected.
- **goflow2 counters reset on process restart** (LaunchAgent `KeepAlive` will restart it on crash). If flow dashboards suddenly go empty, check `~/Library/Logs/goflow2/stderr.log` and confirm the router is still sending flows to this Mac's current LAN IP (it can change on DHCP renewal).
- **Telegraf requires `watch_method = "poll"`** for the `inputs.tail` plugin — inotify events don't reliably cross the Docker Desktop macOS bind-mount bridge.
- **ntopng only supports InfluxDB 1.x**, not the 2.x API used by the main `influxdb` container. A separate `influxdb-ntopng` (1.8) container exists solely for ntopng's timeseries data — don't point ntopng at the v2 `influxdb` container directly.
- **ntopng's `--local-networks` only affects host classification** (local vs. remote), not which flows are received. If the router isn't exporting NetFlow for a given VLAN/subnet to netflow2ng's port, adding that subnet to `--local-networks` won't make its traffic appear.
- **ntopng preferences (Timeseries driver, local networks changes made via UI, etc.) live in `redis-ntopng`**, not in a file under this repo, so they are not version-controlled and won't survive `docker volume rm` on `redis-ntopng`'s data unless re-applied manually.
- **`--disable-login` requires an explicit mode argument (`0` or `1`)** in the `ntopng` command list in `docker-compose.yml`. Omitting it causes ntopng's argument parser to consume the *next* list item as the mode value instead — e.g. it previously swallowed `--local-networks` itself, silently discarding local-network classification (symptom: "No local hosts detected" despite active traffic) and leaving login enabled. Always keep `"1"` as its own list entry immediately after `"--disable-login"`.
- **The UniFi router's NetFlow exporter only supports a single destination IP:port.** With both goflow2 (`2055`) and netflow2ng (`2056`) needing the same flow data, the router is instead pointed at `scripts/netflow-relay.py` (port `2057`), which duplicates every datagram to both. If flows stop reaching one or both pipelines, check `launchctl list | grep netflow-relay` and the logs in `~/Library/Logs/netflow-relay/`.
- **The ntopng InfluxDB datasource uses InfluxQL (v1.x), not Flux** — unlike the main `InfluxDB-NetFlow` datasource. Dashboard panel queries use the classic `{"query": "SELECT ...", "rawQuery": true}` target format, not Flux syntax.
- **ntopng does not appear to write per-host InfluxDB timeseries** (e.g. `host:traffic`) even with `hosts_ts_creation=light` enabled — only interface-level aggregates (`iface:*`, `asn:*`, `country:*`) are written. Possibly a Community Edition restriction; unconfirmed. Use the Infinity-backed "ntopng - Live Hosts (Names)" dashboard for per-host visibility instead.
- **Infinity datasource queries require `"parser": "backend"`** in the target JSON, or the `columns` selectors silently produce an empty table with no error.
- **The Live Flows node graph can transiently warn about missing nodes** — its nodes (host/active) and edges (flow/active) come from two separate ntopng API calls, so a flow can briefly reference a host that just aged out of the host list. A refresh clears it.
