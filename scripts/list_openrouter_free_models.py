"""List OpenRouter models that are currently free (useful for OPENROUTER_MODEL).

    python scripts/list_openrouter_free_models.py
"""
from __future__ import annotations

import sys

import httpx


def main() -> int:
    try:
        resp = httpx.get("https://openrouter.ai/api/v1/models", timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"Failed to fetch models: {e}", file=sys.stderr)
        return 1
    free = []
    for m in resp.json().get("data", []):
        pricing = m.get("pricing") or {}
        if str(pricing.get("prompt", "1")) in ("0", "0.0") and str(pricing.get("completion", "1")) in ("0", "0.0"):
            free.append((m.get("id"), (m.get("context_length") or 0)))
    free.sort(key=lambda x: -x[1])
    print(f"{len(free)} free models (sorted by context length):\n")
    for model_id, ctx in free:
        print(f"  {model_id:<60} ctx={ctx}")
    print("\nSet one of these as OPENROUTER_MODEL in .env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
