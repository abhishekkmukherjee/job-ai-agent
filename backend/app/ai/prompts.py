"""Prompt loading and rendering.

Prompts live in /prompts as plain text files with {{placeholders}}.  A versioned
file (`name.v2.txt`) takes precedence over the unversioned one so old versions
can be kept around for comparison.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import PROMPTS_DIR


class PromptNotFound(FileNotFoundError):
    pass


@lru_cache(maxsize=32)
def load_prompt(name: str, version: int = 1, prompts_dir: str | None = None) -> str:
    base = Path(prompts_dir) if prompts_dir else PROMPTS_DIR
    candidates = [base / f"{name}.v{version}.txt", base / f"{name}.txt"]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise PromptNotFound(f"Prompt '{name}' (version {version}) not found in {base}")


def render_prompt(template: str, **values: object) -> str:
    """Replace {{key}} placeholders.  Unknown placeholders are left untouched."""
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", "" if value is None else str(value))
    return out


def clear_prompt_cache() -> None:
    load_prompt.cache_clear()
