# -*- coding: utf-8 -*-
# ============================================================
# 05_🧾_Serviços_e_OS.py  —  PDF PRO para Ordem de Serviço
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
        # --- clients (com campos extras para compatibilidade com a página de Clientes)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clients(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              nome TEXT,
              doc TEXT,
              email TEXT,
              phone TEXT,
              address TEXT,
              cep TEXT,
              logradouro TEXT,
              complemento TEXT,
              numero TEXT,
              bairro TEXT,
              cidade TEXT,
              estado TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # --- employees
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employees(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              matricula TEXT,
              nome TEXT,
              funcao TEXT,
              salario REAL DEFAULT 0,
              diaria REAL DEFAULT 0,
              data_admissao TEXT,
              data_rescisao TEXT,
              ativo INTEGER DEFAULT 1
            )
            """
        )
        # --- equipment
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equipment(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              descricao TEXT,
              ativo INTEGER DEFAULT 1
            )
            """
        )
        # --- services
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
        # --- vínculos
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
        # --- receitas e parcelas
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
        # --- caixa (compartilhado)
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


# ----------------------------------------------------------------
# Boot básico
# ----------------------------------------------------------------
require_company()
ensure_schema_srv()
cid = require_company_with_picker()

st.title("🧾 Serviços & Ordem de Serviço")

# ---------------------------------
# Cadastros básicos para selects
# ---------------------------------
with get_conn() as conn:
    clients = conn.execute(
        "SELECT id,nome FROM clients WHERE company_id=? ORDER BY nome",
        (cid,),
    ).fetchall()
    employees = conn.execute(
        "SELECT id,nome FROM employees WHERE company_id=? AND COALESCE(ativo,1)=1 ORDER BY nome",
        (cid,),
    ).fetchall()
    eqs = conn.execute(
        "SELECT id,descricao FROM equipment WHERE company_id=? AND COALESCE(ativo,1)=1 ORDER BY descricao",
        (cid,),
    ).fetchall()

cli_map = {c["nome"]: c["id"] for c in clients}
emp_map = {e["nome"]: e["id"] for e in employees}
eq_map = {e["descricao"]: e["id"] for e in eqs}

# ---------------------------------
# Cadastro de serviço
# ---------------------------------
with st.form("f_srv"):
    st.subheader("Cadastrar Serviço")
    dt = st.date_input("Data do serviço", value=date.today())
    cli = st.selectbox("Cliente", list(cli_map.keys()) if cli_map else [], key="sb_cliente")
    desc = st.text_area("Descrição detalhada / serviços executados")
    valor = st.number_input("Valor total (R$)", min_value=0.0, step=0.01, format="%.2f")
    forma = st.selectbox("Forma de pagamento", ["PIX", "TED", "Boleto", "Cartão", "Dinheiro", "Outro"], key="sb_forma")
    parcelas = st.number_input("Parcelas", min_value=1, max_value=60, value=1)
    fiscal = st.toggle(
        "Fiscal?",
        value=True,
        help="Marque para integrar ao cálculo de impostos. Desmarcado = gerencial.",
    )
    vinc_emps = st.multiselect("Vincular colaboradores", list(emp_map.keys()), key="ms_emps")
    vinc_eqs = st.multiselect("Vincular equipamentos", list(eq_map.keys()), key="ms_eqs")
    ok = st.form_submit_button("Salvar serviço e gerar OS/receita")
    if ok:
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO services(company_id,client_id,data,descricao,valor_total,forma_pagamento,parcelas,fiscal,status)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (cid, cli_map.get(cli) if cli else None, dt.isoformat(), desc, valor, forma, int(parcelas), 1 if fiscal else 0, "aberta"),
            )
            srv_id = cur.lastrowid

            # vínculos
            for n in vinc_emps:
                conn.execute(
                    "INSERT OR IGNORE INTO service_employees(service_id,employee_id) VALUES (?,?)",
                    (srv_id, emp_map[n]),
                )
            for n in vinc_eqs:
                conn.execute(
                    "INSERT OR IGNORE INTO service_equipments(service_id,equipment_id) VALUES (?,?)",
                    (srv_id, eq_map[n]),
                )

            # receita e parcelas
            cur = conn.execute(
                "INSERT INTO revenue(company_id,service_id,data,valor,forma) VALUES (?,?,?,?,?)",
                (cid, srv_id, dt.isoformat(), valor, forma),
            )
            rev_id = cur.lastrowid

            # dividir valor em N parcelas: últimos centavos ajustados na última
            par_val = round(float(valor) / int(parcelas), 2)
            vals = [par_val] * int(parcelas)
            dif = round(float(valor) - sum(vals), 2)
            vals[-1] += dif

            # calcular vencimentos mês a mês
            base_day = dt.day
            base_month_first = dt.replace(day=1)
            for i in range(int(parcelas)):
                # avança ~1 mês por vez (31 dias é aproximação)
                due_month_approx = base_month_first + timedelta(days=31 * i)
                year, month = due_month_approx.year, due_month_approx.month
                try:
                    due = date(year, month, base_day)
                except ValueError:
                    # último dia do mês
                    nxt = (date(year, month, 1) + timedelta(days=31)).replace(day=1)
                    due = nxt - timedelta(days=1)
                conn.execute(
                    "INSERT INTO revenue_installments(revenue_id,num_parcela,due_date,amount) VALUES (?,?,?,?)",
                    (rev_id, i + 1, due.isoformat(), vals[i]),
                )

            conn.commit()
        st.success(f"Serviço #{srv_id} salvo e OS/Recebíveis gerados.")

