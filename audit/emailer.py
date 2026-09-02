"""
emailer.py — sends a finished audit PDF to a prospect via SMTP.

Configured entirely through environment variables so it works with Gmail
(app password), a transactional provider (Postmark/SendGrid/etc via their
SMTP relay), or any other SMTP host, without a hard dependency on one vendor:

    SMTP_HOST       e.g. smtp.gmail.com
    SMTP_PORT       default 587
    SMTP_USER       the account/login used to authenticate
    SMTP_PASSWORD   an app password (NOT your regular account password)
    SMTP_FROM       optional, defaults to SMTP_USER
    FROM_NAME       optional, defaults to "Between Sundays"

Set these on Render under Settings -> Environment.
"""

import os
import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

EMAIL_RE = re.compile(r"^[^@\s\r\n]+@[^@\s\r\n]+\.[^@\s\r\n]+$")


class EmailConfigError(RuntimeError):
    pass


class InvalidRecipientError(ValueError):
    pass


def _clean_header(value):
    """Strips CR/LF to prevent header injection via a crafted recipient/subject."""
    return value.replace("\r", "").replace("\n", "").strip()


def send_report_email(to_email, subject, body_text, pdf_bytes, filename):
    to_email = _clean_header(to_email)
    if not EMAIL_RE.match(to_email):
        raise InvalidRecipientError(f"{to_email!r} doesn't look like a valid email address.")

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_email = os.environ.get("SMTP_FROM", user)
    from_name = os.environ.get("FROM_NAME", "Between Sundays")

    if not all([host, user, password, from_email]):
        raise EmailConfigError(
            "Email sending isn't configured on this server yet. Set SMTP_HOST, SMTP_USER, "
            "SMTP_PASSWORD (and optionally SMTP_FROM, SMTP_PORT) as environment variables."
        )

    msg = MIMEMultipart()
    msg["From"] = f"{_clean_header(from_name)} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = _clean_header(subject)
    msg.attach(MIMEText(body_text, "plain"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={_clean_header(filename)}")
    msg.attach(part)

    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_email, [to_email], msg.as_string())
