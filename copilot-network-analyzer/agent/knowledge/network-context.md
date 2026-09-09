# Network context

Upload as a knowledge file in Copilot Studio (agent → **Knowledge → Add
knowledge → Files**), so answers are grounded in how *this* network is built.
Edit the specifics before uploading — the values below describe the deployment
this project was scaffolded against.

## Topology

- Router/gateway: UniFi Dream Router, exporting NetFlow v9 / IPFIX.
- Local networks: `10.9.1.0/24` (primary LAN) and `192.168.3.0/24`.
- Flow collector: netflow2ng, which republishes flows to ntopng over ZMQ.
- ntopng runs at `10.9.1.241:3001` and is the source of every answer this agent
  gives.

## What the data is, and is not

- ntopng sees **flow records exported by the router**, not a full packet
  capture. Traffic that never crosses the router (two devices on the same VLAN
  talking directly, for instance) may not appear at all.
- Host names come from mDNS, DHCP and reverse DNS. An unnamed device shows its
  IP as its name — that is normal and does not indicate anything suspicious.
- "Active" means ntopng currently tracks the host or flow. Idle and powered-off
  devices are absent rather than reported as offline.
- Byte counters are cumulative since ntopng started tracking each host, not
  daily totals. Throughput figures are instantaneous.
- After the flow collector restarts, live data stays empty until the router
  re-sends its NetFlow templates, which can take 10–20 minutes. An empty
  network shortly after a restart usually means that, not an outage.

## Devices worth naming

Replace with your own; naming devices lets the agent answer "is the TV
streaming" without the user knowing its IP.

| Name in ntopng | What it is |
| --- | --- |
| `mac.localdomain` | Primary workstation |
| `samsung-familyhub` | Kitchen appliance, IoT VLAN |
| `iphone.localdomain` | Phone |

## Escalation

This agent is read-only. Blocking a device, changing firewall rules or altering
ntopng settings is done by hand in the UniFi console or ntopng at
`http://10.9.1.241:3001`.
