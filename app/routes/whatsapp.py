from flask import Blueprint, request, jsonify, Response
from app import db
from app.models.sms_log import SMSLog
from app.models.member import Member, RegistrationSession
from app.models.survey import SurveyTemplate, SurveyQuestion, SurveyResponse

whatsapp = Blueprint('whatsapp', __name__, url_prefix='/whatsapp')

@whatsapp.route('/incoming', methods=['POST'])
def incoming_message():
    sender_id = request.form.get('From', '')
    clean_phone = sender_id.replace('whatsapp:', '')
    message_body = request.form.get('Body', '').strip()
    
    if not sender_id or not message_body:
        return jsonify({'error': 'Missing data'}), 400

    member = Member.query.filter_by(phone_number=clean_phone).first()
    
    new_message = SMSLog(
        sender=clean_phone,
        recipient='System',
        message=message_body,
        direction='incoming',
        status='received',
        member_id=member.id if member else None
    )
    db.session.add(new_message)
    db.session.commit()
    
    # ---------------------------------------------------------
    # CHATBOT MEMORY ENGINE
    # ---------------------------------------------------------
    if not member:
        # Check if they are in the middle of registering
        session = RegistrationSession.query.filter_by(phone_number=clean_phone).first()
        
        if not session:
            if message_body.strip().upper() == 'START':
                # Start registration wizard
                new_session = RegistrationSession(phone_number=clean_phone, step=1)
                db.session.add(new_session)
                db.session.commit()
                reply_text = "Welcome to the NGO SMS Loan System! Let's get you registered.\n\nPlease reply with your Full Name."
            else:
                reply_text = "Welcome! Your phone number is not registered. Please send 'START' to begin registration."
        else:
            if session.step == 1:
                session.full_name = message_body
                session.step = 2
                db.session.commit()
                reply_text = f"Thanks, {message_body}. Now, please reply with your National ID Number."
            elif session.step == 2:
                session.id_number = message_body
                session.step = 3
                db.session.commit()
                reply_text = "Great! Now, please reply with your Gender.\n\nType *Male* or *Female*."
            elif session.step == 3:
                gender_input = message_body.strip().lower()
                if gender_input not in ('male', 'female'):
                    reply_text = "Please reply with either *Male* or *Female*."
                else:
                    session.gender = gender_input
                    
                    # Finalize member creation!
                    new_member = Member(
                        full_name=session.full_name,
                        id_number=session.id_number,
                        phone_number=session.phone_number,
                        gender=session.gender
                    )
                    db.session.add(new_member)
                    
                    # Update the SMS log we just saved so it attaches to the new member
                    new_message.member = new_member
                    
                    # Clean up the temporary session state
                    db.session.delete(session)
                    db.session.commit()
                    
                    reply_text = "Registration complete! 🎉\n\nYou are now an active SME member. You will be notified when surveys or loans are assigned to you."
    else:
        # Check if the member's brain says they are currently taking a survey
        if member.current_survey_id:
            survey = SurveyTemplate.query.get(member.current_survey_id)
            
            # Find the current question by the order_number stored in the member's brain
            current_question = SurveyQuestion.query.filter_by(
                template_id=survey.id,
                order_number=member.current_question_order
            ).first()
            
            if current_question:
                # Save their message as the answer to the current question
                new_response = SurveyResponse(
                    member_id=member.id,
                    question_id=current_question.id,
                    answer=message_body
                )
                db.session.add(new_response)
                
                # ----- SKIP LOGIC ENGINE -----
                # Decide which question comes next based on skip rules
                next_question = None
                
                if current_question.skip_condition and current_question.skip_to_order is not None:
                    # Check if the member's answer matches the skip condition (case-insensitive)
                    if message_body.strip().lower() == current_question.skip_condition.strip().lower():
                        if current_question.skip_to_order == 0:
                            # skip_to_order = 0 means "end survey now"
                            next_question = None
                        else:
                            # Jump to the specified question
                            next_question = SurveyQuestion.query.filter_by(
                                template_id=survey.id,
                                order_number=current_question.skip_to_order
                            ).first()
                    else:
                        # Answer didn't match skip condition — go to next question linearly
                        next_question = SurveyQuestion.query.filter_by(
                            template_id=survey.id,
                            order_number=current_question.order_number + 1
                        ).first()
                else:
                    # No skip rule on this question — go to next question linearly
                    next_question = SurveyQuestion.query.filter_by(
                        template_id=survey.id,
                        order_number=current_question.order_number + 1
                    ).first()
                
                if next_question:
                    # Move to the next question
                    member.current_question_order = next_question.order_number
                    db.session.commit()
                    reply_text = f"Got it. Next question:\n\n{next_question.order_number}. {next_question.question_text}"
                    if next_question.question_type == 'multiple_choice':
                         reply_text += f"\nOptions: {next_question.options}"
                else:
                    # No more questions — survey complete! Clear their memory.
                    member.current_survey_id = None
                    member.current_question_order = None
                    db.session.commit()
                    reply_text = "Thank you! You have completed the survey."
            else:
                # Safety: question not found, reset state
                member.current_survey_id = None
                member.current_question_order = None
                db.session.commit()
                reply_text = "You have already finished this survey."

        # If they aren't taking a survey, check if they are trying to start one
        elif message_body.upper().startswith("START "):
            try:
                survey_id = int(message_body.split(" ")[1])
                survey = SurveyTemplate.query.get(survey_id)
                
                if survey and survey.questions:
                    # Give the member's brain the survey ID and starting question
                    member.current_survey_id = survey.id
                    member.current_question_order = survey.questions[0].order_number
                    db.session.commit()
                    
                    first_question = survey.questions[0]
                    reply_text = f"Starting {survey.title}:\n\n1. {first_question.question_text}"
                    if first_question.question_type == 'multiple_choice':
                         reply_text += f"\nOptions: {first_question.options}"
                else:
                    reply_text = "That survey does not exist or has no questions."
            except:
                reply_text = "Invalid format. Send 'START [ID]' to begin a survey."
        else:
             reply_text = f"Hello {member.full_name}, we received your message! Reply 'START 1' to take an assessment."

    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Message>{reply_text}</Message>
    </Response>
    """
    return Response(twiml_response, mimetype='text/xml')
