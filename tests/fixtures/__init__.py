"""Official documents downloaded on 2026-11-21 (trimmed to the parts the parsers read)."""
from pathlib import Path

ROOT = Path(__file__).parent


def text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def raw(name):
    return (ROOT / name).read_bytes()
