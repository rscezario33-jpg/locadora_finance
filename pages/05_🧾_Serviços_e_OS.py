# ============================================================
# 05_🧾_Serviços_e_OS.py
# ============================================================
from __future__ import annotations
import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

from session_helpers import require_company_with_picker
from db_core import get_conn

st.set_page_config(page_title="🧾 Serviços & OS", layout="wide")


def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()


def ensure_schema_srv():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clients(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              nome TEXT,
              doc TEXT,
              email TEXT,
              phone TEXT,
              address TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS services(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              client_id INTEGER,
              data TEXT,
              descricao TEXT,
              valor_total REAL,
              forma_pagamento TEXT,
              parcelas INTEGER,
              fiscal INTEGER DEFAULT 1,
              status TEXT DEFAULT 'aberta'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_employees(
              service_id INTEGER,
              employee_id INTEGER,
              PRIMARY KEY (service_id, employee_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_equipments(
              service_id INTEGER,
              equipment_id INTEGER,
              PRIMARY KEY (service_id, equipment_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS revenue(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              service_id INTEGER,
              data TEXT,
              valor REAL,
              forma TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS revenue_installments(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              revenue_id INTEGER NOT NULL,
              num_parcela INTEGER,
              due_date TEXT,
              amount REAL,
              paid INTEGER DEFAULT 0,
              paid_date TEXT
            )
            """
        )
        # cash ledger (compartilhado)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cash_ledger(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                tipo TEXT NOT NULL,            -- 'in' ou 'out'
                valor REAL NOT NULL,
                descricao TEXT,
                link_tipo TEXT,
                link_id INTEGER
            )
            """
        )
        conn.commit()


require_company()
ensure_schema_srv()
cid = require_company_with_picker()

st.title("🧾 Serviços & Ordem de Serviço")

# Carregar cadastros básicos
with get_conn() as conn:
    clients = conn.execute("SELECT id,nome FROM clients WHERE company_id=? ORDER BY nome", (cid,)).fetchall()
    employees = conn.execute("SELECT id,nome FROM employees WHERE company_id=? AND COALESCE(ativo,1)=1 ORDER BY nome", (cid,)).fetchall()
    eqs = conn.execute("SELECT id,descricao FROM equipment WHERE company_id=? AND COALESCE(ativo,1)=1 ORDER BY descricao", (cid,)).fetchall()

cli_map = {c["nome"]: c["id"] for c in clients}
emp_map = {e["nome"]: e["id"] for e in employees}
eq_map = {e["descricao"]: e["id"] for e in eqs}

with st.form("f_srv"):
    st.subheader("Cadastrar Serviço")
    dt = st.date_input("Data do serviço", value=date.today())
    cli = st.selectbox("Cliente", list(cli_map.keys()) if cli_map else [])
    desc = st.text_area("Descrição dos serviços")
    valor = st.number_input("Valor total (R$)", min_value=0.0, step=0.01, format="%.2f")
    forma = st.selectbox("Forma de pagamento", ["PIX", "TED", "Boleto", "Cartão", "Dinheiro", "Outro"])
    parcelas = st.number_input("Parcelas", min_value=1, max_value=60, value=1)
    fiscal = st.toggle(
        "Fiscal?",
        value=True,
        help="Marque para integrar ao cálculo de impostos. Desmarcado = gerencial.",
    )
    vinc_emps = st.multiselect("Vincular colaboradores", list(emp_map.keys()))
    vinc_eqs = st.multiselect("Vincular equipamentos", list(eq_map.keys()))
    ok = st.form_submit_button("Salvar serviço e gerar OS/receita")
    if ok:
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO services(company_id,client_id,data,descricao,valor_total,forma_pagamento,parcelas,fiscal,status)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (cid, cli_map.get(cli) if cli else None, dt.isoformat(), desc, valor, forma, parcelas, 1 if fiscal else 0, "aberta"),
            )
            srv_id = cur.lastrowid
            for n in vinc_emps:
                conn.execute("INSERT OR IGNORE INTO service_employees(service_id,employee_id) VALUES (?,?)", (srv_id, emp_map[n]))
            for n in vinc_eqs:
                conn.execute("INSERT OR IGNORE INTO service_equipments(service_id,equipment_id) VALUES (?,?)", (srv_id, eq_map[n]))

            # gerar receita/parcelas
            cur = conn.execute(
                "INSERT INTO revenue(company_id,service_id,data,valor,forma) VALUES (?,?,?,?,?)",
                (cid, srv_id, dt.isoformat(), valor, forma),
            )
            rev_id = cur.lastrowid
            # split parcelado
            par_val = round(valor / parcelas, 2)
            vals = [par_val] * parcelas
            dif = round(valor - sum(vals), 2)
            vals[-1] += dif
            for i in range(parcelas):
                due = (date.fromisoformat(dt.isoformat()).replace(day=1) + timedelta(days=31 * i)).replace(day=dt.day)
                conn.execute(
                    "INSERT INTO revenue_installments(revenue_id,num_parcela,due_date,amount) VALUES (?,?,?,?)",
                    (rev_id, i + 1, due.isoformat(), vals[i]),
                )
            conn.commit()
        st.success(f"Serviço #{srv_id} salvo e OS/Recebíveis gerados.")

st.divider()

# === GRID: seleção múltipla, edição, exclusão, impressão em lote
st.subheader("📋 Serviços (gerenciar/emitir)")
with get_conn() as conn:
    srvs = conn.execute(
        "SELECT s.id, s.data, c.nome as cliente, s.descricao, s.valor_total, s.forma_pagamento, s.parcelas, s.status FROM services s LEFT JOIN clients c ON c.id=s.client_id WHERE s.company_id=? ORDER BY date(s.data) DESC",
        (cid,),
    ).fetchall()

df_srvs = pd.DataFrame([{k: r[k] for k in r.keys()} for r in srvs])
if not df_srvs.empty:
    df_srvs["data"] = df_srvs["data"].apply(lambda x: datetime.fromisoformat(x).strftime("%d/%m/%Y"))

# editor simples (edita descrição/status)
if not df_srvs.empty:
    edited = st.data_editor(
        df_srvs,
        use_container_width=True,
        column_config={"descricao": st.column_config.TextColumn("Descrição"), "status": st.column_config.SelectboxColumn("Status", options=["aberta", "em execução", "concluída", "cancelada"]),},
        disabled=["id", "data", "cliente", "valor_total", "forma_pagamento", "parcelas"],
        hide_index=True,
    )
    # detectar mudanças e salvar
    if st.button("💾 Salvar alterações"):
        with get_conn() as conn:
            for _, r in edited.iterrows():
                conn.execute("UPDATE services SET descricao=?, status=? WHERE id=? AND company_id=?", (r["descricao"], r["status"], int(r["id"]), cid))
            conn.commit()
        st.success("Alterações salvas.")

    # seleção múltipla
    ids_sel = st.multiselect("Selecionar serviços (para excluir/emitir)", [int(x) for x in edited["id"].tolist()])
    colA, colB, colC = st.columns(3)
    with colA:
        if st.button("🗑️ Excluir selecionados") and ids_sel:
            with get_conn() as conn:
                for sid in ids_sel:
                    conn.execute("DELETE FROM services WHERE id=? AND company_id=?", (sid, cid))
                conn.commit()
            st.warning("Registros excluídos.")
            st.rerun()
    with colB:
        # Impressão em lote (PDF se disponível, fallback HTML zipado)
        if st.button("🖨️ Imprimir OS (PDF)") and ids_sel:
            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.pdfgen import canvas
                from reportlab.lib.units import mm
                from reportlab.lib.utils import simpleSplit

                pbuf = io.BytesIO()
                c = canvas.Canvas(pbuf, pagesize=A4)
                W, H = A4
                with get_conn() as conn:
                    for sid in ids_sel:
                        srv = conn.execute("SELECT * FROM services WHERE id=? AND company_id=?", (sid, cid)).fetchone()
                        cli = conn.execute("SELECT * FROM clients WHERE id=?", (srv["client_id"],)).fetchone() if srv and srv["client_id"] else None
                        emps = conn.execute("SELECT e.nome FROM employees e JOIN service_employees se ON se.employee_id=e.id WHERE se.service_id=?", (sid,)).fetchall()
                        eqps = conn.execute("SELECT e.descricao FROM equipment e JOIN service_equipments se ON se.equipment_id=e.id WHERE se.service_id=?", (sid,)).fetchall()

                        c.setFont("Helvetica-Bold", 14); c.drawString(20*mm, H-20*mm, f"Ordem de Serviço #{sid}")
                        c.setFont("Helvetica", 10)
                        y = H-30*mm
                        def line(txt):
                            nonlocal y
                            for piece in simpleSplit(txt, "Helvetica", 10, W-40*mm):
                                if y < 20*mm: c.showPage(); c.setFont("Helvetica", 10); y = H-20*mm
                                c.drawString(20*mm, y, piece); y -= 6*mm
                        line(f"Cliente: {cli['nome'] if cli else '-'}")
                        line(f"Data: {srv['data']}")
                        line(f"Descrição: {srv['descricao'] or '-'}")
                        line(f"Valor total: R$ {srv['valor_total']:.2f} – Forma/Parcelas: {srv['forma_pagamento']}/{srv['parcelas']}")
                        line(f"Classificação: {'Fiscal' if srv['fiscal'] else 'Gerencial'} – Status: {srv['status']}")
                        line("Colaboradores: " + (", ".join([e['nome'] for e in emps]) if emps else "-"))
                        line("Equipamentos: " + (", ".join([e['descricao'] for e in eqps]) if eqps else "-"))
                        c.showPage()
                c.save()
                st.download_button("⬇️ Baixar PDF", pbuf.getvalue(), file_name="OS_lote.pdf", mime="application/pdf")
            except Exception:
                st.info("Para PDF, instale 'reportlab'.")
    with colC:
        st.write("")

# === Recebimentos (parcelas) – marcar como recebido alimenta caixa
st.divider()
st.subheader("💰 Recebíveis (parcelas)")
with get_conn() as conn:
    parc = conn.execute(
        """
        SELECT ri.id, r.service_id, s.data as data_servico, c.nome as cliente, ri.num_parcela, ri.due_date, ri.amount, ri.paid, ri.paid_date
        FROM revenue_installments ri
        JOIN revenue r ON r.id=ri.revenue_id
        JOIN services s ON s.id=r.service_id
        LEFT JOIN clients c ON c.id=s.client_id
        WHERE s.company_id=? AND ri.paid=0
        ORDER BY date(ri.due_date) ASC
        """,
        (cid,),
    ).fetchall()
df_parc = pd.DataFrame([{k: r[k] for k in r.keys()} for r in parc])
if not df_parc.empty:
    df_parc["due_date"] = df_parc["due_date"].apply(lambda x: datetime.fromisoformat(x).strftime("%d/%m/%Y"))
st.dataframe(df_parc, use_container_width=True)

ids_pagar = st.multiselect("Selecionar parcelas recebidas", [int(r["id"]) for r in parc])
if st.button("Marcar como recebidas") and ids_pagar:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        for pid in ids_pagar:
            row = conn.execute(
                """
                SELECT ri.amount, r.service_id
                FROM revenue_installments ri
                JOIN revenue r ON r.id=ri.revenue_id
                WHERE ri.id=?
                """,
                (pid,),
            ).fetchone()
            conn.execute("UPDATE revenue_installments SET paid=1, paid_date=? WHERE id=?", (now, pid))
            # alimenta caixa (entrada)
            if row:
                conn.execute(
                    "INSERT INTO cash_ledger(company_id,data,tipo,valor,descricao,link_tipo,link_id) VALUES (?,?,?,?,?,?,?)",
                    (
                        cid,
                        now,
                        "in",
                        row["amount"],
                        f"Recebimento parcela OS #{row['service_id']}",
                        "revenue_installment",
                        pid,
                    ),
                )
        conn.commit()
    st.success("Parcelas marcadas e caixa atualizado.")
    st.rerun()

# Lembretes de não recebidos
st.subheader("🔔 Lembretes de parcelas vencendo / vencidas")
with get_conn() as conn:
    alert = conn.execute(
        "SELECT ri.id, s.id as service_id, c.nome as cliente, ri.due_date, ri.amount FROM revenue_installments ri JOIN revenue r ON r.id=ri.revenue_id JOIN services s ON s.id=r.service_id LEFT JOIN clients c ON c.id=s.client_id WHERE s.company_id=? AND ri.paid=0 ORDER BY date(ri.due_date) ASC",
        (cid,),
    ).fetchall()

rows_alert = [{k: r[k] for k in r.keys()} for r in alert]
if rows_alert:
    df_alert = pd.DataFrame(rows_alert)
    df_alert["due_date"] = df_alert["due_date"].apply(lambda x: datetime.fromisoformat(x).strftime("%d/%m/%Y"))
    st.dataframe(df_alert, use_container_width=True)
    st.caption("Envie lembrete por e-mail/WhatsApp com links rápidos abaixo.")
else:
    st.info("Sem parcelas pendentes.")
