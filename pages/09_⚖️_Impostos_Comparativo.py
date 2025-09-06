from session_helpers import require_company_with_picker
import streamlit as st
import pandas as pd
from db_core import get_conn

st.set_page_config(page_title="⚖️ Impostos (Comparativo)", layout="wide")

def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()
require_company()
cid = require_company_with_picker()

st.title("⚖️ Simulação de Impostos por Regime (parâmetros)")

st.caption("As alíquotas abaixo são **parametrizáveis**. Ajuste conforme sua regra fiscal. O cálculo considera receitas **fiscais**.")

with get_conn() as conn:
    rules = conn.execute("SELECT * FROM tax_rules ORDER BY regime, min_revenue").fetchall()
df = pd.DataFrame([{k: r[k] for k in r.keys()} for r in rules])
st.dataframe(df, use_container_width=True)

with st.expander("Adicionar/editar regra"):
    with st.form("f_rule"):
        regime = st.selectbox("Regime", ["simples","lucro_presumido","lucro_real"])
        min_rev = st.number_input("Faixa mínima (R$)", min_value=0.0, step=100.0)
        max_rev = st.number_input("Faixa máxima (R$) (0 = sem teto)", min_value=0.0, step=100.0, value=0.0)
        rate = st.number_input("Alíquota (%)", min_value=0.0, step=0.01, format="%.2f")
        ok = st.form_submit_button("Salvar")
        if ok:
            with get_conn() as conn:
                conn.execute("""INSERT INTO tax_rules(regime,min_revenue,max_revenue,rate)
                                VALUES (?,?,?,?)""",
                             (regime, min_rev, None if max_rev==0 else max_rev, rate))
                conn.commit()
            st.success("Regra salva.")
            st.rerun()

st.divider()
st.subheader("Comparativo mensal por regime")

mes = st.selectbox("Mês (YYYY-MM)", options=["(todos)"] + [
    r["m"] for r in get_conn().execute("""
        SELECT strftime('%Y-%m', data_lancamento) AS m
        FROM revenues WHERE company_id=? AND fiscal=1
        GROUP BY m ORDER BY m DESC
    """, (cid,)).fetchall()
])

query = """
SELECT strftime('%Y-%m', ri.due_date) AS m, SUM(ri.amount) AS valor
FROM revenue_installments ri
JOIN revenues r ON r.id=ri.revenue_id
WHERE r.company_id=? AND r.fiscal=1
{and_mes}
GROUP BY m
ORDER BY m
"""
and_mes = "" if mes == "(todos)" else "AND strftime('%Y-%m', ri.due_date)=?"
params = (cid,) if mes == "(todos)" else (cid, mes)

with get_conn() as conn:
    revs = conn.execute(query.format(and_mes=and_mes), params).fetchall()
    rules = conn.execute("SELECT * FROM tax_rules").fetchall()

if not revs:
    st.info("Sem receitas fiscais no período.")
else:
    base = pd.DataFrame(revs)
    base["valor"] = base["valor"].astype(float)

    regimes = ["simples","lucro_presumido","lucro_real"]
    out = {}
    for reg in regimes:
        # aplica maior faixa aplicável por mês (modelo simplificado)
        rates = [r for r in rules if r["regime"] == reg]
        def aplica_taxa(v):
            aplicaveis = [r for r in rates if (v >= r["min_revenue"]) and (r["max_revenue"] is None or v <= r["max_revenue"])]
            if not aplicaveis and rates:
                # se não achou faixa, usa a maior (max_revenue None)
                aplicaveis = [sorted(rates, key=lambda x: (x["max_revenue"] is None, x["max_revenue"] or 0))[-1]]
            return (aplicaveis[0]["rate"] if aplicaveis else 0.0) * v / 100.0
        out[reg] = base.assign(imposto=base["valor"].map(aplica_taxa))["imposto"].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Simples (estimado)", f"R$ {out['simples']:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
    col2.metric("Lucro Presumido (estimado)", f"R$ {out['lucro_presumido']:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
    col3.metric("Lucro Real (estimado)", f"R$ {out['lucro_real']:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))

    st.caption("Obs.: modelo **simplificado** para estimativa. Ajuste as faixas/aliquotas em **tax_rules** e/ou evolua as fórmulas conforme as regras reais da empresa.")

