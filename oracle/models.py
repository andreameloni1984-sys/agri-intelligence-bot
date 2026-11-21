from dataclasses import dataclass, field


# kind: (official title prefix, short Telegram label)
EVENTS = {
    "cpi": ("Consumer Price Index", "CPI USA"),
    "ppi": ("Producer Price Index", "PPI USA"),
    "pce": ("Personal Income and Outlays", "PCE USA"),
    "nfp": ("Employment Situation", "Occupazione USA (NFP)"),
    "claims": ("Unemployment Insurance Weekly Claims", "Richieste di disoccupazione USA"),
    "eia": ("Weekly Petroleum Status Report", "Scorte petrolifere EIA"),
    "fomc": ("FOMC policy decision", "Decisione FOMC"),
    "wasde": ("USDA WASDE", "USDA WASDE"),
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
    scenario_source: str = ""


@dataclass
class Analysis:
    directions: dict[str, str]
    reason: str
