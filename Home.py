# Home.py
import streamlit as st
import datetime, bcrypt
from db_core import init_schema_and_seed, get_conn, USE_PG, DATABASE_URL
from security import verify_credentials, ensure_admin_seed, list_user_companies

# (opcional) roda migrações idempotentes se o arquivo existir
try:
    from init_db import migrate as _migrate
except Exception:
    _migrate = None

st.set_page_config(page_title="Locadora Finance • Home", layout="wide", initial_sidebar_state="expanded")

# 1) Garantir schema/seed/migração (Cloud pode reiniciar container)
init_schema_and_seed()
ensure_admin_seed()
if _migrate:
    try:
        _migrate()
    except Exception as _e:
        # evita quebrar a Home se migração falhar por detalhe de permissão
        pass

# 2) Sessão
if "user" not in st.session_state:
    st.session_state.user = None
if "company" not in st.session_state:
    st.session_state.company = None

# ---------- Fluxo: definir senha via token (?setpwd=token) ----------
def handle_set_password_token():
    # Compat com versões novas/antigas do Streamlit
    try:
        qp = st.query_params
    except Exception:
        qp = st.experimental_get_query_params()
    token = None
    if isinstance(qp, dict):
        v = qp.get("setpwd")
        if isinstance(v, list):
            token = v[0] if v else None
        else:
            token = v
    if not token:
        return False  # nada a fazer

    st.title("🔑 Definir nova senha")

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM password_reset_tokens WHERE token=?", (token,)).fetchone()
    if not row:
        st.error("Token inválido.")
        return True

    # checa se já usado
    used = row["used"]
    if used in (1, True, "1", "true", "t", "T"):
        st.error("Token já utilizado.")
        return True

    # checa expiração (armazenado como ISO UTC)
    try:
        exp = datetime.datetime.fromisoformat(row["expires_at"])
    except Exception:
        st.error("Token com data inválida.")
        return True
    if datetime.datetime.utcnow() > exp:
        st.error("Token expirado.")
        return True

    p1 = st.text_input("Nova senha", type="password")
    p2 = st.text_input("Confirmar senha", type="password")
    if st.button("Salvar senha", type="primary"):
        if not p1 or p1 != p2:
            st.warning("As senhas não conferem.")
        else:
            pw_hash = bcrypt.hashpw(p1.encode(), bcrypt.gensalt())
            with get_conn() as conn:
                conn.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, row["user_id"]))
                conn.execute("UPDATE password_reset_tokens SET used=? WHERE id=?", (1, row["id"]))
                conn.commit()
            st.success("Senha alterada com sucesso. Faça login novamente.")
            # Limpa usuário logado, se houver
            st.session_state.user = None
            st.session_state.company = None
    return True

# ---------- Login ----------
def do_login():
    st.title("🔐 Acesso ao Sistema")
    with st.form("login"):
        email = st.text_input("E-mail", value="admin@admin")
        pwd = st.text_input("Senha", type="password", value="admin")
        ok = st.form_submit_button("Entrar", type="primary")
        if ok:
            u = verify_credentials(email, pwd)
            if u:
                st.session_state.user = u
                st.rerun()
            else:
                st.error("Credenciais inválidas")

# ---------- Sidebar: usuário + seletor de empresa ----------
def sidebar_after_login():
    u = st.session_state.user
    st.sidebar.markdown(f"**Usuário:** {u['name']}  \n*Perfil:* `{u['role']}`")

    # Info do banco
    db_label = "Supabase Postgres" if USE_PG else "SQLite local"
    st.sidebar.caption(f"Banco: **{db_label}**")
    if USE_PG and DATABASE_URL:
        try:
            host = DATABASE_URL.split('@')[1].split('/')[0]
            st.sidebar.caption(f"Host: `{host}`")
        except Exception:
            pass

    # Carrega empresas vinculadas (ou todas, se admin sem vínculo)
    with get_conn() as conn:
        rows = list_user_companies(u["id"])
        if not rows and u["role"] == "admin":
            rows = conn.execute("SELECT * FROM companies ORDER BY razao_social").fetchall()

    if rows:
        labels = {r["id"]: f'{r["razao_social"]} ({r["regime"]})' for r in rows}
        ids = [r["id"] for r in rows]
        # seleciona padrão
        default_idx = 0
        if st.session_state.get("company"):
            try:
                default_idx = ids.index(st.session_state.company["id"])
            except Exception:
                default_idx = 0

        sel_id = st.sidebar.selectbox("🏢 Empresa ativa", ids, index=default_idx, format_func=lambda x: labels[x])
        # Atualiza sessão se mudou
        if (not st.session_state.get("company")) or (st.session_state.company["id"] != sel_id):
            with get_conn() as conn:
                st.session_state.company = dict(
                    conn.execute("SELECT * FROM companies WHERE id=?", (sel_id,)).fetchone()
                )
        st.sidebar.success(f"Empresa: {st.session_state.company['razao_social']}")
    else:
        st.sidebar.warning("Nenhuma empresa vinculada. Cadastre em **📦 Empresas**.")

    # Sair
    if st.sidebar.button("🔓 Sair"):
        st.session_state.user = None
        st.session_state.company = None
        st.rerun()

# ---------- Fluxo principal ----------
# 1) Se veio com token de definição de senha, prioriza essa tela
if handle_set_password_token():
    st.stop()

# 2) Se não logado, mostra login
if not st.session_state.user:
    do_login()
    st.stop()

# 3) Logado: sidebar com seletor de empresa e boas-vindas
sidebar_after_login()

st.title("👋 Bem-vindo(a) à Locadora Finance")
st.write("Use o menu **Pages** (barra lateral) para navegar entre os módulos.")

st.markdown("""
- **📦 Empresas**: cadastro de empresas e (para admin) vincular usuários.
- **🔐 Usuários (Admin)**: criar/editar usuários, escopo por empresa/página, convites e reset de senha.
- **👥 Clientes**: cadastro de clientes com endereço completo e exportações.
- **🧑‍🔧 Colaboradores & Férias**: cadastro, férias/afastamentos, custos.
- **🛠️ Equipamentos & Manutenção**: estoque, docs, manutenções e alertas.
- **🧾 Serviços & OS**: serviços, vínculo de colaboradores/equipamentos, OS, recebíveis e cobrança.
- **💸 Despesas**: despesas à vista/parceladas, recorrência e baixas.
- **💰 Receitas**: recebíveis e baixas integradas ao caixa.
- **📊 Caixa & Dashboards**: fluxo de caixa e KPIs.
- **⚖️ Impostos Comparativo**: simulação por regime.
- **🧮 Custos & Salários**: composição de custos por colaborador/serviço.
""")
