import streamlit as st
from datetime import date
from db_core import get_conn
from utils import add_months

st.set_page_config(page_title="💸 Despesas", layout="wide")

def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()
require_company()
cid = st.session_state.company["id"]

st.title("💸 Despesas (a pagar)")

with st.form("f_exp"):
    st.subheader("Lançar despesa")
    fornecedor = st.text_input("Fornecedor")
    descricao = st.text_area("Descrição")
    forma = st.selectbox("Forma de pagamento", ["PIX","TED","Boleto","Cartão","Dinheiro","Outro"])
    dt = st.date_input("Data de lançamento", value=date.today())
    valor = st.number_input("Valor total (R$)", min_value=0.0, step=0.01, format="%.2f")
    parcelas = st.number_input("Parcelas", min_value=1, max_value=120, value=1)
    ok = st.form_submit_button("Salvar")
    if ok:
        with get_conn() as conn:
            cur = conn.execute("""INSERT INTO expenses(company_id,fornecedor,descricao,forma_pagamento,data_lancamento,valor_total,parcelas)
                                  VALUES (?,?,?,?,?,?,?)""",
                               (cid, fornecedor, descricao, forma, dt.isoformat(), valor, parcelas))
            exp_id = cur.lastrowid
            par_val = round(valor/parcelas, 2)
            vals = [par_val]*parcelas
            dif = round(valor - sum(vals), 2)
            vals[-1] += dif
            for i in range(parcelas):
                due = add_months(dt, i)
                conn.execute("""INSERT INTO expense_installments(expense_id,num_parcela,due_date,amount)
                                VALUES (?,?,?,?)""",(exp_id, i+1, due.isoformat(), vals[i]))
            conn.commit()
        st.success("Despesa lançada com parcelas geradas.")

st.divider()
st.subheader("Parcelas em aberto / pagamento")

with get_conn() as conn:
    rows = conn.execute("""
        SELECT ei.id, e.fornecedor, e.descricao, e.forma_pagamento, ei.num_parcela, ei.due_date, ei.amount
        FROM expense_installments ei
        JOIN expenses e ON e.id=ei.expense_id
        WHERE e.company_id=? AND ei.paid=0
        ORDER BY date(ei.due_date) ASC
    """, (cid,)).fetchall()

st.dataframe([{k: r[k] for k in r.keys()} for r in rows], use_container_width=True)

ids = st.multiselect("Selecionar parcelas para quitar", [r["id"] for r in rows])
if st.button("Quitar selecionadas"):
    from datetime import datetime
    with get_conn() as conn:
        for pid in ids:
            conn.execute("UPDATE expense_installments SET paid=1, paid_date=? WHERE id=?", (datetime.now().isoformat(), pid))
        conn.commit()
    st.success("Parcelas quitadas.")
    st.rerun()
