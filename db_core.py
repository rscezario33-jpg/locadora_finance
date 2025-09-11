# db_core.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime

# Tentamos suportar tanto psycopg (v3) quanto psycopg2
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
            db   = pg.get("dbname") or pg.get("database")
            user = pg.get("user") or pg.get("username")
            pwd  = pg.get("password")
            if all([host, db, user, pwd]):
                return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
    return None

def _ensure_ssl(url: str) -> str:
    # Supabase normalmente exige SSL; se não veio sslmode na URL, adiciona.
    if "supabase.co" in url and "sslmode=" not in url:
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
        # converte placeholders "?" (sqlite) para "%s" (postgres)
        # abordagem simples (funciona bem nos nossos usos)
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: tuple | list = ()):
        if params is None:
            params = ()
        sql_pg = self._qmark_to_percent(sql)
        cur = self._cursor()
        cur.execute(sql_pg, params)
        return cur

    def executescript(self, *_args, **_kwargs):
        # Não suportado/necessário em PG neste projeto; deixamos no-op.
        # Se for preciso no futuro, dividir script em statements e executar uma a uma.
        return None

    def commit(self):
        # psycopg3 usa autocommit False por padrão (bom). Aqui apenas delegamos.
        self._raw.commit()

    def close(self):
        self._raw.close()

    # context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc:
                # se algo falhar, tenta rollback
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
            # Garante SSL se necessário (Supabase)
            import urllib.parse as _urlp
            dsn = DATABASE_URL
            # psycopg2 aceita sslmode na própria URL (já garantimos antes)
            conn = mod.connect(dsn)
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
# Schema/Seed
# - Em SQLite: criamos tudo idempotente (inclusive password_reset_tokens)
# - Em Postgres/Supabase: NÃO criamos nada automaticamente (evita conflito de privilégios).
#   Se quiser bootstrap em PG, crie as tabelas via migrations SQL no Supabase.
# =============================================================================
SCHEMA_SQLITE = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cnpj TEXT NOT NULL,
  razao_social TEXT NOT NULL,
  nome_fantasia TEXT,
  endereco TEXT,
  regime TEXT CHECK(regime IN ('simples','lucro_real','lucro_presumido')) NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  password_hash BLOB NOT NULL,
  is_active INTEGER DEFAULT 1,
  role TEXT CHECK(role IN ('admin','user')) NOT NULL DEFAULT 'user',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_companies (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, company_id)
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token TEXT UNIQUE NOT NULL,
  expires_at TEXT NOT NULL,  -- ISO UTC
  used INTEGER DEFAULT 0
);

/* As demais tabelas dos módulos podem ser criadas pelas páginas específicas
   quando estiver em SQLite. Em PG, prefira migrations no Supabase. */
"""

def init_schema_and_seed():
    if USE_PG:
        # Em Supabase, não tocar no schema automaticamente.
        # Coloque suas migrations no Supabase ou num script separado.
        return

    # SQLite: cria schema mínimo para o app subir
    with get_conn() as conn:
        # Em SQLite, conn é sqlite3.Connection real → tem executescript
        if hasattr(conn, "executescript"):
            conn.executescript(SCHEMA_SQLITE)
        else:
            # safety: divide o script se algum adaptador não suportar executescript
            for stmt in [s.strip() for s in SCHEMA_SQLITE.split(";") if s.strip()]:
                conn.execute(stmt)
        conn.commit()


# =============================================================================
# Util
# =============================================================================
def now_iso():
    return datetime.now().isoformat(timespec="seconds")
