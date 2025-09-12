# db_core.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

# -----------------------------------------------------------------------------
# Drivers PG (psycopg3 preferido; fallback psycopg2)
# -----------------------------------------------------------------------------
_pg_mod = None
try:
    import psycopg  # v3
    from psycopg.rows import dict_row as _pg_dict_row
    _pg_mod = ("psycopg3", psycopg)
except Exception:
    try:
        import psycopg2  # v2
        import psycopg2.extras as _pg_extras
        _pg_mod = ("psycopg2", psycopg2)
    except Exception:
        _pg_mod = None


# =============================================================================
# Descoberta do DATABASE_URL (Supabase / Postgres) e flag USE_PG
# =============================================================================
def _get_streamlit_secrets():
    try:
        import streamlit as st
        return getattr(st, "secrets", {})
    except Exception:
        return {}


def _pg_url_from_env_or_secrets() -> str | None:
    # Prioridade: env > st.secrets["DATABASE_URL"] > st.secrets["pg"] dict
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    sec = _get_streamlit_secrets()
    if isinstance(sec, dict):
        if "DATABASE_URL" in sec:
            return str(sec["DATABASE_URL"])
        if "pg" in sec and isinstance(sec["pg"], dict):
            pg = sec["pg"]
            host = pg.get("host")
            port = pg.get("port", 5432)
            db = pg.get("dbname") or pg.get("database")
            user = pg.get("user") or pg.get("username")
            pwd = pg.get("password")
            if all([host, db, user, pwd]):
                return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
    return None


def _ensure_ssl(url: str) -> str:
    # Supabase normalmente exige SSL; se não veio sslmode na URL, adiciona.
    if "supabase.co" in url and "sslmode=" not in url.lower():
        return url + ("&sslmode=require" if "?" in url else "?sslmode=require")
    return url


DATABASE_URL: str | None = _pg_url_from_env_or_secrets()
if DATABASE_URL:
    DATABASE_URL = _ensure_ssl(DATABASE_URL)

USE_PG: bool = bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))

# SQLite local (dev) – caminho padrão
SQLITE_PATH = os.getenv("SQLITE_PATH", "locadora_finance.db")


# =============================================================================
# Adaptador de conexão para expor .execute() com fetchone()/fetchall()
# =============================================================================
class _PgConnAdapter:
    """
    Adapta psycopg3/psycopg2 para uma interface compatível com sqlite3.Connection:
    - .execute(sql, params) -> cursor com .fetchone()/.fetchall()
    - .commit(), .close(), e suporte a 'with get_conn() as conn:'
    Converte placeholders "?" (sqlite) para "%s" (postgres).
    """

    def __init__(self, raw_conn, driver: str):
        self._raw = raw_conn
        self._driver = driver

    def _cursor(self):
        if self._driver == "psycopg3":
            # retorna dict rows
            return self._raw.cursor(row_factory=_pg_dict_row)
        else:  # psycopg2
            return self._raw.cursor(cursor_factory=_pg_extras.RealDictCursor)

    @staticmethod
    def _qmark_to_percent(sql: str) -> str:
        # Conversão simples cobre nossos usos (placeholders posicionais).
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: tuple | list = ()):
        if params is None:
            params = ()
        sql_pg = self._qmark_to_percent(sql)
        cur = self._cursor()
        cur.execute(sql_pg, params)
        return cur

    def executescript(self, *_args, **_kwargs):
        # Não usamos script em PG
        return None

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()

    # context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc:
                try:
                    self._raw.rollback()
                except Exception:
                    pass
            else:
                self._raw.commit()
        finally:
            self.close()


# =============================================================================
# Conexão unificada
# =============================================================================
@contextmanager
def get_conn():
    """
    Retorna uma conexão com interface uniforme para SQLite e Postgres (Supabase).
    - SQLite: sqlite3.Connection com .execute()
    - Postgres: _PgConnAdapter expondo .execute() (placeholders "?" convertidos p/ %s)
    """
    if USE_PG:
        if not _pg_mod:
            raise RuntimeError(
                "Driver Postgres não encontrado. Adicione 'psycopg[binary]>=3.1' "
                "ou 'psycopg2-binary>=2.9' ao requirements.txt."
            )
        driver, mod = _pg_mod
        if driver == "psycopg3":
            conn = mod.connect(DATABASE_URL, autocommit=False)
            try:
                yield _PgConnAdapter(conn, driver="psycopg3")
            finally:
                conn.close()
        else:  # psycopg2
            conn = mod.connect(DATABASE_URL)
            try:
                yield _PgConnAdapter(conn, driver="psycopg2")
            finally:
                conn.close()
    else:
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
        except Exception:
            pass
        try:
            yield conn
        finally:
            conn.close()


