# ============================================================
# 04_🛠️_Equipamentos_e_Manutenção.py
# ============================================================
from __future__ import annotations
import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

from session_helpers import require_company_with_picker
from db_core import get_conn

st.set_page_config(page_title="🛠️ Equipamentos & Manutenção", layout="wide")


def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()


def ensure_schema_eq():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equipment(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              codigo TEXT,
              descricao TEXT,
              tipo TEXT,
              placa TEXT,
              chassi TEXT,
              doc_vencimento TEXT,
              manut_km INTEGER DEFAULT 0,
              manut_data TEXT,
              observacao TEXT,
              ativo INTEGER DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equipment_docs(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              equipment_id INTEGER NOT NULL,
              nome TEXT,
              dt_validade TEXT,
              resolvido INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equipment_maintenance(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              equipment_id INTEGER NOT NULL,
              tipo TEXT,
              data TEXT,
              km INTEGER,
              descricao TEXT,
              custo REAL DEFAULT 0
            )
            """
        )
        # Alvarás/licenças da empresa
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS company_permits(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              nome TEXT,
              dt_validade TEXT,
              resolvido INTEGER DEFAULT 0
            )
            """
        )
        # expenses (p/ integração de custo manutenção)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              fornecedor TEXT,
              descricao TEXT,
              categoria TEXT,
              tags TEXT,
              forma_pagamento TEXT,
              data_lancamento TEXT,
              valor_total REAL,
              parcelas INTEGER DEFAULT 1,
              equipment_id INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expense_installments(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              expense_id INTEGER NOT NULL,
              num_parcela INTEGER,
              due_date TEXT,
              amount REAL,
              paid INTEGER DEFAULT 0,
              paid_date TEXT
            )
            """
        )
        conn.commit()


def fmt_dmy(x):
    try:
        if isinstance(x, str):
            return datetime.fromisoformat(x).strftime("%d/%m/%Y")
        return x.strftime("%d/%m/%Y")
    except Exception:
        return ""


require_company()
ensure_schema_eq()
cid = require_company_with_picker()

st.title("🛠️ Equipamentos & Manutenção")

# --- Aba Cadastro/Lista
with st.expander("📇 Cadastro de equipamentos", expanded=True):
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
                conn.execute(
                    """
                    INSERT INTO equipment(company_id,codigo,descricao,tipo,placa,chassi,doc_vencimento,manut_km,manut_data,observacao)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        cid,
                        codigo,
                        desc,
                        tipo,
                        placa,
                        chassi,
                        doc_venc.isoformat() if doc_venc else None,
                        manut_km,
                        manut_data.isoformat() if manut_data else None,
                        obs,
                    ),
                )
                conn.commit()
            st.success("Equipamento salvo.")

with get_conn() as conn:
    eqs = conn.execute(
        "SELECT * FROM equipment WHERE company_id=? AND COALESCE(ativo,1)=1 ORDER BY descricao",
        (cid,),
    ).fetchall()

df_eq = pd.DataFrame([{k: r[k] for k in r.keys()} for r in eqs])
if not df_eq.empty:
    for c in ["doc_vencimento", "manut_data"]:
        if c in df_eq:
            df_eq[c] = df_eq[c].apply(fmt_dmy)
st.dataframe(df_eq, use_container_width=True)

# --- Expanders por equipamento (docs/manutenções)
for _, row in df_eq.iterrows():
    with st.expander(f"📦 {row['descricao']} — docs & manutenções"):
        eid = int(row["id"]) if "id" in row else None
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**📄 Documentos**")
            with st.form(f"doc_eq_{eid}"):
                dn = st.text_input("Nome do documento (ex: CRLV, seguro)")
                val = st.date_input("Validade")
                okd = st.form_submit_button("Salvar doc")
                if okd:
                    with get_conn() as conn:
                        conn.execute(
                            "INSERT INTO equipment_docs(equipment_id,nome,dt_validade) VALUES (?,?,?)",
                            (eid, dn, val.isoformat()),
                        )
                        conn.commit()
                    st.success("Documento salvo.")
            with get_conn() as conn:
                docs = conn.execute(
                    "SELECT * FROM equipment_docs WHERE equipment_id=? ORDER BY date(dt_validade) DESC",
                    (eid,),
                ).fetchall()
            df_docs = pd.DataFrame([{k: r[k] for k in r.keys()} for r in docs])
            if not df_docs.empty:
                df_docs["dt_validade"] = df_docs["dt_validade"].apply(fmt_dmy)
            st.dataframe(df_docs, use_container_width=True)

        with c2:
            st.markdown("**🔧 Manutenções**")
            with st.form(f"manut_eq_{eid}"):
                tipo_m = st.text_input("Tipo")
                dt_m = st.date_input("Data", value=date.today())
                km = st.number_input("KM", min_value=0, step=100)
                d_m = st.text_area("Descrição")
                custo = st.number_input("Custo (R$)", min_value=0.0, step=0.01, format="%.2f")
                okm = st.form_submit_button("Salvar manutenção")
                if okm:
                    with get_conn() as conn:
                        # Lança manutenção
                        cur = conn.execute(
                            """
                            INSERT INTO equipment_maintenance(equipment_id,tipo,data,km,descricao,custo)
                            VALUES (?,?,?,?,?,?)
                            """,
                            (eid, tipo_m, dt_m.isoformat(), km, d_m, custo),
                        )
                        manut_id = cur.lastrowid
                        # Integra em Despesas (categoria=Manutenção Equipamento)
                        if custo and custo > 0:
                            cur2 = conn.execute(
                                """
                                INSERT INTO expenses(company_id,fornecedor,descricao,categoria,tags,forma_pagamento,data_lancamento,valor_total,parcelas,equipment_id)
                                VALUES (?,?,?,?,?,?,?,?,?,?)
                                """,
                                (
                                    cid,
                                    f"Manutenção {row['descricao']}",
                                    d_m or f"Manutenção {tipo_m}",
                                    "Manutenção Equipamento",
                                    "equipamento,manutencao",
                                    "PIX",
                                    dt_m.isoformat(),
                                    custo,
                                    1,
                                    eid,
                                ),
                            )
                            exp_id = cur2.lastrowid
                            conn.execute(
                                "INSERT INTO expense_installments(expense_id,num_parcela,due_date,amount) VALUES (?,?,?,?)",
                                (exp_id, 1, dt_m.isoformat(), custo),
                            )
                        conn.commit()
                    st.success("Manutenção lançada e despesa integrada ao módulo 💸 Despesas.")

            with get_conn() as conn:
                mans = conn.execute(
                    "SELECT * FROM equipment_maintenance WHERE equipment_id=? ORDER BY date(data) DESC",
                    (eid,),
                ).fetchall()
            df_m = pd.DataFrame([{k: r[k] for k in r.keys()} for r in mans])
            if not df_m.empty:
                df_m["data"] = df_m["data"].apply(fmt_dmy)
            st.dataframe(df_m, use_container_width=True)

