import streamlit as st
from db_core import get_conn

st.set_page_config(page_title="👥 Clientes", layout="wide")

def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()

require_company()
cid = st.session_state.company["id"]

st.title("👥 Clientes")

with st.form("form_client"):
    nome = st.text_input("Nome/Razão Social")
    doc = st.text_input("CNPJ/CPF")
    email = st.text_input("E-mail")
    phone = st.text_input("Telefone")
    address = st.text_area("Endereço")
    ok = st.form_submit_button("Salvar")
    if ok:
        with get_conn() as conn:
            conn.execute("""INSERT INTO clients(company_id,nome,doc,email,phone,address)
                            VALUES (?,?,?,?,?,?)""", (cid, nome, doc, email, phone, address))
            conn.commit()
        st.success("Cliente salvo.")

st.subheader("Clientes da empresa")
with get_conn() as conn:
    rows = conn.execute("SELECT * FROM clients WHERE company_id=? ORDER BY nome", (cid,)).fetchall()
st.dataframe([{k: r[k] for k in r.keys()} for r in rows], use_container_width=True)
