"""Transparent economic hypotheses for a single scheduled release.

Before publication the hypothesis compares an independent, attributed estimate
(``context.scenario``) with the consensus; after publication it compares the
official figure with the consensus. Without either comparison the direction is
reported as not determinable instead of being guessed.
"""
from .models import Analysis

MACRO_ASSETS = {
    "cpi": ("Gold", "Platinum"),
    "ppi": ("Gold", "Copper"),
    "pce": ("Gold", "Platinum"),
    "nfp": ("Gold", "Copper"),
    "claims": ("Gold", "Copper"),
    "fomc": ("Gold", "Platinum"),
}
UNKNOWN = "NON DETERMINABILE"


def _difference(metric, values, baseline):
    if metric not in values or metric not in baseline:
        return 0
    return round(values[metric] - baseline[metric], 6)


def _direction(pressure):
    return "LONG" if pressure > 0 else "SHORT" if pressure < 0 else UNKNOWN


def _unknown(assets, reason):
    return Analysis(dict.fromkeys(assets, UNKNOWN), reason)


DEFAULT_ASSETS = {**MACRO_ASSETS, "eia": ("WTI", "Brent"), "wasde": ("Corn", "Soybeans")}


def _fmt(values):
    return ", ".join(f"{key} {value:g}" for key, value in sorted(values.items())) or "n/d"


def interpret(kind, release, context, preliminary=False):
    if preliminary and not context.scenario:
        return _unknown(DEFAULT_ASSETS[kind],
                        "Previsione non disponibile: nessuna stima indipendente verificabile del dato. "
                        f"Consenso: {_fmt(context.consensus)}. Precedente: {_fmt(context.previous)}.")
    if preliminary and kind != "wasde" and not set(context.scenario) & set(context.consensus):
        return _unknown(DEFAULT_ASSETS[kind],
                        f"Previsione non disponibile: stima {context.scenario_source or 'indipendente'} "
                        f"({_fmt(context.scenario)}) senza consenso confrontabile.")
    result = _interpret(kind, release, context, preliminary)
    if preliminary and context.scenario_source:
        result.reason = f"Stima {context.scenario_source} confrontata con il consenso. {result.reason}"
    return result


def _interpret(kind, release, context, preliminary):
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
            ". ".join(reasons) or "Scorte finali USA invariate o senza confronto omogeneo.",
        )

    assets = ("WTI", "Brent") if kind == "eia" else MACRO_ASSETS[kind]
    if kind == "eia":
        crude = _difference("crude_mb", values, baseline)
        products = [_difference(metric, values, baseline) for metric in ("gasoline_mb", "distillates_mb")]
        if crude and any(crude * product < 0 and abs(product) >= abs(crude) for product in products):
            return _unknown(assets, "Scorte di greggio e prodotti raffinati indicano pressioni opposte.")
        if not crude:
            return _unknown(assets, "Scorte di greggio in linea con il consenso o consenso indisponibile.")
        return Analysis(dict.fromkeys(assets, _direction(-crude)),
                        f"Scorte di greggio {values['crude_mb']:+.2f} mln barili contro consenso {baseline['crude_mb']:+.2f} "
                        f"({crude:+.2f}). Offerta {'più abbondante' if crude > 0 else 'più scarsa'} del previsto: "
                        f"possibile pressione {'ribassista' if crude > 0 else 'rialzista'} sul petrolio.")

    if kind in {"cpi", "ppi", "pce"}:
        headline = _difference("headline_mom_pct", values, baseline)
        core = _difference("core_mom_pct", values, baseline)
        if headline * core < 0:
            return _unknown(assets, "Inflazione generale e di fondo sorprendono in direzioni opposte.")
        surprise = core or headline
        if not surprise:
            return _unknown(assets, "Inflazione in linea con il consenso o consenso indisponibile.")
        if kind in {"cpi", "pce"} and not core:
            assets = ("Gold", "Copper")
        metric = "core_mom_pct" if core else "headline_mom_pct"
        return Analysis(dict.fromkeys(assets, _direction(-surprise)),
                        f"Inflazione {'di fondo' if core else 'generale'} m/m {values[metric]:.1f}% contro consenso "
                        f"{baseline[metric]:.1f}%: {'superiore' if surprise > 0 else 'inferiore'} alle attese, possibile "
                        f"{'rafforzamento' if surprise > 0 else 'indebolimento'} di dollaro e rendimenti.")

    if kind == "fomc":
        surprise = _difference("upper_pct", values, baseline)
        if not surprise:
            return _unknown(assets, "Tasso in linea con il consenso o consenso indisponibile. Guidance senza confronto verificabile.")
        return Analysis(dict.fromkeys(assets, _direction(-surprise)),
                        f"Limite superiore Fed {values['upper_pct']:.2f}% contro consenso {baseline['upper_pct']:.2f}%: "
                        f"politica {'più restrittiva' if surprise > 0 else 'più espansiva'} del previsto, possibile effetto su dollaro e rendimenti.")

    if kind == "claims":
        surprise = -_difference("claims", values, baseline)
        revision = release.revised.get("claims", previous.get("claims", 0)) - previous.get("claims", 0)
        if surprise and surprise * revision > 0 and abs(revision) >= abs(surprise):
            return _unknown(assets, "La revisione delle richieste precedenti contrasta con la sorpresa corrente.")
        reason = (f"Richieste {values.get('claims', 0):,.0f} contro consenso {baseline.get('claims', 0):,.0f}: lavoro "
                  f"{'più solido' if surprise > 0 else 'più debole'} del previsto. Effetto opposto su oro (rendimenti) "
                  "e rame (domanda industriale).").replace(",", ".")
    else:
        surprise = _difference("payrolls", values, baseline)
        unemployment = _difference("unemployment_pct", values, baseline)
        revisions = sum(value - release.previous[key] for key, value in release.revised.items()
                        if key in release.previous and key.startswith("payrolls"))
        if surprise and (surprise * unemployment > 0 or surprise * revisions < 0 and abs(revisions) >= abs(surprise)):
            return _unknown(assets, "Occupazione, disoccupazione o revisioni segnalano impulsi contrastanti.")
        reason = (f"Nuovi impieghi {values.get('payrolls', 0):,.0f} contro consenso {baseline.get('payrolls', 0):,.0f}: lavoro "
                  f"{'più solido' if surprise > 0 else 'più debole'} del previsto. Effetto opposto su oro (rendimenti) "
                  "e rame (domanda industriale).").replace(",", ".")
    if not surprise:
        return _unknown(assets, "Dato sul lavoro in linea con il consenso o consenso indisponibile.")
    return Analysis({assets[0]: _direction(-surprise), assets[1]: _direction(surprise)}, reason)
