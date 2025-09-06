from session_helpers import require_company_with_picker
import streamlit as st
from datetime import date
from db_core import get_conn
from utils import add_months

st.set_page_config(page_title="💰 Receitas", layout="wide")

def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()
require_company()
cid = require_company_with_picker()

st.title("💰 Receitas (a receber)")

with get_conn() as conn:
    clients = conn.execute("SELECT id,nome FROM clients WHERE company_id=? ORDER BY nome", (cid,)).fetchall()
cli_map = {c["nome"]: c["id"] for c in clients}

with st.form("f_rev"):
    st.subheader("Lançar receita avulsa (opcional; serviços já geram automaticamente)")
    dt = st.date_input("Data de lançamento", value=date.today())
    cli = st.selectbox("Cliente", list(cli_map.keys()) if cli_map else [])
    desc = st.text_area("Descrição")
    valor = st.number_input("Valor total (R$)", min_value=0.0, step=0.01, format="%.2f")
    forma = st.selectbox("Forma de pagamento", ["PIX","TED","Boleto","Cartão","Dinheiro","Outro"])
    fiscal = st.toggle("Fiscal?", value=True)
    parcelas = st.number_input("Parcelas", min_value=1, max_value=120, value=1)
    ok = st.form_submit_button("Salvar")
    if ok:
        with get_conn() as conn:
            cur = conn.execute("""INSERT INTO revenues(company_id,service_id,client_id,descricao,forma_pagamento,data_lancamento,valor_total,parcelas,fiscal)
                                  VALUES (?,?,?,?,?,?,?,?,?)""",
                               (cid, None, cli_map.get(cli) if cli else None, desc, forma, dt.isoformat(), valor, parcelas, 1 if fiscal else 0))
            rev_id = cur.lastrowid
            par_val = round(valor/parcelas, 2)
            vals = [par_val]*parcelas
            dif = round(valor - sum(vals), 2)
            vals[-1] += dif
            for i in range(parcelas):
                due = add_months(dt, i)
                conn.execute("""INSERT INTO revenue_installments(revenue_id,num_parcela,due_date,amount)
                                VALUES (?,?,?,?)""",(rev_id, i+1, due.isoformat(), vals[i]))
            conn.commit()
        st.success("Receita lançada com parcelas geradas.")

st.divider()
st.subheader("Parcelas em aberto / recebimento")

with get_conn() as conn:
    rows = conn.execute("""
        SELECT ri.id, r.descricao, r.forma_pagamento, ri.num_parcela, ri.due_date, ri.amount
        FROM revenue_installments ri
        JOIN revenues r ON r.id=ri.revenue_id
        WHERE r.company_id=? AND ri.received=0
        ORDER BY date(ri.due_date) ASC
    """, (cid,)).fetchall()

st.dataframe([{k: r[k] for k in r.keys()} for r in rows], use_container_width=True)

ids = st.multiselect("Selecionar parcelas para receber", [r["id"] for r in rows])
if st.button("Receber selecionadas"):
    from datetime import datetime
    with get_conn() as conn:
        for pid in ids:
            conn.execute("UPDATE revenue_installments SET received=1, received_date=? WHERE id=?", (datetime.now().isoformat(), pid))
        conn.commit()
    st.success("Parcelas recebidas.")
    st.rerun()

