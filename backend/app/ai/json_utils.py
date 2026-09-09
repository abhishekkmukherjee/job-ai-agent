"""Robust extraction of a JSON object from LLM output."""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _try_load(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = _TRAILING_COMMA_RE.sub(r"\1", text)
        return json.loads(cleaned)


def extract_json(text: str) -> dict[str, Any]:
    """Return the first JSON object found in `text`.

    Handles markdown code fences, leading prose, trailing commentary and
    trailing commas.  Raises ValueError when no object can be decoded.
    """
    if not text:
        raise ValueError("empty response")
    candidates: list[str] = []
    for m in _FENCE_RE.finditer(text):
        candidates.append(m.group(1).strip())
    candidates.append(text.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    last_error: Exception | None = None
    for cand in candidates:
        if not cand:
            continue
        try:
            data = _try_load(cand)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            continue
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return {"items": data}
    # Last resort: scan for balanced braces
    depth = 0
    begin = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                begin = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and begin != -1:
                try:
                    data = _try_load(text[begin : i + 1])
                    if isinstance(data, dict):
                        return data
                except (json.JSONDecodeError, ValueError) as e:
                    last_error = e
    raise ValueError(f"no JSON object found in response: {last_error}")