# =============================================================================
# Schema / Seed (idempotente)
#  - Em SQLite: cria e ajusta colunas.
#  - Em Postgres/Supabase: tenta criar/alterar (se permissões permitirem). Se não puder, ignora.
# =============================================================================
def init_schema_and_seed():
    """
    Cria o schema mínimo e garante colunas requeridas pelos módulos (Home, Empresas, Clientes).
    """

    def _exec_silent(conn, sql: str, params: tuple = ()):
        try:
            conn.execute(sql, params)
        except Exception:
            # já existe / sem permissão / outro detalhe — segue
            pass

    def _ensure_col(conn, table: str, col: str, decl: str):
        """
        Adiciona coluna se ainda não existir. Funciona em SQLite/PG usando try/except.
        Ex.: _ensure_col(conn, "companies", "resp_cpf", "TEXT")
        """
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        except Exception:
            pass

    with get_conn() as conn:
        # ---------------- users ----------------
        if USE_PG:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS users (
                  id BIGSERIAL PRIMARY KEY,
                  name TEXT NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  password_hash BYTEA NOT NULL,
                  is_active INTEGER DEFAULT 1,
                  role TEXT DEFAULT 'user',
                  created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """,
            )
        else:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  password_hash BLOB NOT NULL,
                  is_active INTEGER DEFAULT 1,
                  role TEXT DEFAULT 'user',
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """,
            )
        _ensure_col(conn, "users", "is_active", "INTEGER DEFAULT 1")
        _ensure_col(conn, "users", "role", "TEXT")
        _ensure_col(conn, "users", "created_at", "TEXT" if not USE_PG else "TIMESTAMPTZ")

        # --------------- companies ---------------
        if USE_PG:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS companies (
                  id BIGSERIAL PRIMARY KEY,
                  cnpj TEXT NOT NULL,
                  razao_social TEXT NOT NULL,
                  nome_fantasia TEXT,
                  endereco TEXT,
                  regime TEXT,
                  created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """,
            )
        else:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS companies (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cnpj TEXT NOT NULL,
                  razao_social TEXT NOT NULL,
                  nome_fantasia TEXT,
                  endereco TEXT,
                  regime TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """,
            )
        # Colunas utilizadas pela página Empresas (01)
        _ensure_col(conn, "companies", "resp_cpf", "TEXT")
        _ensure_col(conn, "companies", "resp_nome", "TEXT")
        _ensure_col(conn, "companies", "resp_telefone", "TEXT")
        _ensure_col(conn, "companies", "resp_email", "TEXT")
        _ensure_col(conn, "companies", "cep", "TEXT")
        _ensure_col(conn, "companies", "logradouro", "TEXT")
        _ensure_col(conn, "companies", "complemento", "TEXT")
        _ensure_col(conn, "companies", "numero", "TEXT")
        _ensure_col(conn, "companies", "bairro", "TEXT")
        _ensure_col(conn, "companies", "cidade", "TEXT")
        _ensure_col(conn, "companies", "estado", "TEXT")
        _ensure_col(conn, "companies", "cnae_principal", "TEXT")
        _ensure_col(conn, "companies", "cnae_secundarios", "TEXT")

        # --------------- clients ---------------
        # (módulo Clientes / página 02)
        if USE_PG:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS clients (
                  id BIGSERIAL PRIMARY KEY,
                  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                  nome TEXT NOT NULL,
                  doc TEXT,
                  email TEXT,
                  phone TEXT,
                  address TEXT,
                  created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """,
            )
        else:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS clients (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                  nome TEXT NOT NULL,
                  doc TEXT,
                  email TEXT,
                  phone TEXT,
                  address TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """,
            )
        # Garante colunas que páginas podem usar
        _ensure_col(conn, "clients", "doc", "TEXT")
        _ensure_col(conn, "clients", "email", "TEXT")
        _ensure_col(conn, "clients", "phone", "TEXT")
        _ensure_col(conn, "clients", "address", "TEXT")
        _ensure_col(conn, "clients", "created_at", "TEXT" if not USE_PG else "TIMESTAMPTZ")
        # Índice por empresa
        _exec_silent(conn, "CREATE INDEX IF NOT EXISTS idx_clients_company_id ON clients(company_id)")

        # --------------- user_companies ---------------
        if USE_PG:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS user_companies (
                  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                  PRIMARY KEY (user_id, company_id)
                )
                """,
            )
        else:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS user_companies (
                  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                  PRIMARY KEY (user_id, company_id)
                )
                """,
            )

        # --------------- password_reset_tokens ---------------
        if USE_PG:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                  id BIGSERIAL PRIMARY KEY,
                  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  token TEXT UNIQUE NOT NULL,
                  expires_at TIMESTAMPTZ NOT NULL,
                  used INTEGER DEFAULT 0
                )
                """,
            )
        else:
            _exec_silent(
                conn,
                """
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  token TEXT UNIQUE NOT NULL,
                  expires_at TEXT NOT NULL,  -- ISO UTC
                  used INTEGER DEFAULT 0
                )
                """,
            )

        # FKs (SQLite) e finaliza
        _exec_silent(conn, "PRAGMA foreign_keys = ON;")
        try:
            conn.commit()
        except Exception:
            pass


# =============================================================================
# Util
# =============================================================================
def now_iso():
    return datetime.now().isoformat(timespec="seconds")