st.divider()

# ---------------------------------
# GRID: seleção múltipla, edição, exclusão, impressão em lote
# ---------------------------------
st.subheader("📋 Serviços (gerenciar/emitir)")
with get_conn() as conn:
    srvs = conn.execute(
        """
        SELECT s.id, s.data, c.nome as cliente, s.descricao, s.valor_total,
               s.forma_pagamento, s.parcelas, s.status, s.fiscal, s.client_id
        FROM services s
        LEFT JOIN clients c ON c.id = s.client_id
        WHERE s.company_id=?
        ORDER BY date(s.data) DESC, s.id DESC
        """,
        (cid,),
    ).fetchall()

df_srvs = pd.DataFrame([{k: r[k] for k in r.keys()} for r in srvs])
if not df_srvs.empty and "data" in df_srvs.columns:
    def _fmt_iso(x):
        try:
            return datetime.fromisoformat(x).strftime("%d/%m/%Y")
        except Exception:
            return x
    df_srvs["data"] = df_srvs["data"].apply(_fmt_iso)

if not df_srvs.empty:
    edited = st.data_editor(
        df_srvs.drop(columns=["client_id"], errors="ignore"),
        use_container_width=True,
        column_config={
            "descricao": st.column_config.TextColumn("Descrição"),
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=["aberta", "em execução", "concluída", "cancelada"],
            ),
            "fiscal": st.column_config.CheckboxColumn("Fiscal?"),
            "valor_total": st.column_config.NumberColumn("Valor total (R$)", format="%.2f"),
            "forma_pagamento": "Forma",
            "parcelas": "Parcelas",
            "cliente": "Cliente",
            "data": "Data",
            "id": "ID",
        },
        disabled=["id", "data", "cliente", "valor_total", "forma_pagamento", "parcelas", "fiscal"],
        hide_index=True,
        key="ed_srvs",
    )

    if st.button("💾 Salvar alterações", key="btn_save_srvs"):
        with get_conn() as conn:
            for _, r in edited.iterrows():
                conn.execute(
                    "UPDATE services SET descricao=?, status=? WHERE id=? AND company_id=?",
                    (r["descricao"], r["status"], int(r["id"]), cid),
                )
            conn.commit()
        st.success("Alterações salvas.")

    # seleção múltipla
    ids_sel = st.multiselect(
        "Selecionar serviços (para excluir/emitir)",
        [int(x) for x in edited["id"].tolist()],
        key="ms_sel_srvs",
    )

    colA, colB, colC = st.columns(3)

    # Excluir selecionados (com “cascata” manual)
    with colA:
        if st.button("🗑️ Excluir selecionados", key="btn_del_srvs") and ids_sel:
            with get_conn() as conn:
                for sid in ids_sel:
                    # apaga lançamentos de caixa vinculados às parcelas deste serviço
                    rows_inst = conn.execute(
                        """
                        SELECT ri.id
                        FROM revenue_installments ri
                        JOIN revenue r ON r.id = ri.revenue_id
                        WHERE r.service_id = ? AND r.company_id = ?
                        """,
                        (sid, cid),
                    ).fetchall()
                    inst_ids = [ri["id"] for ri in rows_inst]
                    if inst_ids:
                        qmarks = ",".join("?" for _ in inst_ids)
                        conn.execute(
                            f"DELETE FROM cash_ledger WHERE company_id=? AND link_tipo='revenue_installment' AND link_id IN ({qmarks})",
                            (cid, *inst_ids),
                        )

                    # apaga parcelas e receita
                    conn.execute(
                        """
                        DELETE FROM revenue_installments
                        WHERE revenue_id IN (SELECT id FROM revenue WHERE service_id=? AND company_id=?)
                        """,
                        (sid, cid),
                    )
                    conn.execute(
                        "DELETE FROM revenue WHERE service_id=? AND company_id=?",
                        (sid, cid),
                    )

                    # vínculos
                    conn.execute("DELETE FROM service_employees WHERE service_id=?", (sid,))
                    conn.execute("DELETE FROM service_equipments WHERE service_id=?", (sid,))

                    # serviço
                    conn.execute("DELETE FROM services WHERE id=? AND company_id=?", (sid, cid))

                conn.commit()
            st.warning("Registros excluídos.")
            st.rerun()

    # ======================================================
    # PDF PRO — Impressão em lote (1 página+ por OS)
    # ======================================================
    with colB:
        if st.button("🖨️ OS (PDF Pro)", key="btn_pdf_pro") and ids_sel:
            pdf_bytes = generate_os_pdf_pro(ids_sel, cid)
            st.download_button(
                "⬇️ Baixar OS (PDF Pro)",
                pdf_bytes,
                file_name="OS_lote_pro.pdf",
                mime="application/pdf",
                key="dl_os_pdf_pro",
            )

    with colC:
        st.write("")

