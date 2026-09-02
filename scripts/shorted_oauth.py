#!/usr/bin/env python3
"""OAuth 2.1 client for api.shorted.com.au — so no API key is ever pasted anywhere.

The point of this module is that a credential is never handled by a human, never
typed into a shell, and never written into the repo. You authorise once in a
browser; the token lives in ~/.config/omega, mode 0600, and refreshes itself.

How it works, and why each piece is needed:

* **Discovery** (RFC 8414). The authorization server is found from the resource's
  own metadata rather than hardcoded, so a dev or preview origin authorises
  against its own server instead of silently against prod.

* **Dynamic registration** (RFC 7591). There is no pre-shared client id to
  distribute or leak: the client registers itself on first use and caches the id.
  The server issues a PUBLIC client (`token_endpoint_auth_method: none`), so
  there is no client secret in existence to protect.

* **PKCE S256** (RFC 7636), which is what makes a public client safe: the
  authorization code is worthless without the verifier, which never leaves this
  process. `state` is checked on the way back to close CSRF.

* **Loopback redirect** (RFC 8252 §7.3) on 127.0.0.1. The code arrives over the
  loopback interface and is never pasted, so it cannot be shoulder-surfed out of
  a terminal or captured from shell history.

* **Refresh.** Access tokens live one hour; a full universe rebuild takes about
  half of that, but a resumed one can straddle the boundary. `refresh_token` is
  an advertised grant, so a long job renews instead of dying at minute 61.

The token this yields carries `aud = <origin>/mcp` alone. That is deliberately
NOT a whole-API credential — it cannot reach MintToken and cannot satisfy a
required_role — but since castlemilk/shorted.com.au#579 the Connect API reads it
for IDENTITY on public methods, which is every endpoint the research engine
touches. So this is exactly enough authority to be metered as ourselves, and no
more. That is the whole design: the least credential that lifts the rate limit.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import ClassVar

RESOURCE_METADATA = "https://api.shorted.com.au/.well-known/oauth-protected-resource/mcp"
API_ORIGIN = "https://api.shorted.com.au"
SCOPES = "shorts:read"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
UA = "omega-asx-research/0.1"

# Outside the repo on purpose: a token in a working tree is one `git add -A` away
# from being published, and this campaign has already lost a day to exactly that.
CACHE = Path.home() / ".config" / "omega" / "shorted_oauth.json"

# Refresh this far before actual expiry, so a long-running request started just
# under the wire does not finish against an expired token.
EXPIRY_SKEW = 120

# How long to wait for the browser round-trip. Generous on purpose: it spans
# signing in, an MFA prompt and reading the consent screen, and the cost of
# being wrong is a full re-run of the flow.
AUTH_TIMEOUT = 900


def _get(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _post_form(url: str, form: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # The body is the whole diagnosis for an OAuth failure — RFC 6749 §5.2
        # puts `error` and `error_description` there. Losing it turns every
        # misconfiguration into an indistinguishable "HTTP 400".
        body = e.read().decode()[:400]
        raise RuntimeError(f"token endpoint {e.code}: {body}") from None


def _post_json(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _load() -> dict:
    if not CACHE.is_file():
        return {}
    try:
        return json.loads(CACHE.read_text())
    except json.JSONDecodeError:
        return {}


def _save(state: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(state, indent=1, sort_keys=True))
    CACHE.chmod(0o600)


def _discover() -> dict:
    """Resource metadata -> authorization server metadata (RFC 9728 then RFC 8414)."""
    res = _get(RESOURCE_METADATA)
    servers = res.get("authorization_servers") or [API_ORIGIN]
    base = servers[0].rstrip("/")
    return _get(f"{base}/.well-known/oauth-authorization-server")


def _register(meta: dict) -> str:
    reg = _post_json(
        meta["registration_endpoint"],
        {
            "client_name": "omega-asx-research",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPES,
        },
    )
    return reg["client_id"]


class _Catcher(http.server.BaseHTTPRequestHandler):
    """Single-shot loopback listener for the redirect."""

    result: ClassVar[dict] = {}
    expected_state: ClassVar[str] = ""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        got = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        # A stale tab from an earlier run carries an earlier `state`. Rejecting it
        # is right — that is the CSRF check doing its job — but ABORTING on it is
        # not: it turns one mis-click into a full re-run of the flow. Discard the
        # response and keep listening for the one that matches.
        if got.get("state") and got["state"] != _Catcher.expected_state:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font:15px system-ui;padding:3rem'>"
                b"<h2>Stale link.</h2><p>That was an older authorisation attempt. "
                b"Use the most recent link in the terminal &mdash; still waiting.</p>"
                b"</body></html>"
            )
            print("  ignored a callback from an earlier attempt (state mismatch)", flush=True)
            return
        _Catcher.result = got
        ok = "code" in _Catcher.result
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body style='font:15px system-ui;padding:3rem'>"
            + (
                b"<h2>Authorised.</h2><p>You can close this tab and return to the terminal.</p>"
                if ok
                else b"<h2>Authorisation failed.</h2><p>Check the terminal.</p>"
            )
            + b"</body></html>"
        )

    def log_message(self, *args):  # silence the default stderr logging
        return


def _authorize(meta: dict, client_id: str) -> dict:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    state = secrets.token_urlsafe(24)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # RFC 8707: bind the token to the MCP resource explicitly.
        "resource": f"{API_ORIGIN}/mcp",
    }
    url = meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)

    # serve_forever, not handle_request: handle_request() services exactly ONE
    # request, so a browser's speculative /favicon.ico — or any probe that beats
    # the redirect to the port — consumes the listener and the real callback is
    # never heard. Serve until a request actually carries a code.
    srv = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), _Catcher)
    _Catcher.result = {}
    _Catcher.expected_state = state
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    print("\n  Authorise omega to read shorted.com.au as you:\n")
    print(f"    {url}\n")
    try:
        webbrowser.open(url)
        print("  (opened in your browser — approve there)\n")
    except Exception:
        print("  (open that link in your browser)\n")

    deadline = time.time() + AUTH_TIMEOUT
    while time.time() < deadline and "code" not in _Catcher.result and "error" not in _Catcher.result:
        time.sleep(0.4)
    srv.shutdown()
    srv.server_close()
    res = _Catcher.result
    if not res:
        raise RuntimeError("timed out waiting for the browser redirect")
    if res.get("state") != state:
        raise RuntimeError("state mismatch — discarding the response")
    if "code" not in res:
        raise RuntimeError(f"authorisation failed: {res.get('error', 'unknown')}")

    return _post_form(
        meta["token_endpoint"],
        {
            "grant_type": "authorization_code",
            "code": res["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": f"{API_ORIGIN}/mcp",
        },
    )


def _refresh(meta: dict, client_id: str, refresh_token: str) -> dict | None:
    try:
        return _post_form(
            meta["token_endpoint"],
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "resource": f"{API_ORIGIN}/mcp",
            },
        )
    except urllib.error.HTTPError:
        return None  # expired or revoked: fall back to a fresh authorisation


def _store(state: dict, tok: dict) -> None:
    state["access_token"] = tok["access_token"]
    state["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600))
    if tok.get("refresh_token"):
        state["refresh_token"] = tok["refresh_token"]
    _save(state)


def get_access_token(interactive: bool = True) -> str | None:
    """A valid access token, refreshing or authorising as needed.

    Returns None when no token can be obtained without a browser and
    `interactive` is False, so a batch caller can fall back to anonymous rather
    than hanging on a redirect nobody is going to complete.
    """
    # An explicitly supplied key still wins — useful in CI, where no browser exists.
    env = os.environ.get("OMEGA_SHORTED_API_KEY")
    if env:
        return env

    state = _load()
    now = int(time.time())

    if state.get("access_token") and state.get("expires_at", 0) - EXPIRY_SKEW > now:
        return state["access_token"]

    meta = _discover()
    client_id = state.get("client_id")
    if not client_id:
        client_id = _register(meta)
        state["client_id"] = client_id
        _save(state)

    if state.get("refresh_token"):
        tok = _refresh(meta, client_id, state["refresh_token"])
        if tok and tok.get("access_token"):
            _store(state, tok)
            return state["access_token"]

    if not interactive:
        return None

    tok = _authorize(meta, client_id)
    if not tok.get("access_token"):
        raise RuntimeError("token endpoint returned no access_token")
    _store(state, tok)
    return state["access_token"]


def status() -> dict:
    """Non-secret description of the cached credential, for logging."""
    s = _load()
    exp = s.get("expires_at")
    return {
        "cache": str(CACHE),
        "registered": bool(s.get("client_id")),
        "has_access_token": bool(s.get("access_token")),
        "has_refresh_token": bool(s.get("refresh_token")),
        "expires_in_s": (exp - int(time.time())) if exp else None,
    }


if __name__ == "__main__":
    tok = get_access_token()
    st = status()
    print(f"  token acquired: {bool(tok)}")
    print(f"  {json.dumps({k: v for k, v in st.items()}, indent=1)}")
