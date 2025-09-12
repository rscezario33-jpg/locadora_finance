# pages/01_📦_Empresas.py
import os, csv, re, requests
from functools import lru_cache

import streamlit as st
from db_core import get_conn
from utils import cnpj_mask
from utils_cep import busca_cep

st.set_page_config(page_title="📦 Empresas", layout="wide")


# ---------- Helpers ----------
def require_login():
    if "user" not in st.session_state or st.session_state.user is None:
        st.stop()


def is_admin() -> bool:
    return bool(st.session_state.user and st.session_state.user.get("role") == "admin")


# ===== CNAE: garantia de tabela + seed opcional + lookup com cache/APIs =====
def ensure_cnae_table():
    """
    Garante a existência da tabela CNAE (SQLite e Postgres/Supabase).
    Schema mínimo: code TEXT PRIMARY KEY, descricao TEXT NOT NULL.
    """
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cnae (
                code TEXT PRIMARY KEY,
                descricao TEXT NOT NULL
            )
            """
        )
        conn.commit()


def seed_cnae_if_empty():
    """
    Se existir assets/cnae.csv (colunas: code,descricao ou codigo,descricao)
    e a tabela estiver vazia, faz o carregamento inicial.
    Não falha a página se o arquivo não existir.
    """
    # caminho relativo ao repo: pages/../assets/cnae.csv
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    csv_path = os.path.join(base_dir, "assets", "cnae.csv")

    try:
        with get_conn() as conn:
            row = conn.execute("SELECT COUNT(1) AS n FROM cnae").fetchone()
            n = row["n"] if isinstance(row, dict) and "n" in row else (row[0] if row else 0)
            if n and int(n) > 0:
                return  # já tem dados
    except Exception:
        # se der erro por ausência, tenta criar e seguir
        try:
            ensure_cnae_table()
        except Exception:
            return

    if not os.path.exists(csv_path):
        return

    rows_to_insert = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                code = (r.get("code") or r.get("codigo") or "").strip()
                desc = (r.get("descricao") or r.get("descrição") or "").strip()
                if code and desc:
                    # normaliza: só números (remove ., - e /)
                    norm = re.sub(r"\D", "", code)
                    rows_to_insert.append((norm, desc))
    except Exception:
        return

    if not rows_to_insert:
        return

    try:
        with get_conn() as conn:
            for code, desc in rows_to_insert:
                try:
                    conn.execute("INSERT INTO cnae(code, descricao) VALUES (?, ?)", (code, desc))
                except Exception:
                    # se já existe, tenta atualizar a descrição
                    try:
                        conn.execute("UPDATE cnae SET descricao=? WHERE code=?", (desc, code))
                    except Exception:
                        pass
            conn.commit()
    except Exception:
        # não derruba a página por causa do seed
        pass


@lru_cache(maxsize=4096)
def _lookup_local_cnae(code_norm: str) -> str | None:
    """
    Consulta local (DB) por descrição do CNAE; retorna None se não achar.
    Tolerante a colunas 'code' ou 'codigo'.
    """
    if not code_norm:
        return None

    ensure_cnae_table()
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT descricao FROM cnae WHERE code=?", (code_norm,)).fetchone()
            if row:
                return row["descricao"] if isinstance(row, dict) and "descricao" in row else (row[0] if row else None)

            # fallback p/ bases antigas que usavam "codigo"
            row2 = conn.execute("SELECT descricao FROM cnae WHERE codigo=?", (code_norm,)).fetchone()
            if row2:
                return row2["descricao"] if isinstance(row2, dict) and "descricao" in row2 else (row2[0] if row2 else None)
    except Exception:
        try:
            ensure_cnae_table()
        except Exception:
            pass
    return None


@st.cache_data(ttl=86400, show_spinner=False)  # 24h
def consulta_cnae_ibge(code_norm: str) -> str | None:
    """
    Consulta a descrição no IBGE (CNAE API) e retorna a descrição.
    - 7+ dígitos: endpoint de SUBCLASSE
    - 4 dígitos: endpoint de CLASSE
    """
    if not code_norm:
        return None

    if len(code_norm) >= 7:
        url = f"https://servicodados.ibge.gov.br/api/v2/cnae/subclasses/{code_norm[:7]}"
    elif len(code_norm) >= 4:
        url = f"https://servicodados.ibge.gov.br/api/v2/cnae/classes/{code_norm[:4]}"
    else:
        return None

    try:
        r = requests.get(url, timeout=6)
        r.raise_for_status()
        data = r.json()
        item = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
        if not item:
            return None
        desc = item.get("descricao") or item.get("titulo") or item.get("descricaoCompleta")
        return desc.strip() if isinstance(desc, str) else None
    except Exception:
        return None


def get_cnae_desc(code: str) -> str | None:
    """
    1) Busca localmente na tabela cnae (cache em memória).
    2) Fallback: IBGE API -> grava local -> retorna.
    """
    code_norm = re.sub(r"\D", "", (code or ""))
    if not code_norm:
        return None

    # 1) tenta local
    desc = _lookup_local_cnae(code_norm)
    if desc:
        return desc

    # 2) tenta IBGE e persiste
    desc = consulta_cnae_ibge(code_norm)
    if desc:
        try:
            with get_conn() as conn:
                try:
                    conn.execute("INSERT INTO cnae(code, descricao) VALUES (?,?)", (code_norm, desc))
                except Exception:
                    try:
                        conn.execute("UPDATE cnae SET descricao=? WHERE code=?", (desc, code_norm))
                    except Exception:
                        pass
                conn.commit()
            # limpa cache para refletir o novo registro (simples e seguro)
            _lookup_local_cnae.cache_clear()
        except Exception:
            pass
    return desc


# Garantias mínimas na carga da página
require_login()
ensure_cnae_table()
seed_cnae_if_empty()

st.title("📦 Empresas")

# ===========================
#   Cadastro de Nova Empresa
# ===========================
with st.expander("➕ Nova empresa", expanded=is_admin()):
    if not is_admin():
        st.info("Somente administradores podem cadastrar empresas.")
    else:
        col1, col2 = st.columns([1, 1])
        with col1:
            cnpj = st.text_input("CNPJ")
            razao = st.text_input("Razão Social")
            fantasia = st.text_input("Nome Fantasia")
            regime = st.selectbox("Regime", ["simples", "lucro_real", "lucro_presumido"], index=0)

        with col2:
            st.markdown("**Responsável pela empresa**")
            resp_cpf = st.text_input("CPF do responsável")
            resp_nome = st.text_input("Nome do responsável")
            resp_telefone = st.text_input("Telefone do responsável")
            resp_email = st.text_input("E-mail do responsável")

        st.markdown("**Endereço**")
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            cep = st.text_input("CEP", key="novo_cep")
            if st.button("↺ Buscar CEP", key="busca_cep_novo", use_container_width=True):
                d = busca_cep(cep)
                if d:
                    st.session_state._addr_novo = d
                else:
                    st.warning("CEP não encontrado.")
        addr = st.session_state.get("_addr_novo", {})
        logradouro = st.text_input("Logradouro", value=addr.get("logradouro", ""))
        complemento = st.text_input("Complemento", value=addr.get("complemento", ""))
        numero = st.text_input("Número")
        bairro = st.text_input("Bairro", value=addr.get("bairro", ""))
        cidade = st.text_input("Cidade", value=addr.get("cidade", ""))
        estado = st.text_input("Estado", value=addr.get("estado", ""))

        st.markdown("**Atividades (CNAE)**")
        cnae_principal = st.text_input("CNAE principal (código, só números)")
        if cnae_principal:
            desc = get_cnae_desc(cnae_principal)
            st.caption(f"Atividade principal: {desc or '— código não encontrado na tabela CNAE'}")
        cnae_secundarios = st.text_input("CNAEs secundários (códigos separados por vírgula)")
        if cnae_secundarios:
            # Mostra descrições conhecidas (quando existirem na tabela)
            sec_list = [x.strip() for x in cnae_secundarios.split(",") if x.strip()]
            if sec_list:
                found = []
                for c in sec_list:
                    dsc = get_cnae_desc(c)
                    if dsc:
                        found.append(f"{c}: {dsc}")
                if found:
                    st.caption("Secundários reconhecidos:\n- " + "\n- ".join(found))

        if st.button("Salvar empresa", type="primary", key="salvar_empresa"):
            if not (cnpj and razao and regime):
                st.warning("Preencha ao menos CNPJ, Razão Social e Regime.")
            else:
                with get_conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO companies (
  cnpj, razao_social, nome_fantasia, endereco, regime,
  resp_cpf, resp_nome, resp_telefone, resp_email,
  cep, logradouro, complemento, numero, bairro, cidade, estado,
  cnae_principal, cnae_secundarios
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            cnpj, razao, fantasia, "", regime,
                            resp_cpf, resp_nome, resp_telefone, resp_email,
                            cep, logradouro, complemento, numero, bairro, cidade, estado,
                            cnae_principal, cnae_secundarios,
                        ),
                    )
                    conn.commit()
                st.success("Empresa cadastrada com sucesso.")
                st.session_state.pop("_addr_novo", None)
                st.rerun()

st.divider()

# ===========================
#     Listagem / Edição
# ===========================
st.subheader("Empresas cadastradas")

# Se não-admin, mostra só as empresas vinculadas ao usuário
with get_conn() as conn:
    if is_admin():
        empresas = conn.execute("SELECT * FROM companies ORDER BY razao_social").fetchall()
    else:
        empresas = conn.execute(
            """
            SELECT c.*
            FROM companies c
            JOIN user_companies uc ON uc.company_id = c.id
            WHERE uc.user_id=?
            ORDER BY c.razao_social
            """,
            (st.session_state.user["id"],),
        ).fetchall()

if not empresas:
    st.info("Nenhuma empresa cadastrada (ou vinculada).")
else:
    for e in empresas:
        header = f"**{e['razao_social']}** — {cnpj_mask(e['cnpj'])} · *{e['regime']}*"
        with st.expander(header, expanded=False):
            col1, col2 = st.columns([1, 1])

            # --- Coluna 1: dados básicos + endereço
            with col1:
                st.markdown("**Dados básicos**")
                st.text_input("CNPJ", e["cnpj"], key=f"cnpj{e['id']}", disabled=not is_admin())
                st.text_input("Razão Social", e["razao_social"], key=f"razao{e['id']}", disabled=not is_admin())
                st.text_input("Nome Fantasia", e.get("nome_fantasia") or "", key=f"fantasia{e['id']}", disabled=not is_admin())
                reg_list = ["simples", "lucro_real", "lucro_presumido"]
                st.selectbox(
                    "Regime",
                    reg_list,
                    index=reg_list.index(e["regime"]),
                    key=f"reg{e['id']}",
                    disabled=not is_admin(),
                )

                st.markdown("**Endereço**")
                st.text_input("CEP", e.get("cep", "") or "", key=f"cep{e['id']}", disabled=not is_admin())
                if is_admin() and st.button("↺ Buscar CEP", key=f"buscacep{e['id']}"):
                    d = busca_cep(st.session_state[f"cep{e['id']}"])
                    if d:
                        st.session_state[f"log{e['id']}"] = d.get("logradouro", "")
                        st.session_state[f"comp{e['id']}"] = d.get("complemento", "")
                        st.session_state[f"bai{e['id']}"] = d.get("bairro", "")
                        st.session_state[f"cid{e['id']}"] = d.get("cidade", "")
                        st.session_state[f"uf{e['id']}"] = d.get("estado", "")
                    else:
                        st.warning("CEP não encontrado.")

                st.text_input("Logradouro", e.get("logradouro", "") or "", key=f"log{e['id']}", disabled=not is_admin())
                st.text_input("Complemento", e.get("complemento", "") or "", key=f"comp{e['id']}", disabled=not is_admin())
                st.text_input("Número", e.get("numero", "") or "", key=f"num{e['id']}", disabled=not is_admin())
                st.text_input("Bairro", e.get("bairro", "") or "", key=f"bai{e['id']}", disabled=not is_admin())
                st.text_input("Cidade", e.get("cidade", "") or "", key=f"cid{e['id']}", disabled=not is_admin())
                st.text_input("Estado", e.get("estado", "") or "", key=f"uf{e['id']}", disabled=not is_admin())

            # --- Coluna 2: responsável + CNAE
            with col2:
                st.markdown("**Responsável**")
                st.text_input("CPF", e.get("resp_cpf", "") or "", key=f"rcpf{e['id']}", disabled=not is_admin())
                st.text_input("Nome", e.get("resp_nome", "") or "", key=f"rnom{e['id']}", disabled=not is_admin())
                st.text_input("Telefone", e.get("resp_telefone", "") or "", key=f"rtel{e['id']}", disabled=not is_admin())
                st.text_input("E-mail", e.get("resp_email", "") or "", key=f"rmail{e['id']}", disabled=not is_admin())

                st.markdown("**CNAE**")
                st.text_input("CNAE principal (código)", e.get("cnae_principal", "") or "", key=f"cnae1{e['id']}", disabled=not is_admin())
                desc1 = get_cnae_desc(st.session_state.get(f"cnae1{e['id']}", e.get("cnae_principal", "")))
                st.caption(f"Atividade principal: {desc1 or '— código não encontrado na tabela CNAE'}")
                st.text_input("CNAEs secundários (códigos separados por vírgula)", e.get("cnae_secundarios", "") or "", key=f"cnae2{e['id']}", disabled=not is_admin())
                secs = [x.strip() for x in st.session_state.get(f"cnae2{e['id']}", e.get("cnae_secundarios", "") or "").split(",") if x.strip()]
                if secs:
                    found = []
                    for c in secs:
                        dsc = get_cnae_desc(c)
                        if dsc:
                            found.append(f"{c}: {dsc}")
                    if found:
                        st.caption("Secundários reconhecidos:\n- " + "\n- ".join(found))

            # --- Ações (Salvar/Excluir) ---
            colS, colD = st.columns([1, 1])
            can_edit = is_admin()
            if can_edit and colS.button("Salvar", key=f"save{e['id']}"):
                with get_conn() as conn:
                    conn.execute(
                        """
                        UPDATE companies SET
                          cnpj=?, razao_social=?, nome_fantasia=?, regime=?,
                          resp_cpf=?, resp_nome=?, resp_telefone=?, resp_email=?,
                          cep=?, logradouro=?, complemento=?, numero=?, bairro=?, cidade=?, estado=?,
                          cnae_principal=?, cnae_secundarios=?
                        WHERE id=?
                        """,
                        (
                            st.session_state[f"cnpj{e['id']}"],
                            st.session_state[f"razao{e['id']}"],
                            st.session_state[f"fantasia{e['id']}"],
                            st.session_state[f"reg{e['id']}"],
                            st.session_state[f"rcpf{e['id']}"],
                            st.session_state[f"rnom{e['id']}"],
                            st.session_state[f"rtel{e['id']}"],
                            st.session_state[f"rmail{e['id']}"],
                            st.session_state[f"cep{e['id']}"],
                            st.session_state[f"log{e['id']}"],
                            st.session_state[f"comp{e['id']}"],
                            st.session_state[f"num{e['id']}"],
                            st.session_state[f"bai{e['id']}"],
                            st.session_state[f"cid{e['id']}"],
                            st.session_state[f"uf{e['id']}"],
                            st.session_state[f"cnae1{e['id']}"],
                            st.session_state[f"cnae2{e['id']}"],
                            e["id"],
                        ),
                    )
                    conn.commit()
                st.success("Empresa atualizada.")

            if can_edit and colD.button("Excluir", key=f"del{e['id']}"):
                with get_conn() as conn:
                    conn.execute("DELETE FROM companies WHERE id=?", (e["id"],))
                    conn.commit()
                st.warning("Empresa excluída.")
                st.rerun()

            # --- Vincular usuários (somente admin) ---
            if is_admin():
                with st.expander("👤 Vincular usuários a esta empresa"):
                    with get_conn() as conn:
                        current_links = conn.execute(
                            """
                            SELECT u.id, u.name, u.email
                            FROM users u
                            JOIN user_companies uc ON uc.user_id = u.id
                            WHERE uc.company_id=?
                            ORDER BY u.name
                            """,
                            (e["id"],),
                        ).fetchall()
                    if current_links:
                        st.caption("Vinculados:")
                        for u in current_links:
                            st.write(f"- {u['name']} <{u['email']}>")
                    email = st.text_input(f"E-mail do usuário para vincular (empresa {e['id']})", key=f"email_{e['id']}")
                    if st.button("Vincular", key=f"v_{e['id']}"):
                        with get_conn() as conn:
                            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                            if u:
                                # Compat: SQLite (INSERT OR IGNORE) e Postgres (ON CONFLICT DO NOTHING)
                                try:
                                    conn.execute(
                                        "INSERT OR IGNORE INTO user_companies(user_id, company_id) VALUES (?,?)",
                                        (u["id"], e["id"]),
                                    )
                                except Exception:
                                    try:
                                        conn.execute(
                                            "INSERT INTO user_companies(user_id, company_id) VALUES (?,?) "
                                            "ON CONFLICT (user_id, company_id) DO NOTHING",
                                            (u["id"], e["id"]),
                                        )
                                    except Exception:
                                        pass
                                conn.commit()
                                st.success("Usuário vinculado.")
                                st.rerun()
                            else:
                                st.error("Usuário não encontrado.")
        st.divider()

