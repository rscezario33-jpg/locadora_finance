# pages/02_👥_Clientes.py
import io
import pandas as pd
import streamlit as st
from session_helpers import require_company_with_picker
from db_core import get_conn
from utils_cep import busca_cep

# (opcional) permissões finas por página/empresa
try:
    from permissions import check_perm as _perm_check
except Exception:
    _perm_check = None

st.set_page_config(page_title="👥 Clientes", layout="wide")

# Exige login e seleciona/garante empresa ativa
cid = require_company_with_picker()

def perm(action: str) -> bool:
    """action: view|create|edit|delete"""
    if _perm_check is None:
        return True  # permissões ainda não habilitadas: permite tudo
    return _perm_check("CLIENTES", action, cid)

st.title("👥 Clientes")

# ===========================
#   Cadastro de novo cliente
# ===========================
with st.expander("➕ Novo cliente", expanded=True):
    with st.form("novo_cli"):
        c1, c2, c3 = st.columns([1.4, 1, 1])
        with c1:
            nome = st.text_input("Nome/Razão Social")
            email = st.text_input("E-mail")
        with c2:
            doc = st.text_input("CNPJ/CPF")
            phone = st.text_input("Telefone")
        with c3:
            # espaço para futuros campos (ex.: tipo de cliente)
            pass

        st.markdown("**Endereço**")
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            cep = st.text_input("CEP", key="novo_cli_cep")
            if st.form_submit_button("↺ Buscar CEP"):
                d = busca_cep(cep)
                if d:
                    st.session_state._caddr = d
                else:
                    st.warning("CEP não encontrado.")
        addr = st.session_state.get("_caddr", {})
        logradouro = st.text_input("Logradouro", value=addr.get("logradouro", ""))
        complemento = st.text_input("Complemento", value=addr.get("complemento", ""))
        numero = st.text_input("Número")
        bairro = st.text_input("Bairro", value=addr.get("bairro", ""))
        cidade = st.text_input("Cidade", value=addr.get("cidade", ""))
        estado = st.text_input("Estado", value=addr.get("estado", ""))

        ok = st.form_submit_button("Salvar cliente", type="primary")
        if ok:
            if not perm("create"):
                st.error("Você não tem permissão para incluir clientes."); st.stop()
            if not nome:
                st.warning("Informe ao menos o Nome/Razão Social.")
            else:
                with get_conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO clients(
                          company_id, nome, doc, email, phone, address,
                          cep, logradouro, complemento, numero, bairro, cidade, estado
                        ) VALUES (?,?,?,?,?,?,
                                  ?,?,?,?,?,?,?)
                        """,
                        (
                            cid, nome, doc, email, phone, "",
                            cep, logradouro, complemento, numero, bairro, cidade, estado,
                        ),
                    )
                    conn.commit()
                st.success("Cliente cadastrado.")
                st.session_state.pop("_caddr", None)
                st.rerun()

st.divider()

# ===========================
#      Lista / Edição
# ===========================
if not perm("view"):
    st.error("Você não tem permissão para visualizar clientes."); st.stop()

# Filtro rápido
colf1, colf2 = st.columns([2, 1])
with colf1:
    q = st.text_input("🔎 Buscar por nome, documento, e-mail ou telefone", "")
with colf2:
    ordenar = st.selectbox("Ordenar por", ["nome", "created_at", "doc"], index=0)

with get_conn() as conn:
    if q.strip():
        like = f"%{q.strip()}%"
        rows = conn.execute(
            f"""
            SELECT * FROM clients
            WHERE company_id=? AND (nome LIKE ? OR doc LIKE ? OR email LIKE ? OR phone LIKE ?)
            ORDER BY {ordenar}
            """,
            (cid, like, like, like, like),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM clients WHERE company_id=? ORDER BY {ordenar}",
            (cid,),
        ).fetchall()

st.subheader(f"Clientes ({len(rows)})")

if not rows:
    st.info("Nenhum cliente encontrado.")
else:
    for r in rows:
        header = f"**{r['nome']}**  |  {(r.get('doc') or '')}  |  {(r.get('email') or '')}"
        with st.expander(header, expanded=False):
            c1, c2, c3 = st.columns([1.4, 1, 1])
            with c1:
                st.text_input("Nome/Razão Social", r["nome"], key=f"n{r['id']}")
                st.text_input("E-mail", r.get("email", "") or "", key=f"e{r['id']}")
            with c2:
                st.text_input("CNPJ/CPF", r.get("doc", "") or "", key=f"d{r['id']}")
                st.text_input("Telefone", r.get("phone", "") or "", key=f"p{r['id']}")
            with c3:
                st.text_input("CEP", r.get("cep", "") or "", key=f"cep{r['id']}")
                if st.button("↺ Buscar CEP", key=f"b{r['id']}"):
                    d = busca_cep(st.session_state[f"cep{r['id']}"])
                    if d:
                        st.session_state[f"log{r['id']}"] = d.get("logradouro", "")
                        st.session_state[f"comp{r['id']}"] = d.get("complemento", "")
                        st.session_state[f"bai{r['id']}"] = d.get("bairro", "")
                        st.session_state[f"cid{r['id']}"] = d.get("cidade", "")
                        st.session_state[f"uf{r['id']}"] = d.get("estado", "")
                    else:
                        st.warning("CEP não encontrado.")

            c4, c5, c6 = st.columns([2, 1, 1])
            with c4:
                st.text_input("Logradouro", r.get("logradouro", "") or "", key=f"log{r['id']}")
            with c5:
                st.text_input("Número", r.get("numero", "") or "", key=f"num{r['id']}")
            with c6:
                st.text_input("Complemento", r.get("complemento", "") or "", key=f"comp{r['id']}")

            c7, c8 = st.columns([1, 1])
            with c7:
                st.text_input("Bairro", r.get("bairro", "") or "", key=f"bai{r['id']}")
            with c8:
                st.text_input("Cidade", r.get("cidade", "") or "", key=f"cid{r['id']}")
            st.text_input("Estado", r.get("estado", "") or "", key=f"uf{r['id']}")

            a1, a2 = st.columns([1, 1])
            if a1.button("Salvar", key=f"sv{r['id']}"):
                if not perm("edit"):
                    st.error("Você não tem permissão para editar."); st.stop()
                with get_conn() as conn:
                    conn.execute(
                        """
                        UPDATE clients SET
                          nome=?, doc=?, email=?, phone=?,
                          cep=?, logradouro=?, complemento=?, numero=?, bairro=?, cidade=?, estado=?
                        WHERE id=?
                        """,
                        (
                            st.session_state[f"n{r['id']}"],
                            st.session_state[f"d{r['id']}"],
                            st.session_state[f"e{r['id']}"],
                            st.session_state[f"p{r['id']}"],
                            st.session_state[f"cep{r['id']}"],
                            st.session_state[f"log{r['id']}"],
                            st.session_state[f"comp{r['id']}"],
                            st.session_state[f"num{r['id']}"],
                            st.session_state[f"bai{r['id']}"],
                            st.session_state[f"cid{r['id']}"],
                            st.session_state[f"uf{r['id']}"],
                            r["id"],
                        ),
                    )
                    conn.commit()
                st.success("Alterações salvas.")

            if a2.button("Excluir", key=f"dl{r['id']}"):
                if not perm("delete"):
                    st.error("Você não tem permissão para excluir."); st.stop()
                with get_conn() as conn:
                    conn.execute("DELETE FROM clients WHERE id=?", (r["id"],))
                    conn.commit()
                st.warning("Cliente excluído.")
                st.rerun()

# ===========================
#        Exportações
# ===========================
if rows:
    st.divider()
    st.markdown("### Exportar")

    df = pd.DataFrame([{k: x[k] for k in x.keys()} for x in rows])

    # CSV
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ CSV", data=csv_bytes, file_name="clientes.csv", mime="text/csv")

    # XLSX
    xbio = io.BytesIO()
    with pd.ExcelWriter(xbio, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="clientes")
    st.download_button(
        "⬇️ XLSX",
        data=xbio.getvalue(),
        file_name="clientes.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # PDF (lista simples)
    from fpdf import FPDF

    def _pdf(df_: pd.DataFrame) -> bytes:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Clientes", ln=1)
        pdf.set_font("Helvetica", size=10)
        for _, row in df_.iterrows():
            linha = f"{row.get('nome','')}"
            if row.get('doc'): linha += f" | {row['doc']}"
            if row.get('email'): linha += f" | {row['email']}"
            if row.get('phone'): linha += f" | {row['phone']}"
            pdf.multi_cell(0, 6, linha)
        return pdf.output(dest="S").encode("latin-1")

    st.download_button(
        "⬇️ PDF",
        data=_pdf(df),
        file_name="clientes.pdf",
        mime="application/pdf",
    )
