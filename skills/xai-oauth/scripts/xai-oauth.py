#!/usr/bin/env python3
"""xAI OAuth 2.0 PKCE loopback flow for OpenClaw."""

import base64
import hashlib
import json
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
OIDC_DISCOVERY = "https://auth.x.ai/.well-known/openid-configuration"
TOKEN_FILE = os.path.expanduser("~/.openclaw/xai-oauth.json")
DEFAULT_PORT = 56121
CALLBACK_TIMEOUT = 180
ALLOWED_CORS_ORIGINS = ["https://accounts.x.ai", "https://auth.x.ai"]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def validate_xai_origin(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = parsed.hostname or ""
    return host == "x.ai" or host.endswith(".x.ai")


def discover_oidc():
    req = Request(OIDC_DISCOVERY)
    try:
        with urlopen(req, timeout=15) as resp:
            config = json.loads(resp.read())
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        eprint(f"Failed to fetch OIDC discovery: {e}")
        sys.exit(1)

    authorization_endpoint = config.get("authorization_endpoint", "")
    token_endpoint = config.get("token_endpoint", "")

    if not validate_xai_origin(authorization_endpoint):
        eprint(f"Authorization endpoint not on x.ai origin: {authorization_endpoint}")
        sys.exit(1)
    if not validate_xai_origin(token_endpoint):
        eprint(f"Token endpoint not on x.ai origin: {token_endpoint}")
        sys.exit(1)

    return authorization_endpoint, token_endpoint


def generate_pkce():
    verifier_bytes = secrets.token_bytes(64)
    code_verifier = b64url_encode(verifier_bytes)[:128]
    challenge_digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = b64url_encode(challenge_digest)
    return code_verifier, code_challenge


def find_port():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", DEFAULT_PORT))
        sock.close()
        return DEFAULT_PORT
    except OSError:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port


def decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        payload = b64url_decode(parts[1])
        return json.loads(payload)
    except (ValueError, json.JSONDecodeError):
        return {}


def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        eprint(f"Failed to load token file: {e}")
        return None


def save_tokens(tokens: dict):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    os.chmod(TOKEN_FILE, 0o600)


def exchange_code(token_endpoint, code, redirect_uri, code_verifier):
    data = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": CLIENT_ID,
        "code_verifier": code_verifier,
    }).encode("utf-8")

    req = Request(token_endpoint, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        eprint(f"Token exchange failed ({e.code}): {body}")
        sys.exit(1)
    except (URLError, json.JSONDecodeError) as e:
        eprint(f"Token exchange error: {e}")
        sys.exit(1)


def refresh_tokens(token_endpoint, refresh_token):
    if not validate_xai_origin(token_endpoint):
        eprint(f"Refusing to send refresh token to non-x.ai endpoint: {token_endpoint}")
        sys.exit(1)

    data = urlencode({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    }).encode("utf-8")

    req = Request(token_endpoint, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        eprint(f"Token refresh failed ({e.code}): {body}")
        sys.exit(1)
    except (URLError, json.JSONDecodeError) as e:
        eprint(f"Token refresh error: {e}")
        sys.exit(1)


# --- Login command ---

def cmd_login():
    authorization_endpoint, token_endpoint = discover_oidc()
    code_verifier, code_challenge = generate_pkce()
    port = find_port()
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = secrets.token_hex(16)
    nonce = secrets.token_hex(16)

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email offline_access grok-cli:access api:access",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
        "plan": "generic",
        "referrer": "openclaw",
    }

    authorize_url = f"{authorization_endpoint}?{urlencode(params)}"

    # Callback state
    result = {"code": None, "error": None}
    server_ready = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            qs = parse_qs(parsed.query)

            # Check state
            received_state = qs.get("state", [None])[0]
            if received_state != state:
                result["error"] = "State mismatch"
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Error: state mismatch</h1>")
                return

            if "error" in qs:
                result["error"] = qs["error"][0]
                desc = qs.get("error_description", [""])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"<h1>OAuth Error: {qs['error'][0]}</h1><p>{desc}</p>".encode())
                return

            code = qs.get("code", [None])[0]
            if not code:
                result["error"] = "No code in callback"
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Error: no authorization code received</h1>")
                return

            result["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization successful!</h1><p>You can close this tab.</p>")

        def do_OPTIONS(self):
            origin = self.headers.get("Origin", "")
            self.send_response(204)
            if origin in ALLOWED_CORS_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def log_message(self, format, *args):
            pass  # Suppress request logging

    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    server.timeout = CALLBACK_TIMEOUT

    def serve():
        server_ready.set()
        server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    server_ready.wait()

    eprint(f"\nOpen this URL to authorize:\n\n  {authorize_url}\n")
    try:
        webbrowser.open(authorize_url)
        eprint("(Browser opened automatically)")
    except Exception:
        eprint("(Could not open browser — please open the URL manually)")

    thread.join(timeout=CALLBACK_TIMEOUT)

    if result["error"]:
        eprint(f"\nAuthorization failed: {result['error']}")
        sys.exit(1)

    if not result["code"]:
        eprint("\nTimeout waiting for callback (180s)")
        sys.exit(1)

    eprint("\nExchanging code for tokens...")
    token_response = exchange_code(token_endpoint, result["code"], redirect_uri, code_verifier)

    if not token_response.get("access_token"):
        eprint("Token exchange did not return access_token")
        sys.exit(1)
    if not token_response.get("refresh_token"):
        eprint("Token exchange did not return refresh_token")
        sys.exit(1)

    tokens = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response["refresh_token"],
        "id_token": token_response.get("id_token", ""),
        "expires_in": token_response.get("expires_in", 3600),
        "token_type": token_response.get("token_type", "Bearer"),
        "token_endpoint": token_endpoint,
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "oauth-loopback",
    }

    save_tokens(tokens)
    eprint("\nAuthentication successful! Tokens saved.")


