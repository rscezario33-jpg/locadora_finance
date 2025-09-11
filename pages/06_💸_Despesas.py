# ============================================================
# 06_💸_Despesas.py
# ============================================================
from __future__ import annotations
import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

from session_helpers import require_company_with_picker
from db_core import get_conn

st.set_page_config(page_title="💸 Despesas", layout="wide")


def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()


def ensure_schema_exp():
    with get_conn() as conn:
        # Fornecedores
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS suppliers(
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
        # Despesas
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              company_id INTEGER NOT NULL,
              supplier_id INTEGER,
              fornecedor TEXT,      -- legado/rápido
              descricao TEXT,
              categoria TEXT,
              tags TEXT,
              forma_pagamento TEXT,
              data_lancamento TEXT,
              valor_total REAL,
              parcelas INTEGER DEFAULT 1
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
        # Caixa
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
ensure_schema_exp()
cid = require_company_with_picker()

st.title("💸 Despesas (a pagar)")

# --- Fornecedores
with st.expander("📇 Fornecedores (CPF/CNPJ, endereço)", expanded=False):
    with st.form("f_sup"):
        snome = st.text_input("Nome/Razão Social")
        sdoc = st.text_input("CPF/CNPJ")
        semail = st.text_input("E-mail")
        sphone = st.text_input("Telefone")
        saddr = st.text_area("Endereço")
        oks = st.form_submit_button("Salvar fornecedor")
        if oks:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO suppliers(company_id,nome,doc,email,phone,address) VALUES (?,?,?,?,?,?)",
                    (cid, snome, sdoc, semail, sphone, saddr),
                )
                conn.commit()
            st.success("Fornecedor salvo.")

    with get_conn() as conn:
        sups = conn.execute("SELECT * FROM suppliers WHERE company_id=? ORDER BY nome", (cid,)).fetchall()
    df_sups = pd.DataFrame([{k: r[k] for k in r.keys()} for r in sups])
    st.dataframe(df_sups, use_container_width=True)

# --- Lançar despesa (repetir N meses / categorias / tags)
with st.form("f_exp"):
    st.subheader("Lançar despesa")
    fornecedor = st.selectbox("Fornecedor (cadastro)", ["-"] + (df_sups["nome"].tolist() if not df_sups.empty else []))
    fornecedor_livre = st.text_input("Fornecedor (texto livre)")
    descricao = st.text_area("Descrição")
    categoria = st.text_input("Categoria")
    tags = st.text_input("Tags (separadas por vírgula)")
    forma = st.selectbox("Forma de pagamento", ["PIX", "TED", "Boleto", "Cartão", "Dinheiro", "Outro"])
    dt = st.date_input("Data de lançamento", value=date.today())
    valor = st.number_input("Valor total (R$)", min_value=0.0, step=0.01, format="%.2f")
    parcelas = st.number_input("Parcelas", min_value=1, max_value=120, value=1)
    repetir = st.number_input("Repetir por N meses (cópias futuras)", min_value=0, max_value=60, value=0)
    ok = st.form_submit_button("Salvar")
    if ok:
        with get_conn() as conn:
            # localizar supplier_id
            supplier_id = None
            if fornecedor and fornecedor != "-":
                row = conn.execute("SELECT id FROM suppliers WHERE company_id=? AND nome=?", (cid, fornecedor)).fetchone()
                supplier_id = row["id"] if row else None

            def inserir_uma_despesa(base_date: date):
                cur = conn.execute(
                    """
                    INSERT INTO expenses(company_id,supplier_id,fornecedor,descricao,categoria,tags,forma_pagamento,data_lancamento,valor_total,parcelas)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        cid,
                        supplier_id,
                        fornecedor_livre or fornecedor if fornecedor != "-" else fornecedor_livre,
                        descricao,
                        categoria,
                        tags,
                        forma,
                        base_date.isoformat(),
                        valor,
                        parcelas,
                    ),
                )
                exp_id = cur.lastrowid
                par_val = round(valor / parcelas, 2)
                vals = [par_val] * parcelas
                dif = round(valor - sum(vals), 2)
                vals[-1] += dif
                for i in range(parcelas):
                    due = (base_date.replace(day=1) + timedelta(days=31 * i)).replace(day=base_date.day)
                    conn.execute(
                        "INSERT INTO expense_installments(expense_id,num_parcela,due_date,amount) VALUES (?,?,?,?)",
                        (exp_id, i + 1, due.isoformat(), vals[i]),
                    )
                return exp_id

            # atual
            inserir_uma_despesa(dt)
            # cópias futuras
            b = dt
            for _ in range(int(repetir)):
                b = (b.replace(day=1) + timedelta(days=31)).replace(day=dt.day)
                inserir_uma_despesa(b)

            conn.commit()
        st.success("Despesa(s) lançada(s) com parcelas geradas.")

st.divider()
st.subheader("Parcelas em aberto / pagamento")

with get_conn() as conn:
    rows = conn.execute(
        """
        SELECT ei.id, COALESCE(s.nome, e.fornecedor) AS fornecedor, e.descricao, e.categoria, e.tags,
               e.forma_pagamento, ei.num_parcela, ei.due_date, ei.amount
        FROM expense_installments ei
        JOIN expenses e ON e.id=ei.expense_id
        LEFT JOIN suppliers s ON s.id=e.supplier_id
        WHERE e.company_id=? AND ei.paid=0
        ORDER BY date(ei.due_date) ASC
        """,
        (cid,),
    ).fetchall()

df_rows = pd.DataFrame([{k: r[k] for k in r.keys()} for r in rows])
if not df_rows.empty:
    df_rows["due_date"] = df_rows["due_date"].apply(lambda x: datetime.fromisoformat(x).strftime("%d/%m/%Y"))
st.dataframe(df_rows, use_container_width=True)

ids = st.multiselect("Selecionar parcelas para quitar", [r["id"] for r in rows])
if st.button("Quitar selecionadas") and ids:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        for pid in ids:
            amt = conn.execute(
                "SELECT ei.amount FROM expense_installments ei WHERE ei.id=?",
                (pid,),
            ).fetchone()
            conn.execute("UPDATE expense_installments SET paid=1, paid_date=? WHERE id=?", (now, pid))
            if amt:
                conn.execute(
                    "INSERT INTO cash_ledger(company_id,data,tipo,valor,descricao,link_tipo,link_id) VALUES (?,?,?,?,?,?,?)",
                    (
                        cid,
                        now,
                        "out",
                        amt["amount"],
                        f"Pagamento parcela despesa #{pid}",
                        "expense_installment",
                        pid,
                    ),
                )
        conn.commit()
    st.success("Parcelas quitadas e caixa atualizado.")
    st.rerun()

# Caixa (resumo simples)
st.divider()
st.subheader("📦 Caixa – resumo do dia")
with get_conn() as conn:
    hoje_iso = date.today().isoformat()
    caixa = conn.execute(
        "SELECT tipo, SUM(valor) as total FROM cash_ledger WHERE company_id=? AND date(data)=date(?) GROUP BY tipo",
        (cid, hoje_iso),
    ).fetchall()
rows_cx = {r["tipo"]: r["total"] for r in caixa}
entradas = rows_cx.get("in", 0.0) or 0.0
saidas = rows_cx.get("out", 0.0) or 0.0
st.metric("Entradas (hoje)", f"R$ {entradas:.2f}")
st.metric("Saídas (hoje)", f"R$ {saidas:.2f}")
