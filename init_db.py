# init_db.py
from db_core import init_schema_and_seed
from security import ensure_admin_seed

if __name__ == "__main__":
    init_schema_and_seed()
    ensure_admin_seed()
    print("Banco inicializado. Usuário padrão: admin@admin / admin")
