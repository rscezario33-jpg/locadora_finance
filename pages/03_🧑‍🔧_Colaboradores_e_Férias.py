# 03_🧑‍🔧_Colaboradores_e_Férias.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional

import pandas as pd
import streamlit as st

from session_helpers import require_company_with_picker
from db_core import get_conn

# ==============================
# Config
# ==============================
st.set_page_config(page_title="🧑‍🔧 Colaboradores & Férias", layout="wide")

# ==============================
# Helpers / Schema
# ==============================
def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()


def ensure_schema():
    """Create/adjust minimally required tables/columns."""
    with get_conn() as conn:
        # employees
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
        # vacations
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vacations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                inicio_gozo TEXT,
                fim_gozo TEXT,
                dias INTEGER,
                base REAL,
                um_terco REAL,
                inss REAL,
                fgts REAL,
                irrf REAL,
                liquido REAL,
                observacao TEXT
            )
            """
        )
        # leaves (afastamentos)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leaves(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                tipo TEXT,
                inicio TEXT,
                fim TEXT,
                observacao TEXT
            )
            """
        )
        # cash ledger (entrada/saída)
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


def fmt_dmy(x: Optional[str | date]) -> str:
    if x is None:
        return ""
    if isinstance(x, date):
        return x.strftime("%d/%m/%Y")
    try:
        return datetime.fromisoformat(x).strftime("%d/%m/%Y")
    except Exception:
        return str(x)


# 2025 Tabelas (ajustáveis no topo do app se precisar)
INSS_TETO_2025 = 8157.41
INSS_FAIXAS_2025 = [
    (0.00, 1518.00, 0.075),
    (1518.01, 2793.88, 0.09),
    (2793.89, 4190.83, 0.12),
    (4190.84, 8157.41, 0.14),
]

# IRRF (tabela progressiva mensal - vigência a partir de 05/2025)
IRRF_TABELA_2025M = [
    (0.00, 2428.80, 0.00, 0.00),
    (2428.81, 2826.65, 0.075, 182.16),
    (2826.66, 3751.05, 0.15, 381.44),
    (3751.06, 4664.68, 0.225, 662.77),
    (4664.69, 9999999.0, 0.275, 896.00),
]
IRRF_DED_DEP = 189.59  # por dependente/mês
IRRF_DESC_SIMPLIFICADO = 564.80  # opção alternativa (após 05/2023, mantida em 2025)


def calc_inss_empregado(base: float) -> float:
    """Calcula INSS do segurado (progressivo), limitado ao teto."""
    sc = min(base, INSS_TETO_2025)
    total = 0.0
    for a, b, aliq in INSS_FAIXAS_2025:
        faixa = max(0.0, min(sc, b) - a)
        if faixa > 0:
            total += faixa * aliq
    return round(total, 2)


def calc_irrf(base: float, dependentes: int = 0, usar_desc_simpl: bool = True) -> float:
    """IRRF mensal aplicado 'em separado' sobre as férias.
    Base já deve vir após INSS. Permite desconto simplificado (R$ 564,80) opcional.
    """
    base_calc = max(0.0, base - (IRRF_DESC_SIMPLIFICADO if usar_desc_simpl else dependentes * IRRF_DED_DEP))
    for a, b, aliq, ded in IRRF_TABELA_2025M:
        if a <= base_calc <= b:
            return round(max(0.0, base_calc * aliq - ded), 2)
    return 0.0


def calc_ferias(
    salario: float,
    dias: int,
    media_adic: float = 0.0,
    vender_dias: int = 0,
    inss_incide_terco: bool = True,
    dependentes: int = 0,
    usar_desc_simpl: bool = True,
) -> Dict[str, float]:
    dias = max(0, min(30, int(dias)))
    vender_dias = max(0, min(10, int(vender_dias)))

    # Remuneração férias proporcional aos dias de gozo + 1/3 constitucional
    base_fixas = salario + media_adic
    remun_ferias = base_fixas * (dias / 30.0)
    um_terco = remun_ferias / 3.0

    # Abono pecuniário (venda de 1/3 das férias) – não entra no gozo
    abono = base_fixas * (vender_dias / 30.0)

    fgts = round(0.08 * (remun_ferias + um_terco + abono), 2)  # FGTS incide sobre férias + 1/3 + abono

    # INSS do segurado: usualmente incide sobre férias gozadas; opção p/ incluir 1/3
    base_inss = remun_ferias + (um_terco if inss_incide_terco else 0.0) + abono
    inss = calc_inss_empregado(base_inss)

    # IRRF: férias tributadas em separado no mês do pagamento, base após INSS
    base_ir = (remun_ferias + um_terco + abono) - inss
    irrf = calc_irrf(base_ir, dependentes=dependentes, usar_desc_simpl=usar_desc_simpl)

    bruto = round(remun_ferias + um_terco + abono, 2)
    liquido = round(bruto - inss - irrf, 2)

    return {
        "remun_ferias": round(remun_ferias, 2),
        "um_terco": round(um_terco, 2),
        "abono": round(abono, 2),
        "fgts": fgts,
        "inss": inss,
        "irrf": irrf,
        "bruto": bruto,
        "liquido": liquido,
    }


