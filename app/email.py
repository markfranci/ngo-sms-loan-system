from email.message import EmailMessage
from email.utils import formataddr
import smtplib

from flask import current_app


class EmailNotConfiguredError(RuntimeError):
    pass


def _smtp_config():
    config = current_app.config
    required = {
        'SMTP_HOST': config.get('SMTP_HOST'),
        'SMTP_FROM_EMAIL': config.get('SMTP_FROM_EMAIL'),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise EmailNotConfiguredError(f'Missing SMTP settings: {", ".join(missing)}')
    return config


def send_email(to_email, subject, body):
    config = _smtp_config()
    from_email = config.get('SMTP_FROM_EMAIL')
    from_name = config.get('SMTP_FROM_NAME') or 'ENAF Platform'

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = formataddr((from_name, from_email))
    message['To'] = to_email
    message.set_content(body)

    host = config.get('SMTP_HOST')
    port = config.get('SMTP_PORT')
    username = config.get('SMTP_USERNAME')
    password = config.get('SMTP_PASSWORD')
    use_ssl = config.get('SMTP_USE_SSL')
    use_tls = config.get('SMTP_USE_TLS')

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(host, port, timeout=20) as smtp:
        if use_tls and not use_ssl:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


def send_user_invitation_email(user, invitation_url):
    subject = 'Your ENAF Platform Invitation'
    body = f"""Hello {user.username},

You have been invited to access the ENAF SMS Survey Management System.

Please use the link below to set your password and activate your account:
{invitation_url}

You will sign in with this email address:
{user.email}

If you were not expecting this invitation, please ignore this email.
"""
    send_email(user.email, subject, body)
