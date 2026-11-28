"""CLI: create a pre-registered client and the panic-button revocation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scopes import ALL_SCOPES
from .security import digest, new_token
from .store import AuthStore


def add_auth_parser(sub: argparse._SubParsersAction) -> None:
    auth = sub.add_parser("auth", help="manage the authorization server (public mode)")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)

    create = auth_sub.add_parser("create-client", help="register a confidential client and show its secret once")
    create.add_argument("--auth-db", type=Path, required=True)
    create.add_argument("--redirect-uri", required=True)
    create.add_argument(
        "--max-scopes",
        default=",".join(ALL_SCOPES),
        help="comma-separated scopes this client may request",
    )

    revoke = auth_sub.add_parser("revoke-all", help="sign out every client (panic button)")
    revoke.add_argument("--auth-db", type=Path, required=True)


def run_auth_command(args: argparse.Namespace, environ: dict[str, str] | None = None) -> int:
    import os

    env = os.environ if environ is None else environ
    pepper = (env.get("TOKEN_PEPPER") or "").strip()
    if not pepper:
        print("error: TOKEN_PEPPER is required", file=sys.stderr)
        return 1

    store = AuthStore(args.auth_db)
    if args.auth_command == "create-client":
        scopes = [s.strip() for s in args.max_scopes.split(",") if s.strip()]
        unknown = [s for s in scopes if s not in ALL_SCOPES]
        if unknown:
            print(f"error: unknown scope(s): {', '.join(unknown)}", file=sys.stderr)
            return 1
        client_id = new_token()
        secret = new_token()
        store.add_client(client_id, digest(pepper, secret), [args.redirect_uri], scopes)
        print(f"client_id: {client_id}")
        print(f"client_secret: {secret}")
        print("Store the secret now; it will not be shown again.", file=sys.stderr)
        return 0

    if args.auth_command == "revoke-all":
        store.revoke_all_tokens()
        print("revoked all tokens, codes and pending logins", file=sys.stderr)
        return 0

    return 1