# --- Alvarás/Permissões da empresa
st.divider()
st.subheader("🏢 Alvarás/Permissões da empresa")
with st.form("f_alvara"):
    n = st.text_input("Nome do alvará/permissão")
    v = st.date_input("Validade")
    oka = st.form_submit_button("Salvar alvará")
    if oka:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO company_permits(company_id,nome,dt_validade) VALUES (?,?,?)",
                (cid, n, v.isoformat()),
            )
            conn.commit()
        st.success("Alvará salvo.")

with get_conn() as conn:
    alvs = conn.execute(
        "SELECT * FROM company_permits WHERE company_id=? ORDER BY date(dt_validade) DESC",
        (cid,),
    ).fetchall()
df_alv = pd.DataFrame([{k: r[k] for k in r.keys()} for r in alvs])
if not df_alv.empty:
    df_alv["dt_validade"] = df_alv["dt_validade"].apply(fmt_dmy)
st.dataframe(df_alv, use_container_width=True)

# --- Notificações D-30/20/10/5 (lista e marcação como resolvido)
st.divider()
st.subheader("🔔 Notificações de vencimento (D-30/20/10/5)")
hoje = date.today()
alertas: list[dict] = []

# docs de equipamentos
for _, r in (df_docs if 'df_docs' in locals() else pd.DataFrame()).iterrows():
    pass  # placeholder para tipagem

# Recarrega direto do banco para não depender do loop acima
with get_conn() as conn:
    docs_all = conn.execute(
        "SELECT 'doc' as tipo, id, equipment_id as ref_id, nome, dt_validade, resolvido FROM equipment_docs ed"
    ).fetchall()
    alv_all = conn.execute(
        "SELECT 'alvara' as tipo, id, NULL as ref_id, nome, dt_validade, resolvido FROM company_permits cp WHERE company_id=?",
        (cid,),
    ).fetchall()

rows_alert = [
    {k: rr[k] for k in rr.keys()} for rr in list(docs_all) + list(alv_all)
]

for r in rows_alert:
    if not r.get("dt_validade"):
        continue
    dv = datetime.fromisoformat(r["dt_validade"]).date()
    dias = (dv - hoje).days
    if dias in (30, 20, 10, 5) and int(r.get("resolvido", 0)) == 0:
        alertas.append(
            {
                "tipo": r["tipo"],
                "id": r["id"],
                "nome": r.get("nome"),
                "vence_em": fmt_dmy(dv),
                "faltam_dias": dias,
            }
        )

if alertas:
    df_alert = pd.DataFrame(alertas)
    st.dataframe(df_alert, use_container_width=True)
    ids_sel = st.multiselect("Marcar como resolvido (encerra lembretes)", [f"{a['tipo']}:{a['id']}" for a in alertas])
    if st.button("Aplicar"):
        with get_conn() as conn:
            for token in ids_sel:
                t, sid = token.split(":"); sid = int(sid)
                if t == "doc":
                    conn.execute("UPDATE equipment_docs SET resolvido=1 WHERE id=?", (sid,))
                else:
                    conn.execute("UPDATE company_permits SET resolvido=1 WHERE id=?", (sid,))
            conn.commit()
        st.success("Registros marcados como resolvidos.")
else:
    st.info("Nenhum lembrete D-30/20/10/5 pendente hoje.")

# Links rápidos para WhatsApp/E-mail
st.caption("Dica: use links diretos como 'mailto:' e 'https://wa.me/?text=...' nas descrições para agilizar comunicação.")