# ==============================
# App
# ==============================
require_company()
ensure_schema()
cid = require_company_with_picker()

st.title("🧑‍🔧 Colaboradores & Férias")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Cadastrar colaborador")
    with st.form("form_emp"):
        matricula = st.text_input("Matrícula")
        nome = st.text_input("Nome", key="nome_colab")
        funcao = st.text_input("Função")
        salario = st.number_input("Salário (R$)", min_value=0.0, step=0.01, format="%.2f")
        diaria = st.number_input("Valor da diária (R$)", min_value=0.0, step=0.01, format="%.2f")
        adm = st.date_input("Data de admissão", value=date.today())
        ok = st.form_submit_button("Salvar")
        if ok:
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO employees(company_id,matricula,nome,funcao,salario,diaria,data_admissao)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (cid, matricula, nome, funcao, salario, diaria, adm.isoformat()),
                )
                conn.commit()
            st.success("Colaborador salvo.")

with col2:
    st.subheader("Colaboradores")
    incluir_inativos = st.checkbox("Incluir inativos", value=False)
    with get_conn() as conn:
        if incluir_inativos:
            emps = conn.execute(
                "SELECT * FROM employees WHERE company_id=? ORDER BY nome",
                (cid,),
            ).fetchall()
        else:
            emps = conn.execute(
                "SELECT * FROM employees WHERE company_id=? AND COALESCE(ativo,1)=1 ORDER BY nome",
                (cid,),
            ).fetchall()

    df_emps = pd.DataFrame([{k: r[k] for k in r.keys()} for r in emps])
    if not df_emps.empty:
        for col in ["data_admissao", "data_rescisao"]:
            if col in df_emps.columns:
                df_emps[col] = df_emps[col].apply(fmt_dmy)
    st.dataframe(df_emps, use_container_width=True)

    with st.expander("📌 Marcar rescisão / mover para inativos"):
        emp_sel = st.selectbox(
            "Colaborador",
            df_emps["nome"].tolist() if not df_emps.empty else [],
            key="colab_sb_rescisao",
        )
        resc = st.date_input("Data de rescisão", value=date.today())
        if st.button("Aplicar rescisão"):
            if emp_sel:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE employees SET data_rescisao=?, ativo=0 WHERE company_id=? AND nome=?",
                        (resc.isoformat(), cid, emp_sel),
                    )
                    conn.commit()
                st.success("Rescisão aplicada. Registro movido para inativos.")
                st.rerun()

st.divider()
st.subheader("Férias e afastamentos")

with get_conn() as conn:
    emps = conn.execute(
        "SELECT id,nome,data_admissao FROM employees WHERE company_id=? AND COALESCE(ativo,1)=1 ORDER BY nome",
        (cid,),
    ).fetchall()
emp_map = {e["nome"]: (e["id"], e["data_admissao"]) for e in emps}
emp_name = st.selectbox(
    "Colaborador",
    list(emp_map.keys()) if emp_map else [],
    key="colab_sb_ferias",
)

