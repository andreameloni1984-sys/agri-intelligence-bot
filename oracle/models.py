from dataclasses import dataclass, field


EVENTS = {
    "cpi": ("Consumer Price Index", "Inflazione CPI"),
    "ppi": ("Producer Price Index", "Prezzi alla produzione PPI"),
    "pce": ("Personal Income and Outlays", "Inflazione PCE"),
    "nfp": ("Employment Situation", "Occupazione USA"),
    "claims": ("Unemployment Insurance Weekly Claims", "Richieste di disoccupazione"),
    "eia": ("Weekly Petroleum Status Report", "Scorte petrolifere EIA"),
    "fomc": ("FOMC policy decision", "Decisione FOMC"),
    "wasde": ("USDA WASDE", "Rapporto USDA WASDE"),
}


def event_kind(title: str) -> str | None:
    return next((kind for kind, (label, _) in EVENTS.items() if title.startswith(label)), None)


@dataclass
class Release:
    actual: dict[str, float]
    url: str
    previous: dict[str, float] = field(default_factory=dict)
    revised: dict[str, float] = field(default_factory=dict)
    periods: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass
class Context:
    consensus: dict[str, float] = field(default_factory=dict)
    previous: dict[str, float] = field(default_factory=dict)
    scenario: dict[str, float] = field(default_factory=dict)
    periods: dict[str, str] = field(default_factory=dict)
    urls: list[str] = field(default_factory=list)
    headlines: list[str] = field(default_factory=list)


@dataclass
class Analysis:
    directions: dict[str, str]
    reason: str
