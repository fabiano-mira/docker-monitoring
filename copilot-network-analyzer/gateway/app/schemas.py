"""Response models.

These are the shapes Copilot Studio sees, so they are deliberately flat,
named in plain language, and small: an agent reasons badly over nested
ntopng records and truncates long payloads. Every model carries a
human-readable `summary` the agent can quote directly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Host(BaseModel):
    ip: str = Field(description="IP address of the host.")
    name: str = Field(description="Resolved name (mDNS/DHCP/reverse DNS), or the IP when unresolved.")
    is_local: bool = Field(description="True when the host is inside a configured local network.")
    country: str | None = Field(default=None, description="Two-letter country code for remote hosts.")
    throughput_bps: float = Field(description="Current throughput in bits per second.")
    bytes_total: int = Field(description="Total bytes seen for this host since ntopng started tracking it.")
    bytes_sent: int = Field(description="Bytes sent by the host.")
    bytes_received: int = Field(description="Bytes received by the host.")
    active_flows: int = Field(description="Number of currently active flows involving the host.")
    last_seen: int | None = Field(default=None, description="Unix timestamp of the last packet seen.")


class HostList(BaseModel):
    summary: str = Field(description="One-sentence, human-readable summary of the result.")
    interface_id: int = Field(description="ntopng interface the data came from.")
    count: int = Field(description="Number of hosts returned.")
    hosts: list[Host] = Field(description="The hosts, ordered as requested.")


class Flow(BaseModel):
    client_ip: str = Field(description="IP address of the client side of the flow.")
    client_name: str | None = Field(default=None, description="Resolved name of the client, when known.")
    server_ip: str = Field(description="IP address of the server side of the flow.")
    server_name: str | None = Field(default=None, description="Resolved name of the server, when known.")
    server_port: int | None = Field(default=None, description="Destination (server) port.")
    l7_protocol: str | None = Field(default=None, description="Application protocol detected by nDPI, e.g. HTTPS, DNS, Netflix.")
    l4_protocol: str | None = Field(default=None, description="Transport protocol, e.g. TCP or UDP.")
    bytes_total: int = Field(description="Bytes exchanged on this flow so far.")
    throughput_bps: float = Field(default=0, description="Current throughput of the flow in bits per second.")


class FlowList(BaseModel):
    summary: str = Field(description="One-sentence, human-readable summary of the result.")
    interface_id: int = Field(description="ntopng interface the data came from.")
    count: int = Field(description="Number of flows returned.")
    flows: list[Flow] = Field(description="The active flows, largest first.")


class Protocol(BaseModel):
    name: str = Field(description="Application protocol name as detected by nDPI.")
    bytes_total: int = Field(description="Bytes attributed to this protocol.")
    share_percent: float = Field(description="Share of total traffic, in percent.")


class ProtocolList(BaseModel):
    summary: str = Field(description="One-sentence, human-readable summary of the result.")
    interface_id: int = Field(description="ntopng interface the data came from.")
    protocols: list[Protocol] = Field(description="Protocols, heaviest first.")


class Alert(BaseModel):
    time: int | None = Field(default=None, description="Unix timestamp when the alert fired.")
    severity: str | None = Field(default=None, description="Alert severity, e.g. info, warning, error.")
    alert_type: str | None = Field(default=None, description="Alert type as named by ntopng.")
    entity: str | None = Field(default=None, description="Host or entity the alert is about.")
    message: str | None = Field(default=None, description="Human-readable alert text.")


class AlertList(BaseModel):
    summary: str = Field(description="One-sentence, human-readable summary of the result.")
    supported: bool = Field(description="False when this ntopng build does not expose the alerts API.")
    count: int = Field(description="Number of alerts returned.")
    alerts: list[Alert] = Field(description="Recent alerts, newest first.")


class NetworkSummary(BaseModel):
    summary: str = Field(description="One-paragraph, human-readable state of the network. Safe to quote verbatim.")
    interface_name: str | None = Field(default=None, description="Name of the monitored ntopng interface.")
    active_hosts: int = Field(description="Number of hosts currently active.")
    local_hosts: int = Field(description="Number of active hosts inside the local networks.")
    active_flows: int = Field(description="Number of currently active flows.")
    throughput_bps: float = Field(description="Aggregate current throughput in bits per second.")
    top_talkers: list[Host] = Field(description="Busiest hosts right now, by throughput.")
    top_protocols: list[Protocol] = Field(description="Heaviest application protocols right now.")


class Interface(BaseModel):
    id: int = Field(description="ntopng interface id, passed as interface_id to other operations.")
    name: str = Field(description="Interface name as configured in ntopng.")


class InterfaceList(BaseModel):
    summary: str = Field(description="One-sentence, human-readable summary of the result.")
    interfaces: list[Interface] = Field(description="Interfaces ntopng is monitoring.")


class Health(BaseModel):
    status: str = Field(description="ok when ntopng answered, degraded when it did not.")
    gateway_version: str = Field(description="Version of this gateway.")
    ntopng_url: str = Field(description="ntopng base URL this gateway is pointed at.")
    ntopng_reachable: bool = Field(description="Whether ntopng answered its interfaces endpoint.")
    detail: str | None = Field(default=None, description="Error detail when ntopng is not reachable.")
