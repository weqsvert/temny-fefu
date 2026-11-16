"""Отправка писем.

Есть SMTP (переменные SMTP_HOST и др.) — отправляем по-настоящему.
Нет SMTP — письмо остаётся в таблице outbox; в режиме разработки её видно на /dev/outbox.
"""
import smtplib
import time
from email.message import EmailMessage

from flask import current_app

from .db import get_db


def send_email(to_addr: str, subject: str, body: str):
    cfg = current_app.config
    if cfg["DEV_OUTBOX"] or not cfg["SMTP_HOST"]:
        get_db().execute(
            "INSERT INTO outbox(to_addr, subject, body, created_at) VALUES (?,?,?,?)",
            (to_addr, subject, body, time.time()),
        )
    if not cfg["SMTP_HOST"]:
        current_app.logger.info("mail (outbox) to=%s subject=%s", to_addr, subject)
        return
    msg = EmailMessage()
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=10) as smtp:
            if cfg["SMTP_TLS"]:
                smtp.starttls()
            if cfg["SMTP_USER"]:
                smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            smtp.send_message(msg)
    except Exception:  # письмо не должно ронять запрос
        current_app.logger.exception("Не удалось отправить письмо на %s", to_addr)
