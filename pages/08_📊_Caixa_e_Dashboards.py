from session_helpers import require_company_with_picker
import streamlit as st
import pandas as pd
from db_core import get_conn

st.set_page_config(page_title="📊 Caixa & Dashboards", layout="wide")

def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()
require_company()
cid = require_company_with_picker()

st.title("📊 Fluxo de Caixa e KPIs")

with get_conn() as conn:
    # a pagar
    pagar = conn.execute("""
        SELECT date(ei.due_date) as data, SUM(ei.amount) as valor
        FROM expense_installments ei
        JOIN expenses e ON e.id=ei.expense_id
        WHERE e.company_id=?
        GROUP BY date(ei.due_date)
        ORDER BY 1
    """,(cid,)).fetchall()
    # a receber
    receber = conn.execute("""
        SELECT date(ri.due_date) as data, SUM(ri.amount) as valor
        FROM revenue_installments ri
        JOIN revenues r ON r.id=ri.revenue_id
        WHERE r.company_id=?
        GROUP BY date(ri.due_date)
        ORDER BY 1
    """,(cid,)).fetchall()

df_out = pd.DataFrame(pagar, columns=["data","valor"])
df_in  = pd.DataFrame(receber, columns=["data","valor"])

df_out["data"] = pd.to_datetime(df_out["data"])
df_in["data"]  = pd.to_datetime(df_in["data"])

# status atual (vencidas e não pagas/recebidas)
with get_conn() as conn:
    venc_out = conn.execute("""
        SELECT SUM(ei.amount) AS v
        FROM expense_installments ei
        JOIN expenses e ON e.id=ei.expense_id
        WHERE e.company_id=? AND ei.paid=0 AND date(ei.due_date) < date('now')
    """,(cid,)).fetchone()["v"] or 0
    venc_in = conn.execute("""
        SELECT SUM(ri.amount) AS v
        FROM revenue_installments ri
        JOIN revenues r ON r.id=ri.revenue_id
        WHERE r.company_id=? AND ri.received=0 AND date(ri.due_date) < date('now')
    """,(cid,)).fetchone()["v"] or 0

col1, col2, col3 = st.columns(3)
col1.metric("🔻 Vencidas (a pagar)", f"R$ {venc_out:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
col2.metric("🔺 Vencidas (a receber)", f"R$ {venc_in:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
saldo_estimado = (df_in["valor"].sum() if not df_in.empty else 0) - (df_out["valor"].sum() if not df_out.empty else 0)
col3.metric("💼 Saldo estimado (todas as datas)", f"R$ {saldo_estimado:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))

st.subheader("Curva de entradas x saídas por data")
if df_in.empty and df_out.empty:
    st.info("Sem dados para exibir.")
else:
    import plotly.express as px
    df_in["tipo"] = "Entradas"
    df_out["tipo"] = "Saídas"
    df = pd.concat([df_in, df_out], ignore_index=True)
    fig = px.line(df, x="data", y="valor", color="tipo", markers=True)
    st.plotly_chart(fig, use_container_width=True)

