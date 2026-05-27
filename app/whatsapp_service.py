from flask import current_app
from twilio.rest import Client

from app import db
from app.models.sms_log import SMSLog


class WhatsAppNotConfiguredError(RuntimeError):
    pass


def send_whatsapp_message(member, message_text):
    account_sid = current_app.config.get('TWILIO_ACCOUNT_SID')
    auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
    from_number = current_app.config.get('TWILIO_WHATSAPP_NUMBER')

    if not account_sid or not auth_token or not from_number:
        raise WhatsAppNotConfiguredError('Twilio WhatsApp credentials are not configured.')

    status = 'sent'
    try:
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=message_text,
            from_=from_number,
            to=f'whatsapp:{member.phone_number}',
        )
    except Exception:
        status = 'failed'
        raise
    finally:
        db.session.add(SMSLog(
            sender='System',
            recipient=member.phone_number,
            message=message_text,
            direction='outgoing',
            status=status,
            member_id=member.id,
        ))
