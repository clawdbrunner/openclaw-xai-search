# openclaw-xai-search

Search X (Twitter) posts from OpenClaw using your existing SuperGrok subscription. No X developer account, no API keys, no rate limits to worry about.

Two skills that work together:

- **xai-oauth** — Authenticate with xAI via OAuth 2.0 PKCE using your SuperGrok subscription
- **x-search** — Search X posts in real time through xAI's Responses API

## How It Works

Instead of dealing with X's developer API (rate limits, expensive credits, developer accounts), this routes X search through xAI's API. If you have a SuperGrok subscription, you already have access — you just need to authenticate once.

1. **Authenticate** — Run the OAuth login, approve in your browser, done in 30 seconds
2. **Search** — Call `x-search.py` with any query, get back structured JSON with citations
3. **Auto-refresh** — Tokens refresh automatically, you stay logged in

Under the hood, it calls xAI's `/v1/responses` endpoint with the `x_search` tool, using `grok-4.20-reasoning` to process results. Your SuperGrok subscription covers the cost.

## Requirements

- **OpenClaw** installed and running
- **Python 3.9+** (stdlib only, no pip dependencies)
- An active **SuperGrok** subscription at [grok.com](https://grok.com)

## Installation

```bash
# Clone into your OpenClaw skills directory
git clone https://github.com/clawdbrunner/openclaw-xai-search.git
cd openclaw-xai-search

# Copy skills to OpenClaw
cp -r skills/xai-oauth ~/.openclaw/skills/
cp -r skills/x-search ~/.openclaw/skills/

# Make scripts executable
chmod +x ~/.openclaw/skills/xai-oauth/scripts/xai-oauth.py
chmod +x ~/.openclaw/skills/x-search/scripts/x-search.py
```

## Setup

### Step 1: Authenticate

```bash
python3 ~/.openclaw/skills/xai-oauth/scripts/xai-oauth.py login
```

This opens your browser to `accounts.x.ai`. Log in with the X account tied to your SuperGrok subscription and approve access. Tokens are stored securely at `~/.openclaw/xai-oauth.json` (file permissions `0600`).

**Remote/SSH sessions:** Use `--no-browser` to get a URL you can open on your local machine:

```bash
python3 ~/.openclaw/skills/xai-oauth/scripts/xai-oauth.py login --no-browser
```

### Step 2: Verify

```bash
python3 ~/.openclaw/skills/xai-oauth/scripts/xai-oauth.py status
```

### Step 3: Search

```bash
# Basic search
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "open source AI agents"

# Filter by specific accounts
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "AI agents" --handles @openclaw,@xaboratory

# Exclude accounts
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "AI agents" --exclude @spambot1,@spambot2

# Date range
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "AI agents" --from 2026-05-01 --to 2026-05-16

# Include image/video analysis
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "AI agents" --images --videos
```

Output is JSON to stdout:

```json
{
  "success": true,
  "query": "open source AI agents",
  "answer": "...",
  "citations": ["https://x.com/..."],
  "inline_citations": [...],
  "model": "grok-4.20-reasoning",
  "credential_source": "xai-oauth"
}
```

## Commands Reference

### xai-oauth

| Command | Description |
|---------|-------------|
| `login` | Start OAuth 2.0 PKCE browser flow |
| `login --no-browser` | Print auth URL instead of opening browser |
| `refresh` | Manually refresh access token |
| `status` | Show current auth state |
| `token` | Output current access token (for scripting) |

### x-search

| Flag | Description |
|------|-------------|
| `"query"` | Search query (required) |
| `--handles @a,@b` | Only include posts from these handles (max 10) |
| `--exclude @a,@b` | Exclude posts from these handles (max 10) |
| `--from YYYY-MM-DD` | Start date filter |
| `--to YYYY-MM-DD` | End date filter |
| `--images` | Include image analysis in results |
| `--videos` | Include video analysis in results |

## Credential Resolution

x-search resolves credentials in this order:

1. **xai-oauth** (preferred) — Uses your SuperGrok subscription via OAuth tokens
2. **XAI_API_KEY** (fallback) — If you have a paid xAI API key set as an environment variable

If neither is available, you'll get an error directing you to set up OAuth.

## Security

- **PKCE (S256)** — Full OAuth 2.0 PKCE flow with code challenge/verifier
- **State parameter** — CSRF protection on the callback
- **Loopback only** — Callback server binds to `127.0.0.1` only
- **Endpoint validation** — Token endpoint verified to be on `x.ai` origin
- **CORS restricted** — Callback only accepts requests from `accounts.x.ai` / `auth.x.ai`
- **Token storage** — Stored at `~/.openclaw/xai-oauth.json` with `0600` permissions
- **No token leakage** — Tokens never printed to logs or agent context
- **Auto-refresh** — JWT expiry checked, tokens refreshed 2 minutes before expiration

## Architecture

```
┌─────────────┐     OAuth 2.0 PKCE      ┌──────────────┐
│  xai-oauth  │ ──────────────────────── │ accounts.x.ai│
│  (login)    │ ←──── tokens ────────── │   auth.x.ai  │
└──────┬──────┘                          └──────────────┘
       │
       │ stores tokens at
       │ ~/.openclaw/xai-oauth.json
       │
       ▼
┌─────────────┐     POST /v1/responses   ┌──────────────┐
│  x-search   │ ──── x_search tool ────→ │  api.x.ai    │
│             │ ←── JSON + citations ─── │              │
└─────────────┘                          └──────────────┘
```

## Acknowledgments

Inspired by [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s xAI OAuth implementation. The OAuth flow parameters (client ID, scope, PKCE, `plan=generic`) and x_search API structure are based on their open-source work.

## License

MIT
