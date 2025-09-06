# security.py
import bcrypt
from db_core import get_conn

def create_user(name: str, email: str, password: str, role: str = "admin", active: bool = True):
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(name,email,password_hash,is_active,role) VALUES (?,?,?,?,?)",
            (name, email, pw_hash, 1 if active else 0, role),
        )
        conn.commit()

def verify_credentials(email: str, password: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=? AND is_active=1", (email,)).fetchone()
        if not row:
            return None
        if bcrypt.checkpw(password.encode(), row["password_hash"]):
            return dict(row)
    return None

def add_user_to_company(user_id: int, company_id: int):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO user_companies(user_id, company_id) VALUES (?,?)",
                     (user_id, company_id))
        conn.commit()

def list_user_companies(user_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT c.* FROM companies c
            JOIN user_companies uc ON uc.company_id=c.id
            WHERE uc.user_id=?
            ORDER BY c.razao_social
        """, (user_id,)).fetchall()

def ensure_admin_seed():
    # cria admin@admin com senha admin se não houver usuários
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) as n FROM users").fetchone()["n"]
        if n == 0:
            create_user("Admin", "admin@admin", "admin", role="admin", active=True)
