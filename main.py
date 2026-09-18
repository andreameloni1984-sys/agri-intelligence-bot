from database import init_db
from sources.ismea_market import parse_ovicaprini, parse_lattiero_caseari
from sources.sardegna_bandi import fetch_bandi
from engines.intelligence import report

if __name__ == "__main__":
    init_db()
    prices = parse_ovicaprini() + parse_lattiero_caseari()
    grants = fetch_bandi()
    print(report(prices, grants))
