#!/usr/bin/env python3
"""Search X (Twitter) posts via xAI's x_search tool."""

import json
import os
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.x.ai/v1/responses"
MODEL = "grok-4.20-reasoning"
XAI_OAUTH_SCRIPT = os.path.expanduser("~/.openclaw/skills/xai-oauth/scripts/xai-oauth.py")
MAX_HANDLES = 10
MAX_RETRIES = 2
TIMEOUT = 180


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def get_credential():
    """Resolve credential: try xai-oauth first, then XAI_API_KEY."""
    # Try xai-oauth
    try:
        result = subprocess.run(
            ["python3", XAI_OAUTH_SCRIPT, "token"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), "xai-oauth"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Try env var
    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if api_key:
        return api_key, "env:XAI_API_KEY"

    return None, None


def normalize_handles(handles_str):
    """Parse comma-separated handles, strip @, error if over limit."""
    if not handles_str:
        return []
    handles = [h.strip().lstrip("@") for h in handles_str.split(",")]
    handles = [h for h in handles if h]
    if len(handles) > MAX_HANDLES:
        eprint(f"Error: too many handles ({len(handles)}). Maximum is {MAX_HANDLES}.")
        sys.exit(1)
    return handles


def build_request_body(query, args):
    """Build the API request body."""
    tool_params = {}

    if args.get("handles"):
        tool_params["allowed_x_handles"] = args["handles"]
    if args.get("exclude"):
        tool_params["excluded_x_handles"] = args["exclude"]
    if args.get("from_date"):
        tool_params["from_date"] = args["from_date"]
    if args.get("to_date"):
        tool_params["to_date"] = args["to_date"]
    if args.get("images"):
        tool_params["enable_image_understanding"] = True
    if args.get("videos"):
        tool_params["enable_video_understanding"] = True

    tool_def = {"type": "x_search"}
    if tool_params:
        tool_def.update(tool_params)

    body = {
        "model": MODEL,
        "input": [{"role": "user", "content": query}],
        "tools": [tool_def],
        "store": False,
    }

    return body


def parse_response(data):
    """Extract answer, citations, and inline citations from response."""
    answer = ""
    citations = []
    inline_citations = []

    # Try output_text first
    if "output_text" in data and data["output_text"]:
        answer = data["output_text"]

    # Extract from output array
    output = data.get("output", [])
    for item in output:
        if item.get("type") == "message":
            content = item.get("content", [])
            for block in content:
                if block.get("type") == "output_text" or block.get("type") == "text":
                    if not answer:
                        answer = block.get("text", "")
                    # Extract inline citations from annotations
                    annotations = block.get("annotations", [])
                    for ann in annotations:
                        if ann.get("type") == "url_citation":
                            inline_citations.append({
                                "url": ann.get("url", ""),
                                "title": ann.get("title", ""),
                                "start_index": ann.get("start_index", 0),
                                "end_index": ann.get("end_index", 0),
                            })

    # Top-level citations
    if "citations" in data and isinstance(data["citations"], list):
        citations = data["citations"]

    return answer, citations, inline_citations


def do_search(query, args):
    """Execute the search API call with retries."""
    token, source = get_credential()
    if not token:
        return {
            "success": False,
            "error": "No credentials available. Run xai-oauth login or set XAI_API_KEY.",
            "error_type": "AuthError",
        }

    body = build_request_body(query, args)
    body_bytes = json.dumps(body).encode("utf-8")

    backoff = [1.5, 3.0]
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        req = Request(API_URL, data=body_bytes, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")

        try:
            with urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())

            answer, citations, inline_citations = parse_response(data)

            return {
                "success": True,
                "query": query,
                "answer": answer,
                "citations": citations,
                "inline_citations": inline_citations,
                "model": MODEL,
                "credential_source": source,
            }

        except HTTPError as e:
            status = e.code
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            if status == 401:
                return {
                    "success": False,
                    "error": f"Authentication failed (401): {err_body}",
                    "error_type": "AuthError",
                }
            elif status == 429:
                return {
                    "success": False,
                    "error": f"Rate limited (429): {err_body}",
                    "error_type": "RateLimitError",
                }
            elif status >= 500 and attempt < MAX_RETRIES:
                last_error = f"Server error ({status}): {err_body}"
                eprint(f"Retry {attempt + 1}/{MAX_RETRIES} after {status}...")
                time.sleep(backoff[attempt])
                continue
            else:
                return {
                    "success": False,
                    "error": f"HTTP {status}: {err_body}",
                    "error_type": "HTTPError",
                }

        except (URLError, TimeoutError) as e:
            if attempt < MAX_RETRIES:
                last_error = str(e)
                eprint(f"Retry {attempt + 1}/{MAX_RETRIES} after timeout/network error...")
                time.sleep(backoff[attempt])
                continue
            return {
                "success": False,
                "error": f"Network error: {e}",
                "error_type": "NetworkError",
            }

        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON response: {e}",
                "error_type": "ParseError",
            }

    return {
        "success": False,
        "error": f"Max retries exceeded. Last error: {last_error}",
        "error_type": "RetryExhausted",
    }


def parse_args(argv):
    """Parse command-line arguments."""
    if not argv:
        eprint("Usage: x-search.py \"query\" [--handles @u1,@u2] [--exclude @u1] [--from DATE] [--to DATE] [--images] [--videos]")
        sys.exit(1)

    query = argv[0]
    args = {}
    i = 1

    while i < len(argv):
        arg = argv[i]
        if arg == "--handles" and i + 1 < len(argv):
            i += 1
            args["handles"] = normalize_handles(argv[i])
        elif arg == "--exclude" and i + 1 < len(argv):
            i += 1
            args["exclude"] = normalize_handles(argv[i])
        elif arg == "--from" and i + 1 < len(argv):
            i += 1
            args["from_date"] = argv[i]
        elif arg == "--to" and i + 1 < len(argv):
            i += 1
            args["to_date"] = argv[i]
        elif arg == "--images":
            args["images"] = True
        elif arg == "--videos":
            args["videos"] = True
        else:
            eprint(f"Unknown argument: {arg}")
            sys.exit(1)
        i += 1

    # Validate: cannot use both handles and exclude
    if args.get("handles") and args.get("exclude"):
        eprint("Error: cannot use both --handles and --exclude simultaneously")
        sys.exit(1)

    return query, args


def main():
    query, args = parse_args(sys.argv[1:])
    result = do_search(query, args)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
