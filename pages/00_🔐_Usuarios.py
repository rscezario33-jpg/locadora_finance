# pages/00_🔐_Usuarios.py
import streamlit as st
from db_core import get_conn
from security import create_user
import bcrypt

st.set_page_config(page_title="🔐 Usuários (Admin)", layout="wide")

def require_admin():
    if "user" not in st.session_state or st.session_state.user is None:
        st.stop()
    if st.session_state.user["role"] != "admin":
        st.error("Apenas administradores podem acessar esta página.")
        st.stop()

require_admin()
st.title("🔐 Administração de Usuários")

# ---------- Criar novo usuário ----------
with st.expander("➕ Criar novo usuário", expanded=True):
    with st.form("new_user"):
        name = st.text_input("Nome")
        email = st.text_input("E-mail")
        pwd = st.text_input("Senha provisória", type="password")
        role = st.selectbox("Perfil", ["user", "admin"])
        active = st.checkbox("Ativo", value=True)
        ok = st.form_submit_button("Criar")
        if ok:
            try:
                if not name or not email or not pwd:
                    st.warning("Preencha Nome, E-mail e Senha.")
                else:
                    create_user(name, email, pwd, role=role, active=active)
                    st.success("Usuário criado com sucesso.")
            except Exception as e:
                st.error(f"Erro ao criar usuário: {e}")

st.divider()

# ---------- Listagem ----------
with get_conn() as conn:
    users = conn.execute("SELECT id,name,email,role,is_active,created_at FROM users ORDER BY name").fetchall()

st.subheader("Usuários cadastrados")
st.dataframe([{k: r[k] for k in r.keys()} for r in users], use_container_width=True)

# ---------- Gerenciar um usuário ----------
if users:
    user_map = {f"{u['name']} <{u['email']}>": u["id"] for u in users}
    sel = st.selectbox("Selecionar usuário p/ edição", list(user_map.keys()))
    uid = user_map[sel]

    with get_conn() as conn:
        u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        companies = conn.execute("SELECT id, razao_social FROM companies ORDER BY razao_social").fetchall()
        linked = conn.execute("SELECT company_id FROM user_companies WHERE user_id=?", (uid,)).fetchall()
        linked_ids = {x["company_id"] for x in linked}

    col1, col2 = st.columns([1,1])

    # Status / perfil / senha
    with col1:
        st.markdown("### ⚙️ Status e perfil")
        is_active = st.checkbox("Ativo", value=bool(u["is_active"]))
        role = st.selectbox("Perfil", ["user","admin"], index=["user","admin"].index(u["role"]))
        new_pwd = st.text_input("Redefinir senha (opcional)", type="password")
        if st.button("Salvar alterações", key="save_user"):
            if uid == st.session_state.user["id"] and not is_active:
                st.error("Você não pode desativar o próprio usuário logado.")
            else:
                with get_conn() as conn:
                    conn.execute("UPDATE users SET is_active=?, role=? WHERE id=?",
                                 (1 if is_active else 0, role, uid))
                    if new_pwd:
                        pw_hash = bcrypt.hashpw(new_pwd.encode(), bcrypt.gensalt())
                        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, uid))
                    conn.commit()
                st.success("Alterações salvas.")
                st.rerun()

    # Vínculo com empresas
    with col2:
        st.markdown("### 🏢 Vínculo com empresas")
        opts = {c["razao_social"]: c["id"] for c in companies}
        default = [name for name, cid in opts.items() if cid in linked_ids]
        sel_emp = st.multiselect("Empresas vinculadas", list(opts.keys()), default=default)
        if st.button("Aplicar vínculos", key="save_links"):
            target_ids = {opts[n] for n in sel_emp}
            with get_conn() as conn:
                conn.execute("DELETE FROM user_companies WHERE user_id=?", (uid,))
                for cid in target_ids:
                    conn.execute("INSERT OR IGNORE INTO user_companies(user_id, company_id) VALUES (?,?)", (uid, cid))
                conn.commit()
            st.success("Vínculos atualizados.")
            st.rerun()
