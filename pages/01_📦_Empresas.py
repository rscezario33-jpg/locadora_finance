from session_helpers import require_company_with_picker
import streamlit as st
from db_core import get_conn
from utils import cnpj_mask

st.set_page_config(page_title="📦 Empresas", layout="wide")

def require_login():
    if "user" not in st.session_state or st.session_state.user is None:
        st.stop()

require_login()

st.title("📦 Empresas")

colA, colB = st.columns([1,1])

with colA:
    st.subheader("Cadastrar / Editar")
    with st.form("form_empresa"):
        cnpj = st.text_input("CNPJ")
        razao = st.text_input("Razão Social")
        fantasia = st.text_input("Nome Fantasia")
        endereco = st.text_area("Endereço")
        regime = st.selectbox("Regime", ["simples","lucro_real","lucro_presumido"])
        submit = st.form_submit_button("Salvar")
        if submit:
            with get_conn() as conn:
                conn.execute("""INSERT INTO companies(cnpj, razao_social, nome_fantasia, endereco, regime)
                                VALUES (?,?,?,?,?)""",
                             (cnpj, razao, fantasia, endereco, regime))
                conn.commit()
            st.success("Empresa salva!")

with colB:
    st.subheader("Empresas Cadastradas")
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM companies ORDER BY razao_social").fetchall()
    for r in rows:
        st.markdown(f"**{r['razao_social']}**  \n{cnpj_mask(r['cnpj'])} — *{r['regime']}*  \n{r['endereco'] or ''}")
        if st.session_state.user["role"] == "admin":
            # vínculo usuário-empresa
            with st.expander("Vincular usuários"):
                email = st.text_input(f"E-mail do usuário (empresa {r['id']})", key=f"email_{r['id']}")
                if st.button("Vincular", key=f"v_{r['id']}"):
                    u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                    if u:
                        conn.execute("INSERT OR IGNORE INTO user_companies(user_id, company_id) VALUES (?,?)", (u["id"], r["id"]))
                        conn.commit()
                        st.success("Usuário vinculado.")
                    else:
                        st.error("Usuário não encontrado.")
        st.divider()

