import streamlit as st
from db_core import get_conn
from security import list_user_companies

def require_company_with_picker() -> int:
    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Faça login na Home.")
        st.stop()

    if st.session_state.get("company"):
        return st.session_state.company["id"]

    st.title("🏢 Selecione a Empresa")
    uid = st.session_state.user["id"]

    with get_conn() as conn:
        rows = list_user_companies(uid)
        if not rows and st.session_state.user["role"] == "admin":
            rows = conn.execute("SELECT * FROM companies ORDER BY razao_social").fetchall()

    if not rows:
        st.info("Nenhuma empresa vinculada. Vá em **📦 Empresas** para cadastrar e vincular.")
        st.stop()

    labels = {r["id"]: f'{r["razao_social"]} ({r["regime"]})' for r in rows}
    sel = st.selectbox("Empresa", [r["id"] for r in rows], format_func=lambda x: labels[x])
    if st.button("Entrar"):
        with get_conn() as conn:
            st.session_state.company = dict(conn.execute("SELECT * FROM companies WHERE id=?", (sel,)).fetchone())
        st.rerun()

    st.stop()
