import streamlit as st
from db_core import get_conn

st.set_page_config(page_title="🧮 Custos e Salários", layout="wide")

def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()
require_company()
cid = st.session_state.company["id"]

st.title("🧮 Custos de Pessoal")

st.caption("Composição simples: salário + encargos (%) configuráveis + diárias quando aplicável.")

enc_col, sal_col = st.columns([1,2])

with enc_col:
    inss = st.number_input("Encargos (% INSS/FGTS/médias)", min_value=0.0, step=0.5, value=35.0, format="%.2f")
    benef = st.number_input("Benefícios (% estimado)", min_value=0.0, step=0.5, value=5.0, format="%.2f")
    outros = st.number_input("Outros custos (%)", min_value=0.0, step=0.5, value=3.0, format="%.2f")
    total_pct = inss + benef + outros
    st.info(f"Percentual total aplicado sobre salário: **{total_pct:.2f}%**")

with sal_col:
    with get_conn() as conn:
        emps = conn.execute("SELECT nome, funcao, salario, diaria FROM employees WHERE company_id=? ORDER BY nome", (cid,)).fetchall()
    rows = []
    for e in emps:
        sal = float(e["salario"] or 0)
        custo = sal * (1 + total_pct/100)
        rows.append({
            "Nome": e["nome"],
            "Função": e["funcao"],
            "Salário": sal,
            "Custo total estimado": round(custo, 2),
            "Diária (fixa)": float(e["diaria"] or 0)
        })
    if rows:
        import pandas as pd
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Sem colaboradores cadastrados.")
