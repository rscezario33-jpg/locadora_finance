# init_db.py
"""
Inicializa e MIGRA o banco (SQLite local ou Postgres/Supabase).
- Cria/atualiza o schema base (db_core.init_schema_and_seed)
- Aplica migrações (novas colunas/tabelas)
- Garante usuário admin seed (security.ensure_admin_seed)

Execute localmente:
    python init_db.py
No Streamlit Cloud, basta rodar uma vez (ou manter como util).
"""

from db_core import init_schema_and_seed, get_conn, USE_PG
from security import ensure_admin_seed


# ---------- helpers de introspecção ----------
def column_exists(conn, table: str, col: str) -> bool:
    """Verifica se coluna existe (compatível SQLite/Postgres)."""
    if USE_PG:
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name=?",
            (table, col),
        ).fetchone()
        return bool(row)
    else:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == col for r in rows)


def table_exists(conn, table: str) -> bool:
    """Verifica se tabela existe (compatível SQLite/Postgres)."""
    if USE_PG:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name=?", (table,)
        ).fetchone()
        return bool(row)
    else:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return bool(row)


# ---------- MIGRAÇÕES ----------
def migrate():
    """
    Aplica migrações idempotentes:
      - companies: responsável, endereço completo, CNAEs
      - users: tokens de reset/convite + permissions (escopo CRUD por página/empresa)
      - clients: endereço completo
      - cnae: catálogo opcional para descrição por código
    """
    with get_conn() as conn:
        # --- 01: EMPRESAS (responsável + endereço + CNAE)
        company_new_cols = [
            ("resp_cpf", "TEXT"),
            ("resp_nome", "TEXT"),
            ("resp_telefone", "TEXT"),
            ("resp_email", "TEXT"),
            ("cep", "TEXT"),
            ("logradouro", "TEXT"),
            ("complemento", "TEXT"),
            ("numero", "TEXT"),
            ("bairro", "TEXT"),
            ("cidade", "TEXT"),
            ("estado", "TEXT"),
            ("cnae_principal", "TEXT"),
            ("cnae_secundarios", "TEXT"),  # lista de códigos separados por vírgula
        ]
        for col, typ in company_new_cols:
            if not column_exists(conn, "companies", col):
                conn.execute(f"ALTER TABLE companies ADD COLUMN {col} {typ}")

        # --- 00: USUÁRIOS (tokens + permissões)
        if not table_exists(conn, "password_reset_tokens"):
            if USE_PG:
                conn.execute(
                    """
                    CREATE TABLE password_reset_tokens (
                      id SERIAL PRIMARY KEY,
                      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                      token TEXT NOT NULL UNIQUE,
                      expires_at TEXT NOT NULL,
                      used BOOLEAN DEFAULT FALSE
                    )
                    """
                )
            else:
                conn.execute(
                    """
                    CREATE TABLE password_reset_tokens (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      token TEXT NOT NULL UNIQUE,
                      expires_at TEXT NOT NULL,
                      used INTEGER DEFAULT 0,
                      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    )
                    """
                )

        if not table_exists(conn, "permissions"):
            if USE_PG:
                conn.execute(
                    """
                    CREATE TABLE permissions (
                      id SERIAL PRIMARY KEY,
                      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                      company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                      page_key TEXT NOT NULL,
                      can_view BOOLEAN DEFAULT TRUE,
                      can_create BOOLEAN DEFAULT FALSE,
                      can_edit BOOLEAN DEFAULT FALSE,
                      can_delete BOOLEAN DEFAULT FALSE,
                      UNIQUE(user_id, company_id, page_key)
                    )
                    """
                )
            else:
                conn.execute(
                    """
                    CREATE TABLE permissions (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      company_id INTEGER NOT NULL,
                      page_key TEXT NOT NULL,
                      can_view INTEGER DEFAULT 1,
                      can_create INTEGER DEFAULT 0,
                      can_edit INTEGER DEFAULT 0,
                      can_delete INTEGER DEFAULT 0,
                      UNIQUE(user_id, company_id, page_key),
                      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                      FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE
                    )
                    """
                )

        # --- 02: CLIENTES (endereço completo)
        client_new_cols = [
            ("cep", "TEXT"),
            ("logradouro", "TEXT"),
            ("complemento", "TEXT"),
            ("numero", "TEXT"),
            ("bairro", "TEXT"),
            ("cidade", "TEXT"),
            ("estado", "TEXT"),
        ]
        for col, typ in client_new_cols:
            if not column_exists(conn, "clients", col):
                conn.execute(f"ALTER TABLE clients ADD COLUMN {col} {typ}")

        # --- CNAE (tabela catálogo opcional)
        if not table_exists(conn, "cnae"):
            conn.execute(
                """
                CREATE TABLE cnae (
                  code TEXT PRIMARY KEY,
                  descricao TEXT NOT NULL
                )
                """
            )

        # tudo OK
        try:
            conn.commit()
        except Exception:
            pass


def init_all():
    """Roda init + migração + seed de admin."""
    init_schema_and_seed()  # schema base (já cria tax_rules, etc.)
    migrate()               # aplica mudanças desta versão
    ensure_admin_seed()     # garante admin@admin / admin


if __name__ == "__main__":
    init_all()
    print("Banco inicializado/migrado. Usuário padrão: admin@admin / admin")
