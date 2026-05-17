---
name: xai-oauth
description: Authenticate with xAI via OAuth 2.0 PKCE loopback flow for SuperGrok subscription access. Run once to authorize, then auto-refreshes.
metadata:
  {
    "openclaw":
      {
        "emoji": "🔑",
        "requires": { "bins": ["python3"] },
      },
  }
---

# xAI OAuth Skill

Authenticate with xAI (Grok) using OAuth 2.0 Authorization Code + PKCE via a local loopback server.

## Usage

```bash
# First-time login (opens browser)
python3 ~/.openclaw/skills/xai-oauth/scripts/xai-oauth.py login

# Check auth status
python3 ~/.openclaw/skills/xai-oauth/scripts/xai-oauth.py status

# Get access token (refreshes if needed)
python3 ~/.openclaw/skills/xai-oauth/scripts/xai-oauth.py token

# Manually refresh
python3 ~/.openclaw/skills/xai-oauth/scripts/xai-oauth.py refresh
```

## Token Storage

Tokens are stored at `~/.openclaw/xai-oauth.json`.

## Notes

- Uses PKCE (S256) — no client secret needed
- Loopback server on 127.0.0.1:56121 (fallback to random port)
- Tokens auto-refresh when within 120s of expiry
- Standard library Python only (no pip dependencies)
