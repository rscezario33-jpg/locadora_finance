import streamlit as st
from datetime import date
from db_core import get_conn
from utils import add_months

st.set_page_config(page_title="🧾 Serviços & OS", layout="wide")

def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()
require_company()
cid = st.session_state.company["id"]

st.title("🧾 Serviços & Ordem de Serviço")

with get_conn() as conn:
    clients = conn.execute("SELECT id,nome FROM clients WHERE company_id=? ORDER BY nome", (cid,)).fetchall()
    employees = conn.execute("SELECT id,nome FROM employees WHERE company_id=? ORDER BY nome", (cid,)).fetchall()
    eqs = conn.execute("SELECT id,descricao FROM equipment WHERE company_id=? AND ativo=1 ORDER BY descricao", (cid,)).fetchall()

cli_map = {c["nome"]: c["id"] for c in clients}
emp_map = {e["nome"]: e["id"] for e in employees}
eq_map = {e["descricao"]: e["id"] for e in eqs}

with st.form("f_srv"):
    st.subheader("Cadastrar Serviço")
    dt = st.date_input("Data do serviço", value=date.today())
    cli = st.selectbox("Cliente", list(cli_map.keys()) if cli_map else [])
    desc = st.text_area("Descrição dos serviços")
    valor = st.number_input("Valor total (R$)", min_value=0.0, step=0.01, format="%.2f")
    forma = st.selectbox("Forma de pagamento", ["PIX","TED","Boleto","Cartão","Dinheiro","Outro"])
    parcelas = st.number_input("Parcelas", min_value=1, max_value=60, value=1)
    fiscal = st.toggle("Fiscal?", value=True, help="Marque para integrar ao cálculo de impostos. Desmarcado = gerencial")
    vinc_emps = st.multiselect("Vincular colaboradores", list(emp_map.keys()))
    vinc_eqs = st.multiselect("Vincular equipamentos", list(eq_map.keys()))
    ok = st.form_submit_button("Salvar serviço e gerar OS/receita")
    if ok:
        with get_conn() as conn:
            cur = conn.execute("""INSERT INTO services(company_id,client_id,data,descricao,valor_total,forma_pagamento,parcelas,fiscal,status)
                                  VALUES (?,?,?,?,?,?,?,?,?)""",
                               (cid, cli_map.get(cli) if cli else None, dt.isoformat(), desc, valor, forma, parcelas, 1 if fiscal else 0, "aberta"))
            srv_id = cur.lastrowid
            for n in vinc_emps:
                conn.execute("INSERT OR IGNORE INTO service_employees(service_id,employee_id) VALUES (?,?)", (srv_id, emp_map[n]))
            for n in vinc_eqs:
                conn.execute("INSERT OR IGNORE INTO service_equipments(service_id,equipment_id) VALUES (?,?)", (srv_id, eq_map[n]))

            # gerar receita/parcelas
            cur2 = conn.execute("""INSERT INTO revenues(company_id,service_id,client_id,descricao,forma_pagamento,data_lancamento,valor_total,parcelas,fiscal)
                                   VALUES (?,?,?,?,?,?,?,?,?)""",
                                (cid, srv_id, cli_map.get(cli) if cli else None, f"Serviço #{srv_id} - {desc[:80]}", forma, dt.isoformat(), valor, parcelas, 1 if fiscal else 0))
            rev_id = cur2.lastrowid
            par_val = round(valor / parcelas, 2)
            # ajustar última parcela por arredondamento
            vals = [par_val] * parcelas
            dif = round(valor - sum(vals), 2)
            vals[-1] += dif
            for i in range(parcelas):
                due = add_months(dt, i)
                conn.execute("""INSERT INTO revenue_installments(revenue_id,num_parcela,due_date,amount)
                                VALUES (?,?,?,?)""", (rev_id, i+1, due.isoformat(), vals[i]))
            conn.commit()
        st.success(f"Serviço #{srv_id} salvo e OS gerada.")

st.divider()
st.subheader("Ordem de Serviço (visualização/impressão)")
srv_id_in = st.number_input("ID do serviço", min_value=1, step=1)
if st.button("Carregar OS"):
    with get_conn() as conn:
        srv = conn.execute("SELECT * FROM services WHERE id=? AND company_id=?", (srv_id_in, cid)).fetchone()
        if not srv:
            st.error("Serviço não encontrado.")
        else:
            cli = conn.execute("SELECT * FROM clients WHERE id=?", (srv["client_id"],)).fetchone() if srv["client_id"] else None
            emps = conn.execute("""SELECT e.* FROM employees e
                                   JOIN service_employees se ON se.employee_id=e.id
                                   WHERE se.service_id=?""", (srv_id_in,)).fetchall()
            eqs = conn.execute("""SELECT e.* FROM equipment e
                                  JOIN service_equipments se ON se.equipment_id=e.id
                                  WHERE se.service_id=?""", (srv_id_in,)).fetchall()

            st.markdown(f"""
### OS #{srv['id']}
**Cliente:** {cli['nome'] if cli else '-'}  
**Data:** {srv['data']}  
**Descrição:** {srv['descricao'] or '-'}  
**Valor total:** R$ {srv['valor_total']:.2f}  
**Forma/Parcelas:** {srv['forma_pagamento']} / {srv['parcelas']}  
**Classificação:** {"Fiscal" if srv['fiscal'] else "Gerencial"}  
""")
            with st.expander("Colaboradores vinculados"):
                st.write([e["nome"] for e in emps] or "-")
            with st.expander("Equipamentos vinculados"):
                st.write([e["descricao"] for e in eqs] or "-")

            # "Impressão" simples via HTML (o usuário pode salvar como PDF no navegador)
            html = f"""
<h2>Ordem de Serviço #{srv['id']}</h2>
<p><b>Cliente:</b> {cli['nome'] if cli else '-'}</p>
<p><b>Data:</b> {srv['data']}</p>
<p><b>Descrição:</b> {srv['descricao'] or '-'}</p>
<p><b>Valor total:</b> R$ {srv['valor_total']:.2f}</p>
<p><b>Forma/Parcelas:</b> {srv['forma_pagamento']} / {srv['parcelas']}</p>
<p><b>Classificação:</b> {'Fiscal' if srv['fiscal'] else 'Gerencial'}</p>
<p><b>Colaboradores:</b> {', '.join([e['nome'] for e in emps]) if emps else '-'}</p>
<p><b>Equipamentos:</b> {', '.join([e['descricao'] for e in eqs]) if eqs else '-'}</p>
"""
            st.download_button("⬇️ Baixar OS (HTML)", data=html, file_name=f"OS_{srv_id_in}.html", mime="text/html")
