# Copilot Studio Network Analyzer (ntopng)

A Microsoft Copilot Studio agent that answers questions about a live network —
"who's using the bandwidth", "what is my Mac talking to", "anything unusual
overnight" — backed by ntopng at **http://10.9.1.241:3001**.

This is a **scaffold**: the gateway, connector and agent definitions are
complete and tested, but the ntopng-specific endpoints beyond the core four are
best-effort across ntopng versions and should be verified against your box with
`scripts/probe-ntopng.sh` before you rely on them.

```
Copilot Studio agent
        │  actions
        ▼
Power Platform custom connector  (connector/apiDefinition.swagger.json)
        │  HTTPS + X-API-Key
        ▼
Public hostname (Cloudflare Tunnel / reverse proxy)
        │
        ▼
Gateway — FastAPI, read-only        (gateway/)
        │  ntopng REST v2
        ▼
ntopng  http://10.9.1.241:3001
```

## Why a gateway rather than pointing the connector at ntopng

Three reasons, all of which bite immediately otherwise:

1. **Reachability.** `10.9.1.241` is RFC1918. Copilot Studio runs in Microsoft's
   cloud and cannot route to it, so *something* has to face the internet. Better
   that it is a small read-only service than ntopng's full admin UI.
2. **Shape.** ntopng answers with `{"rc":0,"rsp":{"data":[…]}}` and nested,
   abbreviated fields (`thpt.bps`, `num_flows.total`). Agents reason poorly over
   that and truncate large payloads. The gateway returns flat records, plain
   field names, and a human-readable `summary` string per response.
3. **Blast radius.** ntopng's API can change settings. The gateway exposes eight
   `GET` operations and nothing else, behind its own API key.

## Layout

| Path | What it is |
| --- | --- |
| `gateway/` | FastAPI service: ntopng client, mappers, routes, tests |
| `connector/` | Power Platform custom connector (generated Swagger 2.0 + metadata) |
| `agent/` | Agent instructions, conversation starters, topic YAML, knowledge file |
| `scripts/build_connector.py` | Regenerates the connector from the live OpenAPI |
| `scripts/probe-ntopng.sh` | Checks which ntopng REST endpoints your build serves |
| `scripts/smoke-test.sh` | Calls every gateway operation end to end |
| `docker-compose.yml` | Gateway + optional Cloudflare Tunnel |

## Actions the agent gets

| Operation | Path | Answers |
| --- | --- | --- |
| `GetNetworkSummary` | `/v1/summary` | "How's the network?" — hosts, flows, throughput, top talkers, top protocols in one call |
| `GetTopTalkers` | `/v1/hosts/top` | "Who's using the bandwidth?" (by throughput or bytes; local/remote/all) |
| `FindHost` | `/v1/hosts/search` | "Is the TV online?" — substring match on name or IP |
| `GetActiveFlows` | `/v1/flows/active` | "Who is X talking to?" (filter by host or protocol) |
| `GetTopProtocols` | `/v1/protocols/top` | "How much of this is streaming?" |
| `GetRecentAlerts` | `/v1/alerts/recent` | "Anything wrong overnight?" |
| `ListInterfaces` | `/v1/interfaces` | Interface ids for the other calls |
| `GetHealth` | `/v1/health` | Is ntopng reachable at all? |

## Setup

### 1. Run the gateway

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # → GATEWAY_API_KEYS
$EDITOR .env
docker compose up -d --build
```

Then confirm it reads your ntopng:

```bash
GATEWAY_API_KEY=<the key you generated> ./scripts/smoke-test.sh
```

Every line should read `ok`. If `GetTopProtocols` or `GetRecentAlerts` fail, run
`./scripts/probe-ntopng.sh` — your ntopng build may not serve those endpoints
(Community Edition often does not expose alerts), which the agent handles but
you should know about.

To develop without Docker: `make setup && make test && make run`.

### 2. Expose it to Copilot Studio

The gateway must answer on a public HTTPS hostname. Options, easiest first:

- **Cloudflare Tunnel** (in the compose file). Create a tunnel in Cloudflare
  Zero Trust, point its public hostname at `http://gateway:8000`, put the token
  in `.env`, then `docker compose --profile tunnel up -d`. Outbound-only — no
  port forwarding, no inbound firewall rule.
