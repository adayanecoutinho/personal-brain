"""SQLite token and client store (auth.db). Connections are closed with contextlib.closing."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

CLIENT_IDLE_SECONDS = 90 * 24 * 60 * 60
PENDING_TTL_SECONDS = 10 * 60
AUTH_CODE_TTL_SECONDS = 10 * 60
ACCESS_TTL_SECONDS = 60 * 60
REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60
REUSE_GRACE_SECONDS = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    secret_digest TEXT NOT NULL,
    redirect_uris TEXT NOT NULL,
    max_scopes TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_requests (
    id TEXT PRIMARY KEY,
    github_state TEXT NOT NULL UNIQUE,
    client_id TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    redirect_uri_provided_explicitly INTEGER NOT NULL,
    resource TEXT,
    scopes TEXT NOT NULL,
    client_state TEXT,
    created_at INTEGER NOT NULL,
    state_used INTEGER NOT NULL DEFAULT 0,
    github_ok INTEGER NOT NULL DEFAULT 0,
    consent_csrf TEXT,
    subject TEXT
);
CREATE TABLE IF NOT EXISTS authorization_codes (
    code_digest TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    code_challenge TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    redirect_uri_provided_explicitly INTEGER NOT NULL,
    resource TEXT,
    subject TEXT,
    consumed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS access_tokens (
    token_digest TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    resource TEXT,
    subject TEXT,
    family_id TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_digest TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    resource TEXT,
    subject TEXT,
    family_id TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    rotated_at INTEGER
);
CREATE TABLE IF NOT EXISTS refresh_graces (
    old_digest TEXT PRIMARY KEY,
    family_id TEXT NOT NULL,
    new_access_token TEXT NOT NULL,
    new_refresh_token TEXT NOT NULL,
    rotated_at INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class ClientRow:
    client_id: str
    secret_digest: str
    redirect_uris: list[str]
    max_scopes: list[str]


@dataclass(frozen=True)
class PendingRequest:
    id: str
    github_state: str
    client_id: str
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str | None
    scopes: list[str]
    client_state: str | None
    created_at: int
    state_used: bool
    github_ok: bool
    consent_csrf: str | None
    subject: str | None = None


@dataclass(frozen=True)
class AuthCodeRow:
    code_digest: str
    client_id: str
    scopes: list[str]
    expires_at: int
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str | None
    subject: str | None
    consumed: bool


@dataclass(frozen=True)
class TokenRow:
    token_digest: str
    client_id: str
    scopes: list[str]
    expires_at: int
    resource: str | None
    subject: str | None
    family_id: str
    revoked: bool
    rotated_at: int | None = None


@dataclass(frozen=True)
class GracePair:
    new_access_token: str
    new_refresh_token: str
    rotated_at: int
    family_id: str


def _now() -> int:
    return int(time.time())


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class AuthStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with closing(_connect(path)) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _run(self, fn):
        with closing(_connect(self.path)) as conn:
            result = fn(conn)
            conn.commit()
            return result

    def purge_idle_clients(self, now: int | None = None) -> int:
        cutoff = (now or _now()) - CLIENT_IDLE_SECONDS

        def work(conn: sqlite3.Connection) -> int:
            cur = conn.execute("DELETE FROM clients WHERE last_used_at < ?", (cutoff,))
            return cur.rowcount

        return self._run(work)

    def touch_client(self, client_id: str, now: int | None = None) -> None:
        stamp = now or _now()

        def work(conn: sqlite3.Connection) -> None:
            conn.execute("UPDATE clients SET last_used_at = ? WHERE client_id = ?", (stamp, client_id))

        self._run(work)

    def add_client(
        self,
        client_id: str,
        secret_digest: str,
        redirect_uris: list[str],
        max_scopes: list[str],
        now: int | None = None,
    ) -> None:
        stamp = now or _now()

        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO clients (client_id, secret_digest, redirect_uris, max_scopes, created_at, last_used_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    client_id,
                    secret_digest,
                    json.dumps(redirect_uris),
                    json.dumps(max_scopes),
                    stamp,
                    stamp,
                ),
            )

        self._run(work)

    def get_client(self, client_id: str) -> ClientRow | None:
        def work(conn: sqlite3.Connection) -> ClientRow | None:
            row = conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()
            if row is None:
                return None
            return ClientRow(
                client_id=row["client_id"],
                secret_digest=row["secret_digest"],
                redirect_uris=json.loads(row["redirect_uris"]),
                max_scopes=json.loads(row["max_scopes"]),
            )

        return self._run(work)

    def save_pending(self, pending: PendingRequest) -> None:
        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO pending_requests ("
                " id, github_state, client_id, code_challenge, redirect_uri,"
                " redirect_uri_provided_explicitly, resource, scopes, client_state,"
                " created_at, state_used, github_ok, consent_csrf, subject"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pending.id,
                    pending.github_state,
                    pending.client_id,
                    pending.code_challenge,
                    pending.redirect_uri,
                    int(pending.redirect_uri_provided_explicitly),
                    pending.resource,
                    json.dumps(pending.scopes),
                    pending.client_state,
                    pending.created_at,
                    int(pending.state_used),
                    int(pending.github_ok),
                    pending.consent_csrf,
                    pending.subject,
                ),
            )

        self._run(work)

    def get_pending_by_state(self, github_state: str) -> PendingRequest | None:
        def work(conn: sqlite3.Connection) -> PendingRequest | None:
            row = conn.execute(
                "SELECT * FROM pending_requests WHERE github_state = ?", (github_state,)
            ).fetchone()
            return _pending_from_row(row) if row else None

        return self._run(work)

    def get_pending(self, pending_id: str) -> PendingRequest | None:
        def work(conn: sqlite3.Connection) -> PendingRequest | None:
            row = conn.execute("SELECT * FROM pending_requests WHERE id = ?", (pending_id,)).fetchone()
            return _pending_from_row(row) if row else None

        return self._run(work)

    def mark_state_used(self, github_state: str) -> bool:
        """Mark a GitHub state as used. Returns False if it was already used or missing."""

        def work(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE pending_requests SET state_used = 1"
                " WHERE github_state = ? AND state_used = 0",
                (github_state,),
            )
            return cur.rowcount == 1

        return self._run(work)

    def mark_github_ok(self, pending_id: str, consent_csrf: str, subject: str) -> None:
        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE pending_requests SET github_ok = 1, consent_csrf = ?, subject = ? WHERE id = ?",
                (consent_csrf, subject, pending_id),
            )

        self._run(work)

    def delete_pending(self, pending_id: str) -> None:
        def work(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM pending_requests WHERE id = ?", (pending_id,))

        self._run(work)

    def is_pending_fresh(self, pending: PendingRequest, now: int | None = None) -> bool:
        return pending.created_at + PENDING_TTL_SECONDS > (now or _now())

    def save_auth_code(self, row: AuthCodeRow) -> None:
        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO authorization_codes ("
                " code_digest, client_id, scopes, expires_at, code_challenge,"
                " redirect_uri, redirect_uri_provided_explicitly, resource, subject, consumed"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.code_digest,
                    row.client_id,
                    json.dumps(row.scopes),
                    row.expires_at,
                    row.code_challenge,
                    row.redirect_uri,
                    int(row.redirect_uri_provided_explicitly),
                    row.resource,
                    row.subject,
                    int(row.consumed),
                ),
            )

        self._run(work)

    def get_auth_code(self, code_digest: str) -> AuthCodeRow | None:
        def work(conn: sqlite3.Connection) -> AuthCodeRow | None:
            row = conn.execute(
                "SELECT * FROM authorization_codes WHERE code_digest = ?", (code_digest,)
            ).fetchone()
            if row is None:
                return None
            return AuthCodeRow(
                code_digest=row["code_digest"],
                client_id=row["client_id"],
                scopes=json.loads(row["scopes"]),
                expires_at=row["expires_at"],
                code_challenge=row["code_challenge"],
                redirect_uri=row["redirect_uri"],
                redirect_uri_provided_explicitly=bool(row["redirect_uri_provided_explicitly"]),
                resource=row["resource"],
                subject=row["subject"],
                consumed=bool(row["consumed"]),
            )

        return self._run(work)

    def consume_auth_code(self, code_digest: str) -> bool:
        def work(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE authorization_codes SET consumed = 1"
                " WHERE code_digest = ? AND consumed = 0",
                (code_digest,),
            )
            return cur.rowcount == 1

        return self._run(work)

    def save_access_token(self, row: TokenRow) -> None:
        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO access_tokens ("
                " token_digest, client_id, scopes, expires_at, resource, subject, family_id, revoked"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.token_digest,
                    row.client_id,
                    json.dumps(row.scopes),
                    row.expires_at,
                    row.resource,
                    row.subject,
                    row.family_id,
                    int(row.revoked),
                ),
            )

        self._run(work)

    def save_refresh_token(self, row: TokenRow) -> None:
        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO refresh_tokens ("
                " token_digest, client_id, scopes, expires_at, resource, subject,"
                " family_id, revoked, rotated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.token_digest,
                    row.client_id,
                    json.dumps(row.scopes),
                    row.expires_at,
                    row.resource,
                    row.subject,
                    row.family_id,
                    int(row.revoked),
                    row.rotated_at,
                ),
            )

        self._run(work)

    def get_access_token(self, token_digest: str) -> TokenRow | None:
        def work(conn: sqlite3.Connection) -> TokenRow | None:
            row = conn.execute(
                "SELECT *, NULL AS rotated_at FROM access_tokens WHERE token_digest = ?",
                (token_digest,),
            ).fetchone()
            return _token_from_row(row) if row else None

        return self._run(work)

    def get_refresh_token(self, token_digest: str) -> TokenRow | None:
        def work(conn: sqlite3.Connection) -> TokenRow | None:
            row = conn.execute(
                "SELECT * FROM refresh_tokens WHERE token_digest = ?", (token_digest,)
            ).fetchone()
            return _token_from_row(row) if row else None

        return self._run(work)

    def rotate_refresh(
        self,
        old_digest: str,
        family_id: str,
        new_access_token: str,
        new_refresh_token: str,
        now: int | None = None,
    ) -> None:
        stamp = now or _now()

        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE refresh_tokens SET revoked = 1, rotated_at = ? WHERE token_digest = ?",
                (stamp, old_digest),
            )
            conn.execute(
                "INSERT OR REPLACE INTO refresh_graces"
                " (old_digest, family_id, new_access_token, new_refresh_token, rotated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (old_digest, family_id, new_access_token, new_refresh_token, stamp),
            )

        self._run(work)

    def get_grace(self, old_digest: str) -> GracePair | None:
        def work(conn: sqlite3.Connection) -> GracePair | None:
            row = conn.execute(
                "SELECT * FROM refresh_graces WHERE old_digest = ?", (old_digest,)
            ).fetchone()
            if row is None:
                return None
            return GracePair(
                new_access_token=row["new_access_token"],
                new_refresh_token=row["new_refresh_token"],
                rotated_at=row["rotated_at"],
                family_id=row["family_id"],
            )

        return self._run(work)

    def revoke_family(self, family_id: str) -> None:
        def work(conn: sqlite3.Connection) -> None:
            conn.execute("UPDATE access_tokens SET revoked = 1 WHERE family_id = ?", (family_id,))
            conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE family_id = ?", (family_id,))
            conn.execute("DELETE FROM refresh_graces WHERE family_id = ?", (family_id,))

        self._run(work)

    def revoke_token_digest(self, token_digest: str) -> None:
        def work(conn: sqlite3.Connection) -> None:
            access = conn.execute(
                "SELECT family_id FROM access_tokens WHERE token_digest = ?", (token_digest,)
            ).fetchone()
            refresh = conn.execute(
                "SELECT family_id FROM refresh_tokens WHERE token_digest = ?", (token_digest,)
            ).fetchone()
            family = (access or refresh)
            if family is None:
                return
            family_id = family["family_id"]
            conn.execute("UPDATE access_tokens SET revoked = 1 WHERE family_id = ?", (family_id,))
            conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE family_id = ?", (family_id,))
            conn.execute("DELETE FROM refresh_graces WHERE family_id = ?", (family_id,))

        self._run(work)

    def revoke_all_tokens(self) -> None:
        def work(conn: sqlite3.Connection) -> None:
            conn.execute("UPDATE access_tokens SET revoked = 1")
            conn.execute("UPDATE refresh_tokens SET revoked = 1")
            conn.execute("DELETE FROM refresh_graces")
            conn.execute("DELETE FROM authorization_codes")
            conn.execute("DELETE FROM pending_requests")

        self._run(work)


def _pending_from_row(row: sqlite3.Row) -> PendingRequest:
    return PendingRequest(
        id=row["id"],
        github_state=row["github_state"],
        client_id=row["client_id"],
        code_challenge=row["code_challenge"],
        redirect_uri=row["redirect_uri"],
        redirect_uri_provided_explicitly=bool(row["redirect_uri_provided_explicitly"]),
        resource=row["resource"],
        scopes=json.loads(row["scopes"]),
        client_state=row["client_state"],
        created_at=row["created_at"],
        state_used=bool(row["state_used"]),
        github_ok=bool(row["github_ok"]),
        consent_csrf=row["consent_csrf"],
        subject=row["subject"],
    )


def _token_from_row(row: sqlite3.Row) -> TokenRow:
    return TokenRow(
        token_digest=row["token_digest"],
        client_id=row["client_id"],
        scopes=json.loads(row["scopes"]),
        expires_at=row["expires_at"],
        resource=row["resource"],
        subject=row["subject"],
        family_id=row["family_id"],
        revoked=bool(row["revoked"]),
        rotated_at=row["rotated_at"],
    )
