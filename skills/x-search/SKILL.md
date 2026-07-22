---
name: x-search
description: Search X (Twitter) posts via xAI's built-in x_search tool. Requires xai-oauth skill or XAI_API_KEY env var.
metadata:
  {
    "openclaw":
      {
        "emoji": "🔍",
        "requires": { "bins": ["python3"] },
      },
  }
---

# X Search Skill

Search X (Twitter) posts using xAI's x_search tool via the Responses API.

## Usage

```bash
# Basic search
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "search query"

# Filter by handles
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "topic" --handles @elonmusk,@xaboratory

# Exclude handles
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "topic" --exclude @spam1,@spam2

# Date range
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "topic" --from 2026-01-01 --to 2026-05-16

# Media filters
python3 ~/.openclaw/skills/x-search/scripts/x-search.py "topic" --images --videos
```

## Credential Resolution

1. xai-oauth skill (preferred) — runs `xai-oauth.py token`
2. `XAI_API_KEY` environment variable (fallback)

## Output

JSON to stdout with `success`, `answer`, `citations`, `inline_citations`, `model`, and `credential_source` fields.

## Notes

- Standard library Python only (no pip dependencies)
- Cannot use both `--handles` and `--exclude` simultaneously
- Max 10 handles per filter
- Retries on 5xx/timeout (up to 2 retries with backoff)
