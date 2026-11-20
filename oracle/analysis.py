"""Transparent economic hypotheses for a single scheduled release."""
import re

from .models import Analysis

MACRO_ASSETS = {
    "cpi": ("Gold", "Platinum"),
    "ppi": ("Gold", "Copper"),
    "pce": ("Gold", "Platinum"),
    "nfp": ("Gold", "Copper"),
    "claims": ("Gold", "Copper"),
    "fomc": ("Gold", "Platinum"),
}
THRESHOLDS = {
    "headline_mom_pct": 0, "core_mom_pct": 0, "upper_pct": 0,
    "claims": 0, "payrolls": 0, "unemployment_pct": 0,
    "crude_mb": 0, "gasoline_mb": 0, "distillates_mb": 0,
}
UNKNOWN = "NON DETERMINABILE"


def _difference(metric, values, baseline):
    if metric not in values or metric not in baseline:
        return 0
    change = values[metric] - baseline[metric]
    return change if abs(change) >= THRESHOLDS[metric] else 0


def _direction(pressure):
    return "LONG" if pressure > 0 else "SHORT" if pressure < 0 else UNKNOWN


def _unknown(assets, reason):
    return Analysis(dict.fromkeys(assets, UNKNOWN), reason)


def interpret(kind, release, context, preliminary=False):
    values = context.scenario if preliminary else release.actual
    baseline = context.consensus
    previous = {**context.previous, **release.previous}
    if kind == "wasde":
        movements = []
        for asset in ("Wheat", "Corn", "Soybeans"):
            period = context.periods.get(asset) if preliminary else release.periods.get(asset)
            benchmark = baseline.get(asset) if period and context.periods.get(asset) == period else None
            label = "al consenso"
            if benchmark is None and not preliminary and period and asset in release.previous:
                benchmark, label = release.previous[asset], "alla stima USDA precedente"
            if asset in values and benchmark is not None and benchmark > 0:
                change = (values[asset] - benchmark) / benchmark
                movements.append((asset, change, label))
        movements.sort(key=lambda item: abs(item[1]), reverse=True)
        selected = movements[:2]
        available = sorted(values, key=lambda asset: asset not in release.periods)
        for asset in available:
            if len(selected) < 2 and all(row[0] != asset for row in selected):
                selected.append((asset, 0, ""))
        reasons = [f"{asset}: scorte finali USA {change:+.1%} rispetto {label}"
                   for asset, change, label in selected if abs(change) > 0]
        return Analysis(
            {asset: _direction(-change if abs(change) > 0 else 0) for asset, change, _ in selected},
            ". ".join(reasons) or "Scostamenti sulle scorte finali USA insufficienti o senza confronto omogeneo.",
        )

    assets = ("WTI", "Brent") if kind == "eia" else MACRO_ASSETS[kind]
    if kind == "eia":
        crude = _difference("crude_mb", values, baseline)
        products = [_difference(metric, values, baseline) for metric in ("gasoline_mb", "distillates_mb")]
        if crude and any(crude * product < 0 and abs(product) >= abs(crude) for product in products):
            return _unknown(assets, "Scorte di greggio e prodotti raffinati indicano pressioni opposte.")
        counterforce = "build|rise|increase" if crude > 0 else "draw|fall|decline"
        if not preliminary and crude and any(
            re.search(rf"\b(?:offset|counter|outweigh)\w* (?:the |a |an )?(?:U\.S\. )?"
                      rf"(?:crude (?:oil )?)?(?:stocks? |inventor(?:y|ies) )?(?:{counterforce})\b", title, re.I)
            and re.search(r"\b(?:crude|EIA)\b", title, re.I)
            for title in context.headlines
        ):
            return _unknown(assets, "Reuters riporta un fattore che compensa la pressione delle scorte di greggio.")
        if not crude:
            return _unknown(assets, "Sorpresa sulle scorte di greggio insufficiente o consenso indisponibile.")
        return Analysis(dict.fromkeys(assets, _direction(-crude)),
                        f"Scorte di greggio {crude:+.2f} mln barili rispetto al consenso. Possibile pressione "
                        f"{'ribassista' if crude > 0 else 'rialzista'} sul petrolio.")

    if kind in {"cpi", "ppi", "pce"}:
        headline = _difference("headline_mom_pct", values, baseline)
        core = _difference("core_mom_pct", values, baseline)
        if headline * core < 0:
            return _unknown(assets, "Inflazione generale e di fondo sorprendono in direzioni opposte.")
        surprise = core or headline
        if not surprise:
            return _unknown(assets, "Sorpresa sull’inflazione insufficiente o consenso indisponibile.")
        if kind in {"cpi", "pce"} and not core:
            assets = ("Gold", "Copper")
        return Analysis(dict.fromkeys(assets, _direction(-surprise)),
                        f"Inflazione {'di fondo' if core else 'generale'} {surprise:+.2f} punti sul consenso. "
                        "Possibile effetto su tassi e dollaro.")

    if kind == "fomc":
        surprise = _difference("upper_pct", values, baseline)
        if not surprise:
            return _unknown(assets, "Tasso in linea con il consenso o consenso indisponibile. Guidance senza confronto verificabile.")
        return Analysis(dict.fromkeys(assets, _direction(-surprise)),
                        f"Limite superiore dei tassi Fed {surprise:+.2f} punti sul consenso. Possibile effetto su dollaro e rendimenti.")

    if kind == "claims":
        surprise = -_difference("claims", values, baseline)
        revision = release.revised.get("claims", previous.get("claims", 0)) - previous.get("claims", 0)
        if surprise and surprise * revision > 0 and abs(revision) >= abs(surprise):
            return _unknown(assets, "La revisione delle richieste precedenti contrasta con la sorpresa corrente.")
        reason = f"Richieste {-surprise:+,.0f} sul consenso. Possibili effetti opposti su rendimenti e domanda industriale."
    else:
        surprise = _difference("payrolls", values, baseline)
        unemployment = _difference("unemployment_pct", values, baseline)
        revisions = sum(value - release.previous[key] for key, value in release.revised.items()
                        if key in release.previous and key.startswith("payrolls"))
        if surprise and (surprise * unemployment > 0 or surprise * revisions < 0 and abs(revisions) >= abs(surprise)):
            return _unknown(assets, "Occupazione, disoccupazione o revisioni segnalano impulsi contrastanti.")
        reason = f"Nuovi impieghi {surprise:+,.0f} sul consenso. Possibili effetti opposti su rendimenti e domanda industriale."
    if not surprise:
        return _unknown(assets, "Sorpresa sul lavoro insufficiente o consenso indisponibile.")
    return Analysis({assets[0]: _direction(-surprise), assets[1]: _direction(surprise)}, reason)
