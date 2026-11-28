#!/usr/bin/env python3
"""Fail if the Brain deploy layout is wrong for the chosen stage.

Stages:
  private-only  Stage A. No Brain service (brain-*) may have proxy labels.
  public        Default. brain-public needs proxy labels and --auth; brain-private
                must not have proxy labels.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: PyYAML is required", file=sys.stderr)
    sys.exit(2)

PROXY_HINTS = ("traefik.", "caddy.", "coolify.proxy")
PRIVATE_SERVICE = "brain-private"
PUBLIC_SERVICE = "brain-public"
BRAIN_PREFIX = "brain-"
STAGES = ("private-only", "public")


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _command(service: dict) -> str:
    parts = _as_list(service.get("command")) + _as_list(service.get("entrypoint"))
    # docker compose may use a string or a list
    raw = service.get("command")
    if isinstance(raw, list):
        return " ".join(str(p) for p in raw)
    if isinstance(raw, str):
        return raw
    return " ".join(parts)


def _labels(service: dict) -> list[str]:
    labels = service.get("labels") or []
    if isinstance(labels, dict):
        return [f"{k}={v}" for k, v in labels.items()]
    return [str(item) for item in labels]


def _has_proxy_labels(service: dict) -> bool:
    text = " ".join(_labels(service)).lower()
    return any(hint in text for hint in PROXY_HINTS)


def check_private_only(compose: dict) -> list[str]:
    services = compose.get("services") or {}
    errors: list[str] = []
    if PRIVATE_SERVICE not in services:
        errors.append(f"missing service: {PRIVATE_SERVICE}")
    for name, service in services.items():
        if name.startswith(BRAIN_PREFIX) and _has_proxy_labels(service or {}):
            errors.append(f"{name} must not have proxy labels in stage private-only")
    return errors


def check(compose: dict, stage: str = "public") -> list[str]:
    if stage == "private-only":
        return check_private_only(compose)
    if stage != "public":
        raise ValueError(f"unknown stage: {stage}")
    services = compose.get("services") or {}
    errors: list[str] = []
    if PRIVATE_SERVICE not in services:
        errors.append(f"missing service: {PRIVATE_SERVICE}")
    else:
        if _has_proxy_labels(services[PRIVATE_SERVICE]):
            errors.append(f"{PRIVATE_SERVICE} must not have proxy labels")
    if PUBLIC_SERVICE not in services:
        errors.append(f"missing service: {PUBLIC_SERVICE}")
    else:
        public = services[PUBLIC_SERVICE]
        if "--auth" not in _command(public):
            errors.append(f"{PUBLIC_SERVICE} must run with --auth")
        if not _has_proxy_labels(public):
            errors.append(f"{PUBLIC_SERVICE} must have proxy labels")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check-deploy")
    parser.add_argument(
        "compose_file",
        nargs="?",
        type=Path,
        default=Path("docker-compose.example.yml"),
    )
    parser.add_argument(
        "--stage",
        choices=STAGES,
        default="public",
        help="private-only: no Brain service on the proxy; public: brain-public on the proxy with --auth",
    )
    args = parser.parse_args(argv)
    compose = yaml.safe_load(args.compose_file.read_text(encoding="utf-8"))
    errors = check(compose, args.stage)
    if errors:
        for item in errors:
            print(f"FAIL: {item}", file=sys.stderr)
        return 1
    print(f"PASS: deploy layout looks correct (stage {args.stage})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
