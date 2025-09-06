# Home.py
import streamlit as st
from db_core import init_schema_and_seed, get_conn
from security import verify_credentials, ensure_admin_seed, list_user_companies
from pathlib import Path

st.set_page_config(page_title="Locadora Finance • Home", layout="wide", initial_sidebar_state="collapsed")

# 1) Garantir schema/seed (streamlit cloud reinicia container)
init_schema_and_seed()
ensure_admin_seed()

# 2) Sessão
if "user" not in st.session_state:
    st.session_state.user = None
if "company" not in st.session_state:
    st.session_state.company = None

def do_login():
    st.title("🔐 Acesso ao Sistema")
    with st.form("login"):
        email = st.text_input("E-mail", value="admin@admin")
        pwd = st.text_input("Senha", type="password", value="admin")
        ok = st.form_submit_button("Entrar")
        if ok:
            u = verify_credentials(email, pwd)
            if u:
                st.session_state.user = u
                st.rerun()
            else:
                st.error("Credenciais inválidas")

def choose_company():
    st.title("🏢 Selecione a Empresa")
    companies = list_user_companies(st.session_state.user["id"])
    # fallback: se user não tem vínculo, mostrar todas para admin
    if not companies and st.session_state.user["role"] == "admin":
        with get_conn() as conn:
            companies = conn.execute("SELECT * FROM companies ORDER BY razao_social").fetchall()
    if not companies:
        st.info("Nenhuma empresa vinculada. Vá em 📦 Empresas para cadastrar e vincular.")
        return
    labels = {c["id"]: f'{c["razao_social"]} ({c["regime"]})' for c in companies}
    selected = st.selectbox("Empresa", options=[c["id"] for c in companies], format_func=lambda x: labels[x])
    if st.button("Entrar na empresa"):
        with get_conn() as conn:
            st.session_state.company = dict(conn.execute("SELECT * FROM companies WHERE id=?", (selected,)).fetchone())
        st.rerun()

# 3) Fluxo
if not st.session_state.user:
    do_login()
elif not st.session_state.company:
    choose_company()
else:
    st.sidebar.success(f'Usuário: {st.session_state.user["name"]} ({st.session_state.user["role"]})')
    st.sidebar.info(f'Empresa: {st.session_state.company["razao_social"]}')
    st.title("👋 Bem-vindo(a) à Locadora Finance")
    st.write("Use o menu **Pages** (barra lateral) para navegar entre os módulos.")
    st.markdown("""
- **📦 Empresas**: cadastro de empresas e (para admin) vincular usuários.
- **👥 Clientes**: cadastro de clientes.
- **🧑‍🔧 Colaboradores & Férias**: cadastro e controle de férias/afastamentos.
- **🛠️ Equipamentos & Manutenção**: estoque, docs e manutenções.
- **🧾 Serviços & OS**: serviços, vínculo de colaboradores/equipamentos, OS, geração de receitas/parcelas, fiscal/gerencial.
- **💸 Despesas**: despesas à vista/parceladas, quitação com data automática.
- **💰 Receitas**: recebíveis e baixas.
- **📊 Caixa & Dashboards**: fluxo de caixa e KPIs.
- **⚖️ Impostos Comparativo**: simulação por regime (parametrizável).
- **🧮 Custos & Salários**: composição de custos.
""")
    if st.button("🔓 Sair"):
        st.session_state.user = None
        st.session_state.company = None
        st.rerun()
