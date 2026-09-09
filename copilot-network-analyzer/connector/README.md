# Power Platform custom connector

`apiDefinition.swagger.json` is **generated**, not hand-edited. Regenerate it
whenever the gateway's routes or models change:

```bash
python scripts/build_connector.py --host ntopng-gw.example.com
```

`--host` is the public hostname Copilot Studio calls — the tunnel or reverse
proxy in front of the gateway, never `10.9.1.241`, which Microsoft's cloud
cannot resolve.

## Import options

**Portal (simplest).** Power Apps → *More* → *Discover all* → *Custom
connectors* → *New custom connector* → *Import an OpenAPI file*, then pick this
file. On the Security tab choose *API Key*, parameter label `Gateway API key`,
parameter name `X-API-Key`, location `Header`. Test an operation, then create
the connection with the key from `GATEWAY_API_KEYS`.

**CLI (repeatable).** With [`paconn`](https://learn.microsoft.com/connectors/custom-connectors/paconn-cli):

```bash
pip install paconn
paconn login
paconn create --api-def apiDefinition.swagger.json --api-prop apiProperties.json --icon icon.png
```

`paconn create` fills in `connectorId` and `environment` in `settings.json`;
after that, `paconn update -s settings.json` pushes later changes.

## icon.png

Not included — Power Platform wants a 1:1 PNG under 1 MB (100×100 works).
Supply any icon; the portal import path will also accept the default.
