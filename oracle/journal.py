"""Forecast journal statistics: `python -m oracle.journal`."""
from datetime import datetime, timezone
import json

from . import storage
from .main import POST_WINDOW


def _calls(entries, phase):
    outcomes = [row["outcome"] for entry in entries
                for row in entry.get(phase, {}).get("evaluation", {}).values() if isinstance(row, dict)]
    correct, wrong = outcomes.count("CORRETTA"), outcomes.count("ERRATA")
    return {
        "valutate": len(outcomes), "corrette": correct, "errate": wrong,
        "incerte": outcomes.count("INCERTA"), "prezzi_mancanti": outcomes.count("PREZZI MANCANTI"),
        "direzioni_corrette_pct": round(100 * correct / (correct + wrong), 1) if correct + wrong else None,
    }


def stats(entries, now=None):
    now = now or datetime.now(timezone.utc)
    closed = [entry for entry in entries if datetime.fromisoformat(entry["event_time"]) + POST_WINDOW <= now]
    published = [entry for entry in closed if "published" in entry]
    directional = [entry for entry in published
                   if any(value in {"LONG", "SHORT"} for value in entry["published"]["directions"].values())]
    previews = [entry for entry in closed
                if any(value in {"LONG", "SHORT"} for value in entry.get("preliminary", {}).get("directions", {}).values())]
    delays = [entry["published"]["delay_s"] for entry in published
              if entry["published"]["delivery"] in {"delivered", "unknown", "dry_run"}]
    return {
        "eventi_conclusi": len(closed),
        "copertura_dato_pubblicato_pct": round(100 * len(published) / len(closed), 1) if closed else None,
        "eventi_con_direzione_dopo_dato": len(directional),
        "eventi_con_previsione_preliminare": len(previews),
        "ritardo_medio_notifica_s": round(sum(delays) / len(delays), 1) if delays else None,
        "dopo_dato": _calls(closed, "published"),
        "previsione_preliminare": _calls(closed, "preliminary"),
    }


if __name__ == "__main__":
    print(json.dumps(stats(storage.journal_entries()), indent=2, ensure_ascii=False))