# ---------------------------------
# Recebimentos (parcelas)
# ---------------------------------
st.divider()
st.subheader("💰 Recebíveis (parcelas)")

with get_conn() as conn:
    parc = conn.execute(
        """
        SELECT ri.id, r.service_id, s.data as data_servico, c.nome as cliente,
               ri.num_parcela, ri.due_date, ri.amount, ri.paid, ri.paid_date
        FROM revenue_installments ri
        JOIN revenue r ON r.id=ri.revenue_id
        JOIN services s ON s.id=r.service_id
        LEFT JOIN clients c ON c.id=s.client_id
        WHERE s.company_id=? AND ri.paid=0
        ORDER BY date(ri.due_date) ASC, ri.id ASC
        """,
        (cid,),
    ).fetchall()

rows_parc = [{k: r[k] for k in r.keys()} for r in parc]
df_parc = pd.DataFrame(rows_parc)
if not df_parc.empty and "due_date" in df_parc.columns:
    def _fmt_due(x):
        try:
            return datetime.fromisoformat(x).strftime("%d/%m/%Y")
        except Exception:
            return x
    df_parc["due_date"] = df_parc["due_date"].apply(_fmt_due)
st.dataframe(df_parc, use_container_width=True)

ids_pagar = st.multiselect(
    "Selecionar parcelas recebidas",
    [int(r["id"]) for r in parc],
    key="ms_parc_recebidas",
)
if st.button("Marcar como recebidas", key="btn_marcar_recebidas") and ids_pagar:
    now = datetime.now().isoformat(timespec="seconds")
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
            conn.execute(
                "UPDATE revenue_installments SET paid=1, paid_date=? WHERE id=?",
                (now, pid),
            )
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

# ---------------------------------
# Lembretes de não recebidos
# ---------------------------------
st.subheader("🔔 Lembretes de parcelas vencendo / vencidas")
with get_conn() as conn:
    alert = conn.execute(
        """
        SELECT ri.id, s.id as service_id, c.nome as cliente, ri.due_date, ri.amount
        FROM revenue_installments ri
        JOIN revenue r ON r.id=ri.revenue_id
        JOIN services s ON s.id=r.service_id
        LEFT JOIN clients c ON c.id=s.client_id
        WHERE s.company_id=? AND ri.paid=0
        ORDER BY date(ri.due_date) ASC, ri.id ASC
        """,
        (cid,),
    ).fetchall()

rows_alert = [{k: r[k] for k in r.keys()} for r in alert]
if rows_alert:
    df_alert = pd.DataFrame(rows_alert)
    if "due_date" in df_alert.columns:
        def _fmt_alert(x):
            try:
                return datetime.fromisoformat(x).strftime("%d/%m/%Y")
            except Exception:
                return x
        df_alert["due_date"] = df_alert["due_date"].apply(_fmt_alert)
    st.dataframe(df_alert, use_container_width=True)
    st.caption("Envie lembrete por e-mail/WhatsApp com links rápidos abaixo.")
else:
    st.info("Sem parcelas pendentes.")


