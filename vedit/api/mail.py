"""Trimiterea emailurilor (resetare de parolă) prin SMTP: merge cu Resend, Brevo, Gmail, Mailgun sau serverul tău.

Env:
  VEDIT_SMTP_HOST      ex. smtp.resend.com (fără el, emailurile nu se trimit și resetarea e dezactivată)
  VEDIT_SMTP_PORT      implicit 587 (STARTTLS); 465 = TLS direct
  VEDIT_SMTP_USER      ex. resend
  VEDIT_SMTP_PASSWORD  parola / cheia API
  VEDIT_MAIL_FROM      ex. "vedit <noreply@domeniultau.ro>"
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def enabled() -> bool:
    return bool(os.environ.get("VEDIT_SMTP_HOST"))


def send(to: str, subject: str, text: str) -> None:
    host = os.environ["VEDIT_SMTP_HOST"]
    port = int(os.environ.get("VEDIT_SMTP_PORT", "587"))
    msg = EmailMessage()
    msg["From"] = os.environ.get("VEDIT_MAIL_FROM", "vedit <noreply@localhost>")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    ctx = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=20)
    else:
        server = smtplib.SMTP(host, port, timeout=20)
        server.ehlo()
        if server.has_extn("starttls"):
            server.starttls(context=ctx)
            server.ehlo()
        elif host not in ("localhost", "127.0.0.1"):  # parola SMTP și linkul nu pleacă necriptate pe internet
            server.quit()
            raise RuntimeError(f"serverul SMTP {host} nu oferă STARTTLS; folosește portul 465 sau alt furnizor")
    try:
        user = os.environ.get("VEDIT_SMTP_USER")
        if user:
            server.login(user, os.environ.get("VEDIT_SMTP_PASSWORD", ""))
        server.send_message(msg)
    finally:
        server.quit()
