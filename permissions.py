# permissions.py
import streamlit as st
from db_core import get_conn

def check_perm(page_key: str, action: str, company_id: int) -> bool:
    # admin sempre pode tudo
    u = st.session_state.get("user")
    if not u: return False
    if u["role"] == "admin": return True
    with get_conn() as conn:
        row = conn.execute("""
          SELECT can_view, can_create, can_edit, can_delete
          FROM permissions
          WHERE user_id=? AND company_id=? AND page_key=?
        """, (u["id"], company_id, page_key)).fetchone()
    if not row: return False
    mapping = {"view":"can_view","create":"can_create","edit":"can_edit","delete":"can_delete"}
    return bool(row[mapping[action]])
