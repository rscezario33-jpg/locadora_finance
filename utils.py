# utils.py
from datetime import date
from dateutil.relativedelta import relativedelta

def add_months(d: date, months: int) -> date:
    return d + relativedelta(months=months)

def cnpj_mask(cnpj: str) -> str:
    s = ''.join(filter(str.isdigit, cnpj or ""))
    if len(s) == 14:
        return f"{s[0:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:14]}"
    return cnpj

def compute_vacation_periods(adm: date, n_cycles: int = 3):
    # períodos aquisitivo/concessivo futuros a partir da admissão
    periods = []
    start = adm
    for _ in range(n_cycles):
        aquis_inicio = start
        aquis_fim = add_months(aquis_inicio, 12) - relativedelta(days=1)
        conc_inicio = add_months(aquis_fim, 1)
        conc_fim = add_months(conc_inicio, 12) - relativedelta(days=1)
        periods.append({
            "aquisitivo_inicio": aquis_inicio,
            "aquisitivo_fim": aquis_fim,
            "concessivo_inicio": conc_inicio,
            "concessivo_fim": conc_fim
        })
        start = add_months(aquis_inicio, 12)
    return periods

def month_range(d: date, months: int):
    for i in range(months):
        yield add_months(d, i)
