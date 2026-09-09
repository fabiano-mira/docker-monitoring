#!/usr/bin/env python3
"""Generate the Power Platform custom connector definition from the gateway.

Power Platform custom connectors (and therefore Copilot Studio actions) still
require OpenAPI 2.0, while FastAPI emits 3.1 — so rather than hand-maintaining
a second spec that silently drifts from the code, this downgrades the live one
and adds the x-ms-* annotations Copilot Studio uses to label actions and
parameters in its UI.

Usage:
    python scripts/build_connector.py --host ntopng-gw.example.com
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gateway"))

from app.main import app  # noqa: E402  (needs the path set above)

SCALARS = {"string", "integer", "number", "boolean", "array", "object"}


def flatten(schema: dict[str, Any]) -> dict[str, Any]:
    """Collapse OpenAPI 3.1 constructs Power Platform's 2.0 parser rejects.

    Pydantic writes optional fields as anyOf[{type}, {type: "null"}] and 3.1
    allows type arrays; both become a single nullable 2.0 type here.
    """
    if not isinstance(schema, dict):
        return schema

    if "anyOf" in schema or "oneOf" in schema:
        variants = [v for v in schema.get("anyOf", schema.get("oneOf", [])) if v.get("type") != "null"]
        merged = flatten(variants[0]) if variants else {"type": "string"}
        for key in ("title", "description", "default", "example"):
            if key in schema:
                merged.setdefault(key, schema[key])
        merged["x-nullable"] = True
        return merged

    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in ("examples", "const", "$comment"):
            continue
        if key == "$ref":
            result[key] = value.replace("#/components/schemas/", "#/definitions/")
        elif key == "type" and isinstance(value, list):
            types = [item for item in value if item != "null"]
            result["type"] = types[0] if types else "string"
            if len(types) < len(value):
                result["x-nullable"] = True
        elif key in ("properties", "definitions"):
            result[key] = {name: flatten(sub) for name, sub in value.items()}
        elif key == "items":
            result[key] = flatten(value)
        elif isinstance(value, dict):
            result[key] = flatten(value)
        else:
            result[key] = value

    if result.get("type") not in SCALARS and "$ref" not in result and "type" in result:
        result["type"] = "string"
    return result


def convert(openapi: dict[str, Any], host: str, scheme: str) -> dict[str, Any]:
    info = openapi["info"]
    swagger: dict[str, Any] = {
        "swagger": "2.0",
        "info": {
            "title": info["title"],
            "description": info.get("description", ""),
            "version": info.get("version", "1.0.0"),
        },
        "host": host,
        "basePath": "/",
        "schemes": [scheme],
        "consumes": [],
        "produces": ["application/json"],
        "paths": {},
        "definitions": {
            name: flatten(schema)
            for name, schema in openapi.get("components", {}).get("schemas", {}).items()
        },
        "securityDefinitions": {
            "api_key": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        },
        "security": [{"api_key": []}],
    }

    for path, methods in openapi["paths"].items():
        entry: dict[str, Any] = {}
        for method, operation in methods.items():
            if method not in ("get", "post"):
                continue
            parameters = []
            for parameter in operation.get("parameters", []):
                schema = flatten(parameter.get("schema", {}))
                converted = {
                    "name": parameter["name"],
                    "in": parameter["in"],
                    "required": parameter.get("required", False),
                    "description": parameter.get("description") or schema.get("description", ""),
                    # Copilot Studio shows x-ms-summary as the parameter's label.
                    "x-ms-summary": parameter["name"].replace("_", " ").title(),
                    "type": schema.get("type", "string"),
                }
                for key in ("default", "enum", "format", "minimum", "maximum", "pattern"):
                    if key in schema:
                        converted[key] = schema[key]
                parameters.append(converted)

            success = operation.get("responses", {}).get("200", {})
            response_schema = flatten(
                success.get("content", {}).get("application/json", {}).get("schema", {})
            )
            entry[method] = {
                "operationId": operation.get("operationId", ""),
                "summary": operation.get("summary", ""),
                "description": operation.get("description", ""),
                # Everything here is read-only, so nothing needs confirmation.
                "x-ms-visibility": "important",
                "parameters": parameters,
                "responses": {
                    "200": {"description": success.get("description", "Success"), "schema": response_schema},
                    "401": {"description": "Missing or invalid API key."},
                    "502": {"description": "ntopng returned an error."},
                    "503": {"description": "ntopng is unreachable."},
                },
            }
        if entry:
            swagger["paths"][path] = entry

    return swagger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default="REPLACE-WITH-YOUR-PUBLIC-HOSTNAME",
        help="Public hostname Copilot Studio will call, without scheme or path.",
    )
    parser.add_argument("--scheme", default="https", choices=["https", "http"])
    parser.add_argument("--out", default=str(ROOT / "connector" / "apiDefinition.swagger.json"))
    args = parser.parse_args()

    swagger = convert(app.openapi(), args.host, args.scheme)
    Path(args.out).write_text(json.dumps(swagger, indent=2) + "\n")
    print(f"wrote {args.out} ({len(swagger['paths'])} paths, host={args.host})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
