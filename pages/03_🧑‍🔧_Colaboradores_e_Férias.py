from session_helpers import require_company_with_picker
import streamlit as st
from datetime import date, datetime
from db_core import get_conn
from utils import compute_vacation_periods

st.set_page_config(page_title="🧑‍🔧 Colaboradores & Férias", layout="wide")

def require_company():
    if "company" not in st.session_state or st.session_state.company is None:
        st.stop()

require_company()
cid = require_company_with_picker()

st.title("🧑‍🔧 Colaboradores & Férias")

col1, col2 = st.columns([1,1])

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
                conn.execute("""INSERT INTO employees(company_id,matricula,nome,funcao,salario,diaria,data_admissao)
                                VALUES (?,?,?,?,?,?,?)""",
                             (cid, matricula, nome, funcao, salario, diaria, adm.isoformat()))
                conn.commit()
            st.success("Colaborador salvo.")

with col2:
    st.subheader("Colaboradores")
    with get_conn() as conn:
        emps = conn.execute("SELECT * FROM employees WHERE company_id=? ORDER BY nome", (cid,)).fetchall()
    st.dataframe([{k: r[k] for k in r.keys()} for r in emps], use_container_width=True)

st.divider()
st.subheader("Férias e afastamentos")

with get_conn() as conn:
    emps = conn.execute("SELECT id,nome,data_admissao FROM employees WHERE company_id=? ORDER BY nome", (cid,)).fetchall()
emp_map = {e["nome"]: (e["id"], e["data_admissao"]) for e in emps}
emp_name = st.selectbox("Colaborador", list(emp_map.keys()) if emp_map else [])
if emp_name:
    emp_id, adm_iso = emp_map[emp_name]
    adm_dt = datetime.fromisoformat(adm_iso).date()
    st.caption("**Períodos aquisitivos/concessivos (próximos 3):**")
    periods = compute_vacation_periods(adm_dt, 3)
    st.table([{
        "Aquisitivo início": p["aquisitivo_inicio"],
        "Aquisitivo fim": p["aquisitivo_fim"],
        "Concessivo início": p["concessivo_inicio"],
        "Concessivo fim": p["concessivo_fim"]
    } for p in periods])

    left, right = st.columns([1,1])
    with left:
        st.markdown("**Lançar gozo de férias**")
        with st.form("form_ferias"):
            ini = st.date_input("Início gozo", value=date.today())
            fim = st.date_input("Fim gozo", value=date.today())
            dias = (fim - ini).days + 1
            obs = st.text_input("Observação")
            okf = st.form_submit_button("Salvar gozo")
            if okf:
                with get_conn() as conn:
                    conn.execute("""INSERT INTO vacations(employee_id,inicio_gozo,fim_gozo,dias,observacao)
                                    VALUES (?,?,?,?,?)""",
                                 (emp_id, ini.isoformat(), fim.isoformat(), dias, obs))
                    conn.commit()
                st.success("Férias lançadas.")

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
                    conn.execute("""INSERT INTO leaves(employee_id,tipo,inicio,fim,observacao)
                                    VALUES (?,?,?,?,?)""",
                                 (emp_id, tipo, ini.isoformat(), fim.isoformat(), obs))
                    conn.commit()
                st.success("Afastamento lançado.")

    st.markdown("#### Registros de férias")
    with get_conn() as conn:
        vf = conn.execute("SELECT * FROM vacations WHERE employee_id=? ORDER BY inicio_gozo DESC", (emp_id,)).fetchall()
    st.dataframe([{k: r[k] for k in r.keys()} for r in vf], use_container_width=True)

    st.markdown("#### Registros de afastamentos")
    with get_conn() as conn:
        af = conn.execute("SELECT * FROM leaves WHERE employee_id=? ORDER BY inicio DESC", (emp_id,)).fetchall()
    st.dataframe([{k: r[k] for k in r.keys()} for r in af], use_container_width=True)

