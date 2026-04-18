from flask import Blueprint, request, jsonify, Response
from app import db
from app.models.sms_log import SMSLog

# We create a new Blueprint named 'whatsapp'. This tells Flask to group these routes together.
whatsapp = Blueprint('whatsapp', __name__, url_prefix='/whatsapp')

# This route listens for POST requests at '/whatsapp/incoming'.
# A POST request is how external servers (like Twilio) send data securely to your app.
@whatsapp.route('/incoming', methods=['POST'])
def incoming_message():
    # Twilio sends data as an HTML form (like when you submit a website form).
    # 'From' contains the sender's WhatsApp number (e.g., 'whatsapp:+123456789')
    sender_id = request.form.get('From')
    
    # 'Body' contains the actual text message the user typed.
    message_body = request.form.get('Body')
    
    if not sender_id or not message_body:
        # If it's missing data, return an error code (400 Bad Request)
        return jsonify({'error': 'Missing data'}), 400

    # Create a new record in our database using the SMSLog model we reviewed earlier.
    new_message = SMSLog(
        sender=sender_id,
        recipient='System', # For now, we just mark it as sent to the system
        message=message_body,
        direction='incoming', # It came into our app
        status='received'
    )
    
    # Save it to MariaDB!
    db.session.add(new_message)
    db.session.commit()
    
    # Generate an automated reply using Twilio's XML format (TwiML)
    # Twilio reads this string and automatically texts the user back.
    reply_text = f"We have received your message: '{message_body}'. An admin will review it soon."
    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Message>{reply_text}</Message>
    </Response>
    """
    
    # We must return the response wrapped as XML so Twilio knows how to read it
    return Response(twiml_response, mimetype='text/xml')
