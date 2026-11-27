"""OAuth gate from ADR 015, section 7 / pedido 025. No network: GitHub is faked."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import io
import logging
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

from personal_brain.auth.app import build_authenticated_server, wrap_app
from personal_brain.auth.config import load_auth_config, missing_auth_settings
from personal_brain.auth.github import FakeGitHubIdentity
from personal_brain.auth.logging import LOGIN_OK
from personal_brain.auth.scopes import DOMAIN_SCOPES
from personal_brain.auth.security import digest, new_token
from personal_brain.auth.store import REUSE_GRACE_SECONDS, AuthStore
from personal_brain.cli import main
from personal_brain.logcheck import find_leaks, make_canaries
from personal_brain.server import create_server

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "records"
PUBLIC_URL = "https://brain.example.invalid"
RESOURCE = f"{PUBLIC_URL}/mcp"
ALLOWED_ID = 10000001
PEPPER = "test-pepper-value-not-used-in-production-xx"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def _env() -> dict[str, str]:
    return {
        "GITHUB_CLIENT_ID": "ov_example_client_id",
        "GITHUB_CLIENT_SECRET": "example-github-secret",
        "ALLOWED_GITHUB_USER_ID": str(ALLOWED_ID),
        "TOKEN_PEPPER": PEPPER,
    }


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _config(tmp_path: Path):
    return load_auth_config(public_url=PUBLIC_URL, auth_db=tmp_path / "auth.db", env=_env())


def _client_app(tmp_path: Path, db: Path, github: FakeGitHubIdentity | None = None, domains=None):
    config = _config(tmp_path)
    identity = github or FakeGitHubIdentity(ALLOWED_ID)
    server, provider = build_authenticated_server(db, config, domains, github=identity)
    app = wrap_app(server.streamable_http_app(), config.token_pepper)
    return TestClient(app, base_url=PUBLIC_URL), provider, identity, config


def _register_client(provider, redirect: str = REDIRECT, scopes=None) -> tuple[str, str]:
    scopes = list(scopes or DOMAIN_SCOPES.values())
    client_id = new_token()
    secret = new_token()
    provider.store.add_client(client_id, digest(PEPPER, secret), [redirect], scopes)
    return client_id, secret


def _authorize(http: TestClient, client_id: str, challenge: str, scopes: str, state: str = "client-state") -> str:
    response = http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
            "scope": scopes,
            "state": state,
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    location = response.headers["location"]
    return parse_qs(urlparse(location).query)["state"][0]



def _form_post(http: TestClient, path: str, data, **kwargs):
    """httpx 0.29 no longer sends TestClient(data=) as a form body."""
    if hasattr(data, "items"):
        items = list(data.items())
    else:
        items = list(data)
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    return http.post(path, content=urlencode(items).encode("ascii"), headers=headers, **kwargs)


def _consent(http: TestClient, provider, github_state: str, github_code: str = "gh-code-1", grant=None) -> str:
    callback = http.get(
        "/oauth/github/callback",
        params={"state": github_state, "code": github_code},
        follow_redirects=False,
    )
    assert callback.status_code == 200
    pending = provider.store.get_pending_by_state(github_state)
    assert pending is not None and pending.consent_csrf
    grant = grant if grant is not None else pending.scopes
    # starlette TestClient accepts a list for the same key via a list of tuples
    form = [("csrf", pending.consent_csrf)] + [("scope", s) for s in grant]
    granted = _form_post(http, f"/oauth/consent?request={pending.id}", form, follow_redirects=False)
    assert granted.status_code in (302, 303)
    location = granted.headers["location"]
    assert location.startswith(REDIRECT)
    params = parse_qs(urlparse(location).query)
    assert params.get("state") == ["client-state"]
    return params["code"][0]


def _token(http: TestClient, client_id: str, secret: str, code: str, verifier: str) -> dict:
    response = _form_post(
        http,
        "/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "client_secret": secret,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _full_login(http, provider, scopes: str | None = None) -> dict:
    client_id, secret = _register_client(provider)
    verifier, challenge = _pkce()
    scope = scopes or " ".join(DOMAIN_SCOPES.values())
    github_state = _authorize(http, client_id, challenge, scope)
    code = _consent(http, provider, github_state)
    tokens = _token(http, client_id, secret, code, verifier)
    tokens["client_id"] = client_id
    tokens["client_secret"] = secret
    return tokens


def test_request_without_token_returns_401_with_resource_metadata(tmp_path, db):
    http, _, _, _ = _client_app(tmp_path, db)
    response = http.post("/mcp", headers={"Content-Type": "application/json"}, json={})
    assert response.status_code == 401
    www = response.headers.get("www-authenticate", "")
    assert "resource_metadata=" in www
    assert "oauth-protected-resource" in www


def test_wrong_github_account_is_denied_even_if_login_could_match(tmp_path, db):
    github = FakeGitHubIdentity(user_id=99999999)
    http, provider, _, _ = _client_app(tmp_path, db, github=github)
    client_id, _secret = _register_client(provider)
    _verifier, challenge = _pkce()
    github_state = _authorize(http, client_id, challenge, "brain:training:read")
    denied = http.get(
        "/oauth/github/callback",
        params={"state": github_state, "code": "gh-other"},
    )
    assert denied.status_code == 403
    assert "Acesso negado" in denied.text
    assert "99999999" not in denied.text
    assert "gho_fake" not in denied.text


def test_wrong_expired_or_reused_state_is_refused(tmp_path, db):
    http, provider, _, _ = _client_app(tmp_path, db)
    client_id, _secret = _register_client(provider)
    _verifier, challenge = _pkce()
    github_state = _authorize(http, client_id, challenge, "brain:training:read")

    wrong = http.get("/oauth/github/callback", params={"state": "not-the-state", "code": "x"})
    assert wrong.status_code == 403
    assert "Acesso negado" in wrong.text

    pending = provider.store.get_pending_by_state(github_state)
    assert pending is not None
    # Expire the pending request.
    with closing(__import__("sqlite3").connect(provider.store.path)) as conn:
        conn.execute("UPDATE pending_requests SET created_at = 0 WHERE github_state = ?", (github_state,))
        conn.commit()
    expired = http.get("/oauth/github/callback", params={"state": github_state, "code": "x"})
    assert expired.status_code == 403

    # Fresh request, reuse the state.
    http2, provider2, _, _ = _client_app(tmp_path, db)
    # same auth.db, new app wrapping the same db
    client_id2, _ = _register_client(provider2)
    _v, ch = _pkce()
    state2 = _authorize(http2, client_id2, ch, "brain:training:read")
    first = http2.get("/oauth/github/callback", params={"state": state2, "code": "ok"})
    assert first.status_code == 200
    reused = http2.get("/oauth/github/callback", params={"state": state2, "code": "ok"})
    assert reused.status_code == 403


def test_token_for_another_resource_is_refused(tmp_path, db):
    http, provider, _, config = _client_app(tmp_path, db)
    tokens = _full_login(http, provider)
    # Rewrite the stored resource of this access token.
    token_digest = digest(PEPPER, tokens["access_token"])
    with closing(sqlite3.connect(config.auth_db)) as conn:
        conn.execute(
            "UPDATE access_tokens SET resource = ? WHERE token_digest = ?",
            ("https://other.example.invalid/mcp", token_digest),
        )
        conn.commit()
    response = http.post(
        "/mcp",
        headers={"Authorization": f"Bearer {tokens['access_token']}", "Content-Type": "application/json"},
        json={},
    )
    assert response.status_code in (401, 403)


def test_expired_token_is_refused(tmp_path, db):
    http, provider, _, config = _client_app(tmp_path, db)
    tokens = _full_login(http, provider)
    token_digest = digest(PEPPER, tokens["access_token"])
    with closing(sqlite3.connect(config.auth_db)) as conn:
        conn.execute(
            "UPDATE access_tokens SET expires_at = ? WHERE token_digest = ?",
            (int(time.time()) - 10, token_digest),
        )
        conn.commit()
    response = http.post(
        "/mcp",
        headers={"Authorization": f"Bearer {tokens['access_token']}", "Content-Type": "application/json"},
        json={},
    )
    assert response.status_code == 401


def test_refresh_reuse_grace_then_revokes_family(tmp_path, db):
    http, provider, _, config = _client_app(tmp_path, db)
    tokens = _full_login(http, provider)
    body = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": tokens["client_id"],
        "client_secret": tokens["client_secret"],
    }
    first = _form_post(http, "/token", body)
    assert first.status_code == 200, first.text
    pair = first.json()
    # Reuse inside the 60-second window returns the same new pair.
    second = _form_post(http, "/token", body)
    assert second.status_code == 200
    assert second.json()["access_token"] == pair["access_token"]
    assert second.json()["refresh_token"] == pair["refresh_token"]

    old_digest = digest(PEPPER, tokens["refresh_token"])
    with closing(sqlite3.connect(config.auth_db)) as conn:
        conn.execute(
            "UPDATE refresh_graces SET rotated_at = ? WHERE old_digest = ?",
            (int(time.time()) - (REUSE_GRACE_SECONDS + 5), old_digest),
        )
        conn.commit()
    third = _form_post(http, "/token", body)
    assert third.status_code == 400
    # The new pair is revoked with the family.
    reused_new = _form_post(
        http,
        "/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": pair["refresh_token"],
            "client_id": tokens["client_id"],
            "client_secret": tokens["client_secret"],
        },
    )
    assert reused_new.status_code == 400
    protected = http.post(
        "/mcp",
        headers={"Authorization": f"Bearer {pair['access_token']}", "Content-Type": "application/json"},
        json={},
    )
    assert protected.status_code == 401


def test_training_scope_does_not_see_health_records(tmp_path, db):
    # Scope narrowing uses the same filter as ADR 011; the token is injected
    # through the auth context the HTTP middleware would set.
    config = _config(tmp_path)
    github = FakeGitHubIdentity(ALLOWED_ID)
    server, _provider = build_authenticated_server(db, config, github=github)
    token = AccessToken(
        token="unused",
        client_id="client",
        scopes=["brain:training:read"],
        expires_at=int(time.time()) + 3600,
        resource=RESOURCE,
        subject=str(ALLOWED_ID),
    )
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        found = str(asyncio.run(server.call_tool("search", {"query": "fictional", "limit": 20})))
        assert "train-method-progressive-overload" in found
        health = str(asyncio.run(server.call_tool("read_entry", {"id": "exam-2026-04-02-blood"})))
        missing = str(asyncio.run(server.call_tool("read_entry", {"id": "does-not-exist"})))
        assert "not_found" in health
        assert health == missing
    finally:
        auth_context_var.reset(reset)


def test_redirect_uri_other_than_registered_is_refused(tmp_path, db):
    http, provider, _, _ = _client_app(tmp_path, db)
    client_id, _secret = _register_client(provider)
    _verifier, challenge = _pkce()
    response = http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://attacker.example.invalid/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "https://attacker.example.invalid" not in (response.headers.get("location") or "")


def test_unknown_client_id_is_refused(tmp_path, db):
    http, _, _, _ = _client_app(tmp_path, db)
    _verifier, challenge = _pkce()
    response = http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "does-not-exist",
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        },
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_register_endpoint_does_not_exist(tmp_path, db):
    http, _, _, _ = _client_app(tmp_path, db)
    response = http.post("/register", json={"redirect_uris": [REDIRECT]})
    assert response.status_code == 404
    metadata = http.get("/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    body = metadata.json()
    assert "registration_endpoint" not in body
    assert body.get("client_id_metadata_document_supported") in (None, False)


def test_auth_refuses_to_start_when_settings_are_missing(tmp_path, db):
    missing = missing_auth_settings(public_url=None, auth_db=None, env={})
    assert "GITHUB_CLIENT_ID" in missing
    assert "GITHUB_CLIENT_SECRET" in missing
    assert "ALLOWED_GITHUB_USER_ID" in missing
    assert "TOKEN_PEPPER" in missing
    assert "--public-url" in missing
    assert "--auth-db" in missing
    code = main(
        [
            "serve",
            "--transport",
            "http",
            "--db",
            str(db),
            "--auth",
        ]
    )
    assert code == 1


def test_check_deploy_script_catches_proxy_labels_on_private_service(tmp_path):
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "check-deploy.py"
    spec = importlib.util.spec_from_file_location("check_deploy", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["check_deploy"] = module
    spec.loader.exec_module(module)

    example = root / "docker-compose.example.yml"
    assert module.main([str(example)]) == 0

    bad = tmp_path / "bad.yml"
    text = example.read_text(encoding="utf-8")
    # Give the private service a Traefik label.
    text = text.replace(
        "    restart: unless-stopped\n\n  brain-public:",
        "    labels:\n      - traefik.enable=true\n    restart: unless-stopped\n\n  brain-public:",
        1,
    )
    bad.write_text(text, encoding="utf-8")
    assert module.main([str(bad)]) == 1


def test_log_check_passes_after_full_auth_flow(tmp_path, db):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    logger = logging.getLogger("personal_brain.auth")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        http, provider, identity, _ = _client_app(tmp_path, db)
        canaries = make_canaries(prefix="authcanary")
        tokens = _full_login(http, provider)
        metadata = http.get("/.well-known/oauth-authorization-server")
        assert metadata.status_code == 200
        # Drive the same canary paths as send_auth_canaries, through the in-process
        # app. The fictional public hostname must not be resolved on the network.
        http.get("/oauth/github/callback", params={"state": canaries[0], "code": canaries[1]})
        _form_post(
            http,
            "/token",
            {
                "grant_type": "authorization_code",
                "code": canaries[1],
                "client_id": canaries[2],
                "code_verifier": "a" * 43,
                "redirect_uri": REDIRECT,
            },
        )
        logs = stream.getvalue()
        # Event names are allowed.
        assert LOGIN_OK.split()[0] in logs or LOGIN_OK in logs or "auth.login" in logs
        leaks = find_leaks(logs, canaries + [tokens["access_token"], tokens["refresh_token"], "gho_fake"])
        assert leaks == []
        # GitHub token was used and not kept on the provider beyond the fake's audit list
        # (the production path discards it immediately). The fake only records the value
        # so the test can assert the real logs never got it.
        assert identity.discarded_tokens
        for value in identity.discarded_tokens:
            assert value not in logs
    finally:
        logger.removeHandler(handler)


def test_private_mode_is_unchanged_without_auth_flag(db):
    server = create_server(db)
    found = str(asyncio.run(server.call_tool("search", {"query": "blood"})))
    assert "exam-2026-04-02-blood" in found


def test_create_client_and_revoke_all(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TOKEN_PEPPER", PEPPER)
    auth_db = tmp_path / "auth.db"
    code = main(
        [
            "auth",
            "create-client",
            "--auth-db",
            str(auth_db),
            "--redirect-uri",
            REDIRECT,
            "--max-scopes",
            "brain:health:read,brain:training:read",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "client_id:" in out
    assert "client_secret:" in out
    secret_line = next(line for line in out.splitlines() if line.startswith("client_secret:"))
    secret = secret_line.split(":", 1)[1].strip()
    store = AuthStore(auth_db)
    client_id = next(line for line in out.splitlines() if line.startswith("client_id:")).split(":", 1)[1].strip()
    row = store.get_client(client_id)
    assert row is not None
    assert row.secret_digest == digest(PEPPER, secret)
    assert secret not in (auth_db.read_bytes().decode("latin-1", errors="ignore"))

    assert main(["auth", "revoke-all", "--auth-db", str(auth_db)]) == 0
