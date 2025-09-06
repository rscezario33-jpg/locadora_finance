# db_core.py
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path("locadora_finance.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  nome TEXT NOT NULL,
  doc TEXT,
  email TEXT,
  phone TEXT,
  address TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  matricula TEXT,
  nome TEXT NOT NULL,
  funcao TEXT,
  salario NUMERIC DEFAULT 0,
  diaria NUMERIC DEFAULT 0, -- valor da diária, independente de salário
  data_admissao TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vacations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  inicio_gozo TEXT NOT NULL,
  fim_gozo TEXT NOT NULL,
  dias INTEGER NOT NULL,
  observacao TEXT
);

CREATE TABLE IF NOT EXISTS leaves (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL, -- afastamento
  inicio TEXT NOT NULL,
  fim TEXT NOT NULL,
  observacao TEXT
);

CREATE TABLE IF NOT EXISTS equipment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  codigo TEXT,
  descricao TEXT NOT NULL,
  tipo TEXT, -- veículo, máquina, etc.
  placa TEXT,
  chassi TEXT,
  doc_vencimento TEXT, -- validade do documento
  manut_km INTEGER,
  manut_data TEXT,
  observacao TEXT,
  ativo INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equipment_docs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
  nome TEXT NOT NULL,
  dt_validade TEXT
);

CREATE TABLE IF NOT EXISTS equipment_maintenance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
  tipo TEXT, -- preventiva, corretiva
  data TEXT,
  km INTEGER,
  descricao TEXT,
  custo NUMERIC DEFAULT 0
);

CREATE TABLE IF NOT EXISTS services (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  client_id INTEGER REFERENCES clients(id),
  data TEXT NOT NULL,
  descricao TEXT,
  valor_total NUMERIC NOT NULL,
  forma_pagamento TEXT,
  parcelas INTEGER DEFAULT 1,
  fiscal INTEGER DEFAULT 1, -- 1=fiscal, 0=gerencial
  status TEXT DEFAULT 'aberta', -- aberta, em_execucao, concluida, cancelada
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS service_equipments (
  service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
  equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
  PRIMARY KEY (service_id, equipment_id)
);

CREATE TABLE IF NOT EXISTS service_employees (
  service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
  employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  PRIMARY KEY (service_id, employee_id)
);

-- Despesas (pagar)
CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  fornecedor TEXT,
  descricao TEXT,
  forma_pagamento TEXT,
  data_lancamento TEXT NOT NULL,
  valor_total NUMERIC NOT NULL,
  parcelas INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS expense_installments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
  num_parcela INTEGER NOT NULL,
  due_date TEXT NOT NULL,
  amount NUMERIC NOT NULL,
  paid INTEGER DEFAULT 0,
  paid_date TEXT
);

-- Receitas (receber)
CREATE TABLE IF NOT EXISTS revenues (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,
  client_id INTEGER REFERENCES clients(id),
  descricao TEXT,
  forma_pagamento TEXT,
  data_lancamento TEXT NOT NULL,
  valor_total NUMERIC NOT NULL,
  parcelas INTEGER DEFAULT 1,
  fiscal INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS revenue_installments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  revenue_id INTEGER NOT NULL REFERENCES revenues(id) ON DELETE CASCADE,
  num_parcela INTEGER NOT NULL,
  due_date TEXT NOT NULL,
  amount NUMERIC NOT NULL,
  received INTEGER DEFAULT 0,
  received_date TEXT
);

-- Regras tributárias (parametrizável)
CREATE TABLE IF NOT EXISTS tax_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  regime TEXT NOT NULL, -- simples, lucro_real, lucro_presumido
  min_revenue NUMERIC NOT NULL,
  max_revenue NUMERIC, -- null = infinito
  rate NUMERIC NOT NULL -- percentual (ex: 6.0 = 6%)
);
"""

def init_schema_and_seed():
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        # seed simples para tax_rules (exemplos genéricos, ajuste depois)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS n FROM tax_rules")
        if c.fetchone()["n"] == 0:
            seed_rules = [
                ("simples", 0, 180000, 6.0),
                ("simples", 180000, 360000, 8.5),
                ("simples", 360000, 720000, 10.7),
                ("lucro_presumido", 0, None, 13.33),  # ex: IRPJ+CSLL+PIS/Cofins aprox
                ("lucro_real", 0, None, 9.65),       # ex: PIS/Cofins não cumulativos (ex.), ajuste
            ]
            for regime, mi, ma, rate in seed_rules:
                conn.execute(
                    "INSERT INTO tax_rules(regime, min_revenue, max_revenue, rate) VALUES (?,?,?,?)",
                    (regime, mi, ma, rate),
                )
        conn.commit()

def now_iso():
    return datetime.now().isoformat(timespec="seconds")