# --- Refresh command ---

def cmd_refresh():
    tokens = load_tokens()
    if not tokens:
        eprint("No tokens found. Run 'login' first.")
        sys.exit(1)

    access_token = tokens.get("access_token", "")
    token_endpoint = tokens.get("token_endpoint", "")
    refresh_token = tokens.get("refresh_token", "")

    if not refresh_token:
        eprint("No refresh token available. Run 'login' again.")
        sys.exit(1)

    # Check if token needs refresh
    payload = decode_jwt_payload(access_token)
    exp = payload.get("exp", 0)
    now = time.time()

    if exp > now + 120:
        # Token still valid
        print(access_token)
        return

    eprint("Token expiring soon, refreshing...")
    token_response = refresh_tokens(token_endpoint, refresh_token)

    if not token_response.get("access_token"):
        eprint("Refresh did not return access_token")
        sys.exit(1)

    tokens["access_token"] = token_response["access_token"]
    if "refresh_token" in token_response:
        tokens["refresh_token"] = token_response["refresh_token"]
    if "id_token" in token_response:
        tokens["id_token"] = token_response["id_token"]
    tokens["expires_in"] = token_response.get("expires_in", tokens.get("expires_in", 3600))
    tokens["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    save_tokens(tokens)
    eprint("Token refreshed.")
    print(tokens["access_token"])


# --- Status command ---

def cmd_status():
    tokens = load_tokens()
    if not tokens:
        eprint("No token file found. Run 'login' first.")
        sys.exit(1)

    access_token = tokens.get("access_token", "")
    payload = decode_jwt_payload(access_token)
    exp = payload.get("exp", 0)
    now = time.time()

    source = tokens.get("source", "unknown")
    last_refresh = tokens.get("last_refresh", "unknown")

    eprint(f"Source: {source}")
    eprint(f"Last refresh: {last_refresh}")

    if exp == 0:
        eprint("Could not decode token expiry")
        sys.exit(1)

    remaining = exp - now
    exp_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp))

    if remaining <= 0:
        eprint(f"Token EXPIRED at {exp_time} ({int(-remaining)}s ago)")
        sys.exit(1)
    else:
        eprint(f"Token expires: {exp_time} ({int(remaining)}s remaining)")
        sys.exit(0)


# --- Token command ---

def cmd_token():
    tokens = load_tokens()
    if not tokens:
        eprint("No tokens found. Run 'login' first.")
        sys.exit(1)

    access_token = tokens.get("access_token", "")
    token_endpoint = tokens.get("token_endpoint", "")
    refresh_token = tokens.get("refresh_token", "")

    # Check expiry
    payload = decode_jwt_payload(access_token)
    exp = payload.get("exp", 0)
    now = time.time()

    if exp <= now + 120 and refresh_token:
        eprint("Token expiring, refreshing...")
        if not token_endpoint:
            eprint("No token endpoint stored. Run 'login' again.")
            sys.exit(1)
        token_response = refresh_tokens(token_endpoint, refresh_token)
        if not token_response.get("access_token"):
            eprint("Refresh did not return access_token")
            sys.exit(1)
        tokens["access_token"] = token_response["access_token"]
        if "refresh_token" in token_response:
            tokens["refresh_token"] = token_response["refresh_token"]
        if "id_token" in token_response:
            tokens["id_token"] = token_response["id_token"]
        tokens["expires_in"] = token_response.get("expires_in", tokens.get("expires_in", 3600))
        tokens["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_tokens(tokens)
        access_token = tokens["access_token"]

    print(access_token)


# --- Main ---

def main():
    if len(sys.argv) < 2:
        eprint("Usage: xai-oauth.py <login|refresh|status|token>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "login":
        cmd_login()
    elif cmd == "refresh":
        cmd_refresh()
    elif cmd == "status":
        cmd_status()
    elif cmd == "token":
        cmd_token()
    else:
        eprint(f"Unknown command: {cmd}")
        eprint("Usage: xai-oauth.py <login|refresh|status|token>")
        sys.exit(1)


if __name__ == "__main__":
    main()