# ============================================================
# ====================== PDF PRO MAKER =======================
# ============================================================

def _rv(row, key, default=""):
    """Row value safe: funciona para sqlite3.Row e dict."""
    try:
        v = row[key]
        return v if v is not None else default
    except Exception:
        return default


def _fmt_date_iso(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except Exception:
        return str(iso)


def _fmt_money(v) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {v}"


def _os_number(sid: int, dt_iso: str | None) -> str:
    ano = ""
    try:
        ano = datetime.fromisoformat(dt_iso).strftime("%Y") if dt_iso else ""
    except Exception:
        pass
    return f"{sid:06d}" + (f"/{ano}" if ano else "")


def _split_desc(desc: str) -> list[str]:
    """Quebra descrição em itens (por linhas)."""
    if not desc:
        return []
    parts = [x.strip("-• \t") for x in str(desc).splitlines()]
    return [x for x in parts if x]


def _fetch_company_company(cid: int):
    with get_conn() as conn:
        comp = conn.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    return comp


def _fetch_service_bundle(sid: int, cid: int):
    with get_conn() as conn:
        srv = conn.execute(
            "SELECT * FROM services WHERE id=? AND company_id=?",
            (sid, cid),
        ).fetchone()
        if not srv:
            return None

        cli = None
        client_id = _rv(srv, "client_id", None)
        if client_id:
            cli = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()

        emps = conn.execute(
            """
            SELECT e.nome, e.funcao
            FROM employees e
            JOIN service_employees se ON se.employee_id=e.id
            WHERE se.service_id=?
            ORDER BY e.nome
            """,
            (sid,),
        ).fetchall()

        eqps = conn.execute(
            """
            SELECT e.descricao
            FROM equipment e
            JOIN service_equipments se ON se.equipment_id=e.id
            WHERE se.service_id=?
            ORDER BY e.descricao
            """,
            (sid,),
        ).fetchall()

        inst = conn.execute(
            """
            SELECT ri.num_parcela, ri.due_date, ri.amount, ri.paid, ri.paid_date
            FROM revenue_installments ri
            JOIN revenue r ON r.id=ri.revenue_id
            WHERE r.service_id=?
            ORDER BY ri.num_parcela ASC
            """,
            (sid,),
        ).fetchall()

    return {
        "srv": srv,
        "cli": cli,
        "emps": emps,
        "eqps": eqps,
        "inst": inst,
    }


def generate_os_pdf_pro(ids: list[int], company_id: int) -> bytes:
    """Gera um único PDF com uma OS por página (mais de uma página por OS se precisar)."""
    # Tenta ReportLab; se falhar, usa fpdf2
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor
        from reportlab.lib.utils import simpleSplit
        from reportlab.graphics.barcode import qr

        comp = _fetch_company_company(company_id)

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        W, H = A4

        brand_primary = HexColor("#0F172A")   # slate-900
        brand_accent  = HexColor("#2563EB")   # blue-600
        brand_muted   = HexColor("#CBD5E1")   # slate-300
        line_gray     = HexColor("#E2E8F0")   # slate-200

        def header(cnv, y0, sid, srv_row):
            cnv.setFillColor(brand_primary)
            cnv.rect(0, H-40*mm, W, 40*mm, stroke=0, fill=1)

            # Título + número OS
            cnv.setFillColor(HexColor("#FFFFFF"))
            cnv.setFont("Helvetica-Bold", 18)
            cnv.drawString(20*mm, H-18*mm, "ORDEM DE SERVIÇO")
            cnv.setFont("Helvetica", 10)
            osnum = _os_number(sid, _rv(srv_row, "data", ""))
            cnv.drawRightString(W-20*mm, H-18*mm, f"OS Nº {osnum}")

            # Empresa (razão/CNPJ/contatos)
            cnv.setFont("Helvetica-Bold", 11)
            comp_nome = _rv(comp, "razao_social", "EMPRESA")
            cnv.drawString(20*mm, H-28*mm, comp_nome)
            cnv.setFont("Helvetica", 9)
            cnpj = _rv(comp, "cnpj", "")
            linha2 = []
            if cnpj: linha2.append(f"CNPJ: {cnpj}")
            logradouro = _rv(comp, "logradouro", "")
            numero     = _rv(comp, "numero", "")
            cidade     = _rv(comp, "cidade", "")
            uf         = _rv(comp, "estado", "")
            if cidade or uf:
                linha2.append(f"{cidade} - {uf}")
            if linha2:
                cnv.drawString(20*mm, H-33*mm, " · ".join(linha2))

            # QR com metadados (não é link externo, mas ajuda a identificar)
            try:
                payload = f"OS:{osnum};EMP:{comp_nome}"
                qr_code = qr.QrCodeWidget(payload)
                b = qr_code.getBounds()
                w = b[2] - b[0]
                h = b[3] - b[1]
                size = 18*mm
                d = size / max(w, h)
                cnv.saveState()
                cnv.translate(W-20*mm-size, H-20*mm-size)
                cnv.scale(d, d)
                qr_code.drawOn(cnv, 0, 0)
                cnv.restoreState()
            except Exception:
                pass

        def section_title(cnv, y, txt):
            cnv.setFillColor(brand_accent)
            cnv.rect(20*mm, y-8*mm, W-40*mm, 8*mm, stroke=0, fill=1)
            cnv.setFillColor(HexColor("#FFFFFF"))
            cnv.setFont("Helvetica-Bold", 11)
            cnv.drawString(22*mm, y-6.5*mm, txt)
            return y-10*mm

        def box_kv(cnv, y, pairs: list[tuple[str, str]], per_row=2):
            """Desenha pares chave:valor em grade leve."""
            cnv.setFont("Helvetica", 9)
            cnv.setFillColor(HexColor("#000000"))
            colw = (W-40*mm)/per_row
            x = 20*mm
            rowh = 8.5*mm
            for i, (k, v) in enumerate(pairs):
                col = i % per_row
                if col == 0 and i > 0:
                    y -= rowh
                    x = 20*mm
                cnv.setFillColor(line_gray)
                cnv.rect(x, y-rowh+1.5*mm, colw-2*mm, rowh-2*mm, stroke=0, fill=1)
                cnv.setFillColor(brand_primary)
                cnv.setFont("Helvetica-Bold", 8)
                cnv.drawString(x+2*mm, y-2.5*mm, k.upper())
                cnv.setFont("Helvetica", 9)
                cnv.setFillColor(HexColor("#000000"))
                # wrap do valor
                lines = simpleSplit(v, "Helvetica", 9, colw-6*mm)
                if lines:
                    cnv.drawString(x+2*mm, y-6.5*mm, lines[0])
                x += colw
            return y- rowh - 2*mm

        def long_text(cnv, y, txt):
            cnv.setFillColor(HexColor("#000000"))
            cnv.setFont("Helvetica", 9)
            lines = simpleSplit(txt, "Helvetica", 9, W-40*mm)
            for ln in lines:
                if y < 25*mm:
                    footer(cnv)
                    cnv.showPage()
                    header(cnv, H, sid, srv)
                    y = H-50*mm
                    y = section_title(cnv, y, "DETALHAMENTO DO SERVIÇO")
                cnv.drawString(20*mm, y, ln)
                y -= 5.2*mm
            return y

        def bullet_list(cnv, y, items: list[str]):
            cnv.setFont("Helvetica", 9)
            cnv.setFillColor(HexColor("#000000"))
            for it in items:
                if y < 25*mm:
                    footer(cnv)
                    cnv.showPage()
                    header(cnv, H, sid, srv)
                    y = H-50*mm
                    y = section_title(cnv, y, "DETALHAMENTO DO SERVIÇO")
                wrapped = simpleSplit(it, "Helvetica", 9, W-46*mm)
                cnv.circle(22*mm, y+1.5*mm, 0.8*mm, fill=1, stroke=0)
                cnv.drawString(25*mm, y, wrapped[0])
                y -= 5.2*mm
                for rest in wrapped[1:]:
                    cnv.drawString(25*mm, y, rest)
                    y -= 5.2*mm
            return y

        def table_installments(cnv, y, inst_rows):
            if not inst_rows:
                return y
            cnv.setFont("Helvetica-Bold", 9)
            cnv.setFillColor(brand_primary)
            headers = ["Parcela", "Vencimento", "Valor", "Situação"]
            colw = [(W-40*mm)*0.15, (W-40*mm)*0.25, (W-40*mm)*0.25, (W-40*mm)*0.35]
            xs = [20*mm]
            for w_ in colw[:-1]:
                xs.append(xs[-1]+w_)
            # header bg
            cnv.setFillColor(brand_muted)
            cnv.rect(20*mm, y-7*mm, W-40*mm, 7*mm, stroke=0, fill=1)
            cnv.setFillColor(brand_primary)
            for i, h in enumerate(headers):
                cnv.drawString(xs[i]+2*mm, y-4.8*mm, h.upper())
            y -= 9*mm

            cnv.setFont("Helvetica", 9)
            cnv.setFillColor(HexColor("#000000"))
            for r in inst_rows:
                if y < 30*mm:
                    footer(cnv)
                    cnv.showPage()
                    header(cnv, H, sid, srv)
                    y = H-50*mm
                    y = section_title(cnv, y, "PARCELAS / RECEBÍVEIS")
                    # redesenha cabeçalho
                    cnv.setFillColor(brand_muted)
                    cnv.rect(20*mm, y-7*mm, W-40*mm, 7*mm, stroke=0, fill=1)
                    cnv.setFillColor(brand_primary)
                    for i, h in enumerate(headers):
                        cnv.drawString(xs[i]+2*mm, y-4.8*mm, h.upper())
                    y -= 9*mm
                    cnv.setFillColor(HexColor("#000000"))
                    cnv.setFont("Helvetica", 9)

                situ = "Pago" if int(_rv(r, "paid", 0)) == 1 else "Pendente"
                if int(_rv(r, "paid", 0)) == 1 and _rv(r, "paid_date", ""):
                    situ = f"Pago em {_fmt_date_iso(_rv(r, 'paid_date', ''))}"
                vals = [
                    str(_rv(r, "num_parcela", "")),
                    _fmt_date_iso(_rv(r, "due_date", "")),
                    _fmt_money(_rv(r, "amount", 0.0)),
                    situ,
                ]
                for i, v in enumerate(vals):
                    cnv.drawString(xs[i]+2*mm, y-4.5*mm, v)
                # linha
                cnv.setStrokeColor(line_gray)
                cnv.line(20*mm, y-6.2*mm, W-20*mm, y-6.2*mm)
                y -= 8*mm

            return y-2*mm

        def signatures(cnv, y):
            if y < 45*mm:
                footer(cnv)
                cnv.showPage()
                header(cnv, H, sid, srv)
                y = H-50*mm
            cnv.setStrokeColor(line_gray)
            cnv.line(35*mm, y-12*mm, 95*mm, y-12*mm)
            cnv.line(115*mm, y-12*mm, W-35*mm, y-12*mm)
            cnv.setFont("Helvetica", 9)
            cnv.setFillColor(HexColor("#000000"))
            cnv.drawCentredString((35+95)/2*mm, y-16*mm, "Assinatura do Responsável Técnico")
            cnv.drawCentredString((115+(W/mm-35))/2*mm, y-16*mm, "Assinatura do Cliente")
            return y-22*mm

        def footer(cnv):
            cnv.setStrokeColor(line_gray)
            cnv.line(20*mm, 15*mm, W-20*mm, 15*mm)
            cnv.setFont("Helvetica", 8)
            cnv.setFillColor(brand_primary)
            cnv.drawString(20*mm, 10.5*mm, "Documento gerado por locadora_finance")
            cnv.drawRightString(W-20*mm, 10.5*mm, f"Página {cnv.getPageNumber()}")

        # ====== LOOP de OS selecionadas
        for sid in ids:
            pack = _fetch_service_bundle(sid, company_id)
            if not pack:
                continue
            srv = pack["srv"]
            cli = pack["cli"]
            emps = pack["emps"]
            eqps = pack["eqps"]
            inst = pack["inst"]

            # CABEÇALHO
            header(c, H, sid, srv)
            y = H-50*mm

            # Cliente
            y = section_title(c, y, "DADOS DO CLIENTE")
            cli_pairs = [
                ("Cliente", _rv(cli, "nome", "-") if cli else "-"),
                ("Documento", _rv(cli, "doc", "-") if cli else "-"),
                ("Telefone", _rv(cli, "phone", "-") if cli else "-"),
                ("E-mail", _rv(cli, "email", "-") if cli else "-"),
                ("Endereço", " ".join(x for x in [
                    _rv(cli, "logradouro", ""),
                    _rv(cli, "numero", ""),
                    _rv(cli, "bairro", ""),
                    _rv(cli, "cidade", ""),
                    _rv(cli, "estado", ""),
                ] if x) if cli else "-"),
                ("CEP", _rv(cli, "cep", "-") if cli else "-"),
            ]
            y = box_kv(c, y, cli_pairs, per_row=2)

            # Serviço: resumo
            y = section_title(c, y, "RESUMO DO SERVIÇO")
            srv_pairs = [
                ("Data", _fmt_date_iso(_rv(srv, "data", ""))),
                ("Status", _rv(srv, "status", "").capitalize()),
                ("Classificação", "Fiscal" if int(_rv(srv, "fiscal", 1)) == 1 else "Gerencial"),
                ("Forma de Pagamento", _rv(srv, "forma_pagamento", "")),
                ("Parcelas", str(_rv(srv, "parcelas", 1))),
                ("Valor Total", _fmt_money(_rv(srv, "valor_total", 0.0))),
            ]
            y = box_kv(c, y, srv_pairs, per_row=3)

            # Detalhamento
            desc = _rv(srv, "descricao", "")
            items = _split_desc(desc)
            y = section_title(c, y, "DETALHAMENTO DO SERVIÇO")
            if items:
                y = bullet_list(c, y, items)
            else:
                y = long_text(c, y, desc or "-")

            # Equipe / Equipamentos
            if emps or eqps:
                y = section_title(c, y, "RECURSOS ALOCADOS")
                if emps:
                    nomes = [(" • " + _rv(e, "nome", "")) + (f" ({_rv(e,'funcao','')})" if _rv(e, "funcao", "") else "") for e in emps]
                    y = long_text(c, y, "Colaboradores:\n" + "\n".join(nomes))
                if eqps:
                    descs = [" • " + _rv(e, "descricao", "") for e in eqps]
                    y = long_text(c, y, ("Equipamentos:\n" if emps else "") + "\n".join(descs))

            # Parcelas / Recebíveis
            if inst:
                y = section_title(c, y, "PARCELAS / RECEBÍVEIS")
                y = table_installments(c, y, inst)

            # Observações (campo livre)
            y = section_title(c, y, "OBSERVAÇÕES E CONDIÇÕES")
            obs = (
                "Este documento comprova a contratação/execução dos serviços descritos. "
                "Garantias e responsabilidades seguem as normas aplicáveis e o contrato firmado entre as partes. "
                "Em caso de divergência, contate-nos imediatamente."
            )
            y = long_text(c, y, obs)

            # Assinaturas
            y = signatures(c, y)

            # Rodapé e próxima página
            footer(c)
            c.showPage()

        c.save()
        return buf.getvalue()

    except Exception:
        # Fallback para fpdf2 (layout simplificado, mas elegante)
        try:
            from fpdf import FPDF
        except Exception:
            # sem nada disponível
            return b"%PDF-1.4\n% Faltou reportlab e fpdf2\n"

        comp = _fetch_company_company(company_id)

        class PDF(FPDF):
            def header(self):
                self.set_fill_color(15, 23, 42)  # slate-900
                self.rect(0, 0, 210, 25, "F")
                self.set_text_color(255, 255, 255)
                self.set_font("Helvetica", "B", 16)
                self.set_xy(10, 7)
                self.cell(0, 8, "ORDEM DE SERVIÇO", 0, 1, "L")
                self.ln(2)

            def footer(self):
                self.set_y(-15)
                self.set_draw_color(226, 232, 240)
                self.line(10, self.get_y(), 200, self.get_y())
                self.set_font("Helvetica", "", 8)
                self.set_text_color(15, 23, 42)
                self.cell(0, 8, "Documento gerado por locadora_finance", 0, 0, "L")
                self.cell(0, 8, f"Página {self.page_no()}", 0, 0, "R")

        pdf = PDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=18)

        for sid in ids:
            pack = _fetch_service_bundle(sid, company_id)
            if not pack:
                continue
            srv = pack["srv"]
            cli = pack["cli"]
            emps = pack["emps"]
            eqps = pack["eqps"]
            inst = pack["inst"]

            pdf.add_page()

            # Número OS
            pdf.set_xy(10, 10)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, f"OS Nº {_os_number(sid, _rv(srv, 'data', ''))}", 0, 1, "R")

            # Empresa
            pdf.ln(8)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 6, _rv(comp, "razao_social", "EMPRESA"), 0, 1, "L")
            pdf.set_font("Helvetica", "", 9)
            cnpj = _rv(comp, "cnpj", "")
            cidade = _rv(comp, "cidade", "")
            uf = _rv(comp, "estado", "")
            linha2 = " · ".join([x for x in [f"CNPJ: {cnpj}" if cnpj else "", f"{cidade} - {uf}" if (cidade or uf) else ""] if x])
            if linha2:
                pdf.cell(0, 5, linha2, 0, 1, "L")

            # Cliente
            pdf.ln(2)
            pdf.set_fill_color(37, 99, 235)  # blue-600
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 7, "DADOS DO CLIENTE", 0, 1, "L", True)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, f"Cliente: {_rv(cli,'nome','-') if cli else '-'}")
            pdf.multi_cell(0, 5, f"Documento: {_rv(cli,'doc','-') if cli else '-'} · Telefone: {_rv(cli,'phone','-') if cli else '-'} · E-mail: {_rv(cli,'email','-') if cli else '-'}")
            end = " ".join(x for x in [
                _rv(cli, "logradouro", ""),
                _rv(cli, "numero", ""),
                _rv(cli, "bairro", ""),
                _rv(cli, "cidade", ""),
                _rv(cli, "estado", ""),
            ] if x) if cli else "-"
            pdf.multi_cell(0, 5, f"Endereço: {end} · CEP: {_rv(cli,'cep','-') if cli else '-'}")

            # Resumo
            pdf.ln(2)
            pdf.set_fill_color(37, 99, 235)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 7, "RESUMO DO SERVIÇO", 0, 1, "L", True)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, f"Data: {_fmt_date_iso(_rv(srv,'data',''))} · Status: {_rv(srv,'status','').capitalize()} · Classificação: {'Fiscal' if int(_rv(srv,'fiscal',1))==1 else 'Gerencial'}")
            pdf.multi_cell(0, 5, f"Forma: {_rv(srv,'forma_pagamento','')} · Parcelas: {str(_rv(srv,'parcelas',1))} · Valor Total: {_fmt_money(_rv(srv,'valor_total',0.0))}")

            # Detalhamento
            pdf.ln(2)
            pdf.set_fill_color(37, 99, 235)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 7, "DETALHAMENTO DO SERVIÇO", 0, 1, "L", True)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 9)
            desc = _rv(srv, "descricao", "")
            items = _split_desc(desc)
            if items:
                for it in items:
                    pdf.cell(4, 5, "•")
                    pdf.multi_cell(0, 5, it)
            else:
                pdf.multi_cell(0, 5, desc or "-")

            # Equipe / Equipamentos
            if emps or eqps:
                pdf.ln(1)
                pdf.set_fill_color(37, 99, 235)
                pdf.set_text_color(255, 255, 255)
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 7, "RECURSOS ALOCADOS", 0, 1, "L", True)
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("Helvetica", "", 9)
                if emps:
                    nomes = [(_rv(e, "nome", "")) + (f" ({_rv(e,'funcao','')})" if _rv(e, "funcao", "") else "") for e in emps]
                    pdf.multi_cell(0, 5, "Colaboradores: " + ", ".join(nomes))
                if eqps:
                    descs = [_rv(e, "descricao", "") for e in eqps]
                    pdf.multi_cell(0, 5, "Equipamentos: " + ", ".join(descs))

            # Parcelas
            if inst:
                pdf.ln(1)
                pdf.set_fill_color(37, 99, 235)
                pdf.set_text_color(255, 255, 255)
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 7, "PARCELAS / RECEBÍVEIS", 0, 1, "L", True)
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("Helvetica", "", 9)
                for r in inst:
                    situ = "Pendente"
                    if int(_rv(r, "paid", 0)) == 1:
                        situ = "Pago"
                        if _rv(r, "paid_date", ""):
                            situ += f" em {_fmt_date_iso(_rv(r,'paid_date',''))}"
                    pdf.multi_cell(0, 5, f"Parc. {_rv(r,'num_parcela','')} · Venc.: {_fmt_date_iso(_rv(r,'due_date',''))} · Valor: {_fmt_money(_rv(r,'amount',0.0))} · {situ}")

            # Observações
            pdf.ln(1)
            pdf.set_fill_color(37, 99, 235)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 7, "OBSERVAÇÕES E CONDIÇÕES", 0, 1, "L", True)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 9)
            obs = (
                "Este documento comprova a contratação/execução dos serviços descritos. "
                "Garantias e responsabilidades seguem as normas aplicáveis e o contrato firmado entre as partes."
            )
            pdf.multi_cell(0, 5, obs)

            # Assinaturas
            pdf.ln(12)
            y = pdf.get_y()
            pdf.line(25, y, 95, y)
            pdf.line(115, y, 185, y)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_y(y + 2)
            pdf.cell(70, 5, "Assinatura do Responsável Técnico", 0, 0, "C")
            pdf.set_x(115)
            pdf.cell(70, 5, "Assinatura do Cliente", 0, 1, "C")

        return pdf.output(dest="S").encode("latin-1")


# FIM
