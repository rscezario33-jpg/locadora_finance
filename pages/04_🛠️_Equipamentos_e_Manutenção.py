import streamlit as st
from db_core import get_conn

st.set_page_config(page_title="🛠️ Equipamentos", layout="wide")

def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()
require_company()
cid = st.session_state.company["id"]

st.title("🛠️ Equipamentos & Manutenção")

tab1, tab2, tab3 = st.tabs(["Cadastro", "Documentos", "Manutenções"])

with tab1:
    with st.form("f_eq"):
        codigo = st.text_input("Código")
        desc = st.text_input("Descrição")
        tipo = st.text_input("Tipo (veículo, máquina, etc.)")
        placa = st.text_input("Placa")
        chassi = st.text_input("Chassi")
        doc_venc = st.date_input("Vencimento do documento")
        manut_km = st.number_input("KM base p/ manutenção", min_value=0, step=500)
        manut_data = st.date_input("Data base p/ manutenção")
        obs = st.text_area("Observações")
        ok = st.form_submit_button("Salvar")
        if ok:
            with get_conn() as conn:
                conn.execute("""INSERT INTO equipment(company_id,codigo,descricao,tipo,placa,chassi,doc_vencimento,manut_km,manut_data,observacao)
                                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                             (cid, codigo, desc, tipo, placa, chassi,
                              doc_venc.isoformat() if doc_venc else None,
                              manut_km,
                              manut_data.isoformat() if manut_data else None,
                              obs))
                conn.commit()
            st.success("Equipamento salvo.")

    with get_conn() as conn:
        eqs = conn.execute("SELECT * FROM equipment WHERE company_id=? ORDER BY descricao", (cid,)).fetchall()
    st.dataframe([{k: r[k] for k in r.keys()} for r in eqs], use_container_width=True)

with tab2:
    with get_conn() as conn:
        eqs = conn.execute("SELECT id, descricao FROM equipment WHERE company_id=? ORDER BY descricao", (cid,)).fetchall()
    mapa = {e["descricao"]: e["id"] for e in eqs}
    nome = st.selectbox("Equipamento", list(mapa.keys()) if mapa else [])
    if nome:
        eid = mapa[nome]
        with st.form("doc_eq"):
            dn = st.text_input("Nome do documento (ex: CRLV, seguro)")
            val = st.date_input("Validade")
            okd = st.form_submit_button("Salvar doc")
            if okd:
                with get_conn() as conn:
                    conn.execute("""INSERT INTO equipment_docs(equipment_id,nome,dt_validade)
                                    VALUES (?,?,?)""", (eid, dn, val.isoformat()))
                    conn.commit()
                st.success("Documento salvo.")
        with get_conn() as conn:
            docs = conn.execute("SELECT * FROM equipment_docs WHERE equipment_id=? ORDER BY dt_validade DESC", (eid,)).fetchall()
        st.dataframe([{k: r[k] for k in r.keys()} for r in docs], use_container_width=True)

with tab3:
    with get_conn() as conn:
        eqs = conn.execute("SELECT id, descricao FROM equipment WHERE company_id=? ORDER BY descricao", (cid,)).fetchall()
    mapa = {e["descricao"]: e["id"] for e in eqs}
    nome = st.selectbox("Equipamento p/ manutenção", list(mapa.keys()) if mapa else [], key="eq_manut")
    if nome:
        eid = mapa[nome]
        with st.form("man_eq"):
            tipo = st.selectbox("Tipo", ["preventiva", "corretiva"])
            dt = st.date_input("Data")
            km = st.number_input("KM", min_value=0, step=100)
            desc = st.text_area("Descrição")
            custo = st.number_input("Custo (R$)", min_value=0.0, step=0.01, format="%.2f")
            okm = st.form_submit_button("Salvar manutenção")
            if okm:
                with get_conn() as conn:
                    conn.execute("""INSERT INTO equipment_maintenance(equipment_id,tipo,data,km,descricao,custo)
                                    VALUES (?,?,?,?,?,?)""", (eid, tipo, dt.isoformat(), km, desc, custo))
                    conn.commit()
                st.success("Manutenção lançada.")
        with get_conn() as conn:
            mans = conn.execute("SELECT * FROM equipment_maintenance WHERE equipment_id=? ORDER BY data DESC", (eid,)).fetchall()
        st.dataframe([{k: r[k] for k in r.keys()} for r in mans], use_container_width=True)
