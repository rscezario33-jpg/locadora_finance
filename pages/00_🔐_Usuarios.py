import streamlit as st, uuid, datetime
from db_core import get_conn
from security import create_user
from utils_email import send_email
from permissions import check_perm

st.set_page_config(page_title="🔐 Usuários (Admin)", layout="wide")

def require_admin():
    if "user" not in st.session_state or st.session_state.user is None:
        st.stop()
    if st.session_state.user["role"] != "admin":
        st.error("Apenas administradores.")
        st.stop()
require_admin()

st.title("🔐 Administração de Usuários")

# --- helpers de token ---
def criar_token(user_id, horas=24):
    token = uuid.uuid4().hex
    exp = (datetime.datetime.utcnow() + datetime.timedelta(hours=horas)).isoformat()
    with get_conn() as conn:
        conn.execute("INSERT INTO password_reset_tokens(user_id, token, expires_at) VALUES (?,?,?)", (user_id, token, exp))
        conn.commit()
    return token

def link_definir_senha(token):
    base = st.secrets.get("BASE_URL","")
    if not base:
        # fallback: usa a URL atual sem path adicional
        base = st.experimental_get_query_params().get("_origin", [st.request.url if hasattr(st, 'request') else ""])[0] or ""
    return f"{base}?setpwd={token}"

