# utils_email.py
import smtplib, ssl, os
from email.message import EmailMessage
import streamlit as st

def base_url():
    # opcional: sobrescrever via secret
    return st.secrets.get("BASE_URL", st.experimental_get_query_params().get("_base", [""])[0] or st.runtime.scriptrunner.script_run_context.get_script_run_ctx().session_data.get("server_address",'')).strip() or ""

def send_email(to, subject, html):
    host = st.secrets.get("SMTP_HOST")
    port = int(st.secrets.get("SMTP_PORT", 587))
    user = st.secrets.get("SMTP_USER")
    pwd  = st.secrets.get("SMTP_PASSWORD")
    from_addr = st.secrets.get("SMTP_FROM", user)

    if not (host and user and pwd):
        st.warning("⚠️ E-mail não configurado (secrets SMTP_* faltando).")
        return False

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("HTML only")
    msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port) as server:
        server.starttls(context=ctx)
        server.login(user, pwd)
        server.send_message(msg)
    return True