- **Existing reverse proxy** (Caddy, nginx, Traefik) with a real certificate,
  forwarding to `127.0.0.1:8800`.
- **On-premises data gateway.** Power Platform supports it for custom
  connectors, and it avoids exposing anything publicly, but it is more setup and
  its Copilot Studio support is narrower than Power Automate's. Worth it if
  policy forbids a tunnel.

Whatever you choose, keep `GATEWAY_API_KEYS` set. A public URL with auth
disabled publishes your network's traffic map to anyone who finds it.

### 3. Import the connector

```bash
python scripts/build_connector.py --host ntopng-gw.example.com
```

Then import `connector/apiDefinition.swagger.json` in Power Apps → Custom
connectors, set security to **API Key**, header `X-API-Key`, and create a
connection with your key. Full instructions, including the `paconn` CLI path,
are in `connector/README.md`.

### 4. Build the agent

In Copilot Studio, create an agent named *Network Analyzer*, then:

1. **Instructions** — paste `agent/instructions.md`. This is what makes the
   agent pick the right action and refuse to guess; don't skip it.
2. **Actions** — add your custom connector, enable all eight operations, and
   pick the connection you created.
3. **Knowledge** — upload `agent/knowledge/network-context.md` after editing it
   to match your subnets and device names. Turn off general web knowledge unless
   you want the model answering networking questions from the open internet.
4. **Conversation starters** — from `agent/conversation-starters.md`.
5. **Topics** (optional) — `agent/topics/*.yaml` fix the wording and parameters
   for two common questions. A generative agent answers both without them; the
   `network-health` topic is still worth adding, because it guarantees a clear
   "monitoring is down" answer instead of a vague one when ntopng is unreachable.

Test in the pane on the right with "How is my network doing right now?" before
publishing.

## Design notes

- **Read-only by construction.** Only `GET` routes exist; the client has no
  write methods. The agent instructions tell it to say so when asked to block or
  reconfigure something.
- **Every response carries a `summary`.** The agent leads with it, which keeps
  answers grounded in returned data rather than paraphrased from raw numbers.
- **Missing endpoints are reported, not silently empty.** `GetRecentAlerts`
  returns `supported: false` when ntopng has no alerts API, and the instructions
  forbid reading that as "no alerts" — the difference between "nothing is wrong"
  and "I can't see whether anything is wrong" matters here.
- **Field names are read defensively.** `mappers.py` accepts each field's known
  aliases (`bytes.recvd` / `bytes.rcvd`, `client.ip` / `cli.ip`) because they
  differ across ntopng versions. The primary paths are the ones this deployment's
  Grafana panels already read successfully.
- **The connector is generated.** `apiDefinition.swagger.json` is derived from
  the FastAPI app, so the connector cannot drift from the code. Re-run
  `scripts/build_connector.py` after changing routes or models.

## Verification status

- `make test` — 10 tests, passing, against a stub ntopng that mirrors real
  response shapes.
- Connector generation — verified: 8 paths, valid Swagger 2.0, no OpenAPI 3.x
  constructs left behind.
- Gateway boot — verified: API-key rejection, the degraded `GetHealth` response,
  and the 503-with-detail path when ntopng is unreachable all behave correctly.
- Docker image — **not built here** (no Docker daemon in the scaffolding
  session). `docker compose up -d --build` is the first thing to try.
- **Not verified against live ntopng.** This was scaffolded from a cloud session
  with no route to `10.9.1.241`. The host and flow endpoints match what your
  Grafana dashboards already query successfully; the L7-stats and alert
  endpoints are from ntopng's documented REST surface and are the ones most
  likely to need adjustment. `scripts/probe-ntopng.sh` tells you in one run.

## Relationship to the parent repo

Self-contained and independent. It reads ntopng over HTTP and touches nothing in
the monitoring stack — no shared compose file, no shared volumes. Run it on the
same host or anywhere with a route to `NTOPNG_URL`.