# --- criar novo usuário ---
with st.expander("➕ Criar novo usuário", expanded=True):
    with st.form("new_user"):
        name = st.text_input("Nome")
        email = st.text_input("E-mail")
        role = st.selectbox("Perfil", ["user", "admin"])
        active = st.checkbox("Ativo", value=True)
        ok = st.form_submit_button("Criar e enviar convite")
        if ok:
            if not name or not email:
                st.warning("Preencha Nome e E-mail.")
            else:
                try:
                    # cria com senha inútil temporária
                    create_user(name, email, uuid.uuid4().hex[:12], role=role, active=active)
                    # gera token e envia e-mail
                    token = criar_token(get_conn().execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"])
                    link = link_definir_senha(token)
                    html = f"""
                    <h3>Bem-vindo ao sistema</h3>
                    <p>Para definir sua senha, clique no link abaixo (válido por 24h):</p>
                    <p><a href="{link}">{link}</a></p>
                    """
                    okmail = send_email(email, "Defina sua senha", html)
                    st.success("Usuário criado. Convite enviado por e-mail." if okmail else "Usuário criado. (E-mail não configurado)")
                except Exception as e:
                    st.error(f"Erro ao criar usuário: {e}")

st.divider()

# --- listagem e edição ---
with get_conn() as conn:
    users = conn.execute("SELECT id,name,email,role,is_active,created_at FROM users ORDER BY name").fetchall()
st.subheader("Usuários")
st.dataframe([{k:r[k] for k in r.keys()} for r in users], use_container_width=True)

if users:
    sel = st.selectbox("Selecionar usuário p/ gerenciar", [f"{u['name']} <{u['email']}>" for u in users])
    uid = users[[f"{u['name']} <{u['email']}>" for u in users].index(sel)]["id"]

    with get_conn() as conn:
        u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        companies = conn.execute("SELECT id, razao_social FROM companies ORDER BY razao_social").fetchall()
        links = conn.execute("SELECT company_id FROM user_companies WHERE user_id=?", (uid,)).fetchall()
        linked_ids = {x["company_id"] for x in links}

    with st.expander("⚙️ Status, perfil e senha", expanded=True):
        col1,col2=st.columns([1,1])
        with col1:
            is_active = st.checkbox("Ativo", value=bool(u["is_active"]))
            role = st.selectbox("Perfil", ["user","admin"], index=["user","admin"].index(u["role"]))
            if st.button("Salvar"):
                with get_conn() as conn:
                    conn.execute("UPDATE users SET is_active=?, role=? WHERE id=?", (1 if is_active else 0, role, uid))
                    conn.commit()
                st.success("Alterações salvas."); st.rerun()
        with col2:
            if st.button("🔗 Reenviar link de definição de senha"):
                token = criar_token(uid)
                link = link_definir_senha(token)
                html = f"<p>Defina sua senha: <a href='{link}'>{link}</a> (24h)</p>"
                okm = send_email(u["email"], "Defina sua senha", html)
                st.success("Link enviado." if okm else "E-mail não configurado.")
            if st.button("🧨 Resetar senha (forçar novo cadastro)"):
                token = criar_token(uid)
                # opcional: invalidar senha atual? deixe como está — troca quando acessar o link.
                st.info("Senha será redefinida quando o usuário usar o link enviado.")

    with st.expander("🏢 Vínculo por empresa", expanded=True):
        opts = {c["razao_social"]: c["id"] for c in companies}
        default = [n for n,cid in opts.items() if cid in linked_ids]
        sel_emp = st.multiselect("Empresas vinculadas", list(opts.keys()), default=default)
        if st.button("Aplicar vínculos"):
            target_ids = {opts[n] for n in sel_emp}
            with get_conn() as conn:
                conn.execute("DELETE FROM user_companies WHERE user_id=?", (uid,))
                for cid in target_ids:
                    conn.execute("INSERT OR IGNORE INTO user_companies(user_id, company_id) VALUES (?,?)", (uid, cid))
                conn.commit()
            st.success("Vínculos atualizados."); st.rerun()

    with st.expander("🔏 Escopo por página (CRUD)", expanded=True):
        pages = [
            ("EMPRESAS","01_📦_Empresas"),
            ("CLIENTES","02_👥_Clientes"),
            ("COLABORADORES","03_🧑‍🔧_Colaboradores_e_Férias"),
            ("EQUIPAMENTOS","04_🛠️_Equipamentos_e_Manutenção"),
            ("SERVIÇOS","05_🧾_Serviços_e_OS"),
            ("DESPESAS","06_💸_Despesas"),
            ("RECEITAS","07_💰_Receitas"),
            ("DASH","08_📊_Caixa_e_Dashboards"),
            ("IMPOSTOS","09_⚖️_Impostos_Comparativo"),
            ("CUSTOS","10_🧮_Custos_e_Salários")
        ]
        # selecionar empresa alvo
        cid = st.selectbox("Empresa alvo", [c["id"] for c in companies], format_func=lambda x: next(c["razao_social"] for c in companies if c["id"]==x))
        rows=[]
        with get_conn() as conn:
            for key,title in pages:
                p = conn.execute("""
                  SELECT can_view,can_create,can_edit,can_delete
                  FROM permissions WHERE user_id=? AND company_id=? AND page_key=?""",
                  (uid, cid, key)).fetchone()
                rows.append([key,title] + [bool(p[k]) if p else (key=="EMPRESAS" and st.session_state.user["role"]=="admin") for k in ["can_view","can_create","can_edit","can_delete"]])
        import pandas as pd
        df = pd.DataFrame(rows, columns=["page_key","Página","Ver","Incluir","Editar","Excluir"])
        edited = st.data_editor(df, hide_index=True, disabled=["page_key","Página"], use_container_width=True)
        if st.button("Salvar escopo"):
            with get_conn() as conn:
                for _,r in edited.iterrows():
                    conn.execute("""
                      INSERT INTO permissions(user_id,company_id,page_key,can_view,can_create,can_edit,can_delete)
                      VALUES (?,?,?,?,?,?,?)
                      ON CONFLICT(user_id,company_id,page_key) DO UPDATE SET
                        can_view=excluded.can_view, can_create=excluded.can_create,
                        can_edit=excluded.can_edit, can_delete=excluded.can_delete
                    """, (uid, cid, r["page_key"], int(r["Ver"]), int(r["Incluir"]), int(r["Editar"]), int(r["Excluir"])))
                conn.commit()
            st.success("Escopo salvo.")