if emp_name:
    emp_id, adm_iso = emp_map[emp_name]
    adm_dt = datetime.fromisoformat(adm_iso).date() if adm_iso else date.today()

    # períodos aquisitivos/concessivos (3 próximos)
    def compute_vacation_periods(admissao: date, qtd: int = 3) -> List[Dict[str, str]]:
        base = admissao
        out = []
        for i in range(qtd):
            aq_ini = base.replace(year=base.year + i)
            aq_fim = aq_ini.replace(year=aq_ini.year + 1) - timedelta(days=1)
            con_ini = aq_fim + timedelta(days=1)
            con_fim = con_ini.replace(year=con_ini.year + 1) - timedelta(days=1)
            out.append(
                {
                    "aquisitivo_inicio": fmt_dmy(aq_ini),
                    "aquisitivo_fim": fmt_dmy(aq_fim),
                    "concessivo_inicio": fmt_dmy(con_ini),
                    "concessivo_fim": fmt_dmy(con_fim),
                }
            )
        return out

    st.caption("**Períodos aquisitivos/concessivos (próximos 3):**")
    periods = compute_vacation_periods(adm_dt, 3)
    st.table(
        [
            {
                "Aquisitivo início": p["aquisitivo_inicio"],
                "Aquisitivo fim": p["aquisitivo_fim"],
                "Concessivo início": p["concessivo_inicio"],
                "Concessivo fim": p["concessivo_fim"],
            }
            for p in periods
        ]
    )

    left, right = st.columns([1, 1])
    with left:
        st.markdown("**Lançar gozo de férias**")
        with st.form("form_ferias"):
            dias = st.slider("Dias de gozo", 5, 30, 30, step=1)
            vender = st.slider("Vender dias (abono)", 0, 10, 0)
            media_adic = st.number_input("Média de adicionais (R$)", min_value=0.0, step=0.01, format="%.2f")
            dependentes = st.number_input("Dependentes p/ IRRF", min_value=0, max_value=20, value=0)
            incide_terco_inss = st.checkbox("INSS incide sobre 1/3 de férias", value=True)
            usar_desc_simpl = st.checkbox("IRRF com desconto simplificado (R$ 564,80)", value=True)
            ini = st.date_input("Início do gozo", value=date.today(), key="f_ini")
            fim = st.date_input("Fim do gozo", value=date.today(), key="f_fim")
            obs = st.text_input("Observação", key="f_obs")
            okf = st.form_submit_button("Calcular e lançar")
            if okf:
                # buscar salário atual
                with get_conn() as conn:
                    row = conn.execute("SELECT salario FROM employees WHERE id=?", (emp_id,)).fetchone()
                salario_atual = float(row["salario"]) if row else 0.0
                r = calc_ferias(
                    salario=salario_atual,
                    dias=dias,
                    media_adic=media_adic,
                    vender_dias=vender,
                    inss_incide_terco=incide_terco_inss,
                    dependentes=dependentes,
                    usar_desc_simpl=usar_desc_simpl,
                )
                resumo = pd.DataFrame(
                    [
                        {"Item": "Remuneração férias", "R$": r["remun_ferias"]},
                        {"Item": "+ 1/3 constitucional", "R$": r["um_terco"]},
                        {"Item": "+ Abono (venda de dias)", "R$": r["abono"]},
                        {"Item": "= Bruto", "R$": r["bruto"]},
                        {"Item": "- INSS", "R$": r["inss"]},
                        {"Item": "- IRRF", "R$": r["irrf"]},
                        {"Item": "= Líquido a pagar", "R$": r["liquido"]},
                        {"Item": "FGTS (8%) – depósito", "R$": r["fgts"]},
                    ]
                )

                # Persistir registro
                with get_conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO vacations(employee_id,inicio_gozo,fim_gozo,dias,base,um_terco,inss,fgts,irrf,liquido,observacao)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            emp_id,
                            ini.isoformat(),
                            fim.isoformat(),
                            dias,
                            r["remun_ferias"],
                            r["um_terco"],
                            r["inss"],
                            r["fgts"],
                            r["irrf"],
                            r["liquido"],
                            obs,
                        ),
                    )
                    conn.commit()
                st.success("Férias lançadas.")

                # Guarda para exibir/baixar FORA do form
                st.session_state["ferias_resumo_df"] = resumo
                st.session_state["ferias_resumo_meta"] = {"emp_id": emp_id, "ini": ini.isoformat()}

        # Fora do form: mostra o resumo e botões de download
        if "ferias_resumo_df" in st.session_state:
            resumo = st.session_state["ferias_resumo_df"]
            meta = st.session_state.get("ferias_resumo_meta", {})
            st.dataframe(resumo, use_container_width=True, hide_index=True)

            # CSV
            buf_csv = io.StringIO()
            resumo.to_csv(buf_csv, index=False, sep=";", decimal=",")
            st.download_button(
                "⬇️ CSV (resumo)",
                buf_csv.getvalue().encode("utf-8"),
                file_name=f"ferias_{meta.get('emp_id','')}_{meta.get('ini','')}.csv",
                mime="text/csv",
                key="dl_csv_resumo",
            )

            # XLSX
            try:
                import xlsxwriter  # noqa: F401
                xbuf = io.BytesIO()
                with pd.ExcelWriter(xbuf, engine="xlsxwriter") as w:
                    resumo.to_excel(w, index=False, sheet_name="Férias")
                st.download_button(
                    "⬇️ XLSX (resumo)",
                    xbuf.getvalue(),
                    file_name=f"ferias_{meta.get('emp_id','')}_{meta.get('ini','')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_xlsx_resumo",
                )
            except Exception:
                st.info("Para XLSX, instale 'xlsxwriter'.")

            if st.button("Limpar resumo", key="clear_resumo"):
                st.session_state.pop("ferias_resumo_df", None)
                st.session_state.pop("ferias_resumo_meta", None)
                st.rerun()

    with right:
        st.markdown("**Lançar afastamento**")
        with st.form("form_afast"):
            tipo = st.text_input("Tipo (ex: INSS, médico, sem remuneração)")
            ini = st.date_input("Início", value=date.today(), key="a_ini")
            fim = st.date_input("Fim", value=date.today(), key="a_fim")
            obs = st.text_input("Observação", key="a_obs")
            oka = st.form_submit_button("Salvar afastamento")
            if oka:
                with get_conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO leaves(employee_id,tipo,inicio,fim,observacao)
                        VALUES (?,?,?,?,?)
                        """,
                        (emp_id, tipo, ini.isoformat(), fim.isoformat(), obs),
                    )
                    conn.commit()
                st.success("Afastamento lançado.")

    st.markdown("#### Registros de férias")
    with get_conn() as conn:
        vf = conn.execute(
            "SELECT * FROM vacations WHERE employee_id=? ORDER BY date(inicio_gozo) DESC",
            (emp_id,),
        ).fetchall()
    df_vf = pd.DataFrame([{k: r[k] for k in r.keys()} for r in vf])
    if not df_vf.empty:
        for c in ["inicio_gozo", "fim_gozo"]:
            if c in df_vf:
                df_vf[c] = df_vf[c].apply(fmt_dmy)
    st.dataframe(df_vf, use_container_width=True)

    st.markdown("#### Registros de afastamentos")
    with get_conn() as conn:
        af = conn.execute(
            "SELECT * FROM leaves WHERE employee_id=? ORDER BY date(inicio) DESC",
            (emp_id,),
        ).fetchall()
    df_af = pd.DataFrame([{k: r[k] for k in r.keys()} for r in af])
    if not df_af.empty:
        for c in ["inicio", "fim"]:
            if c in df_af:
                df_af[c] = df_af[c].apply(fmt_dmy)
    st.dataframe(df_af, use_container_width=True)

# Exportação da lista de colaboradores (PDF/XLSX/CSV)
st.divider()
st.subheader("Exportações")
with get_conn() as conn:
    emps2 = conn.execute(
        "SELECT matricula,nome,funcao,salario,diaria,data_admissao,data_rescisao,COALESCE(ativo,1) as ativo FROM employees WHERE company_id=?",
        (cid,),
    ).fetchall()
df_list = pd.DataFrame([{k: r[k] for k in r.keys()} for r in emps2])
if not df_list.empty:
    for col in ["data_admissao", "data_rescisao"]:
        if col in df_list:
            df_list[col] = df_list[col].apply(fmt_dmy)

    # CSV
    csv_buf = io.StringIO()
    df_list.to_csv(csv_buf, index=False, sep=";", decimal=",")
    st.download_button(
        "⬇️ CSV (lista)",
        csv_buf.getvalue().encode("utf-8"),
        file_name="colaboradores.csv",
        mime="text/csv",
        key="dl_csv_lista",
    )

    # XLSX
    try:
        import xlsxwriter  # noqa: F401
        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine="xlsxwriter") as w:
            df_list.to_excel(w, index=False, sheet_name="Colaboradores")
        st.download_button(
            "⬇️ XLSX (lista)",
            xbuf.getvalue(),
            file_name="colaboradores.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_xlsx_lista",
        )
    except Exception:
        st.info("Para XLSX, instale 'xlsxwriter'.")

    # PDF (básico via ReportLab se disponível)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from reportlab.lib.utils import simpleSplit

        pbuf = io.BytesIO()
        c = canvas.Canvas(pbuf, pagesize=A4)
        W, H = A4
        y = H - 20 * mm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20 * mm, y, "Lista de Colaboradores")
        y -= 8 * mm
        c.setFont("Helvetica", 9)
        for _, row in df_list.iterrows():
            linha = f"{row.get('matricula','')} | {row.get('nome','')} | {row.get('funcao','')} | R$ {row.get('salario',0):.2f} | {row.get('data_admissao','')} | {row.get('data_rescisao','')} | {'Ativo' if int(row.get('ativo',1))==1 else 'Inativo'}"
            wrapped = simpleSplit(linha, "Helvetica", 9, W - 40 * mm)
            for piece in wrapped:
                if y < 20 * mm:
                    c.showPage()
                    y = H - 20 * mm
                    c.setFont("Helvetica", 9)
                c.drawString(20 * mm, y, piece)
                y -= 6 * mm
        c.showPage()
        c.save()
        st.download_button(
            "⬇️ PDF (lista)",
            pbuf.getvalue(),
            file_name="colaboradores.pdf",
            mime="application/pdf",
            key="dl_pdf_lista",
        )
    except Exception:
        st.info("Para PDF, instale 'reportlab'.")
