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
                matched_rule = False
                
                # Check new multiple skip rules first
                if current_question.skip_rules:
                    for rule in current_question.skip_rules:
                        if message_body.strip().lower() == rule.condition.strip().lower():
                            matched_rule = True
                            if rule.skip_to_order == 0:
                                next_question = None
                            else:
                                next_question = SurveyQuestion.query.filter_by(
                                    template_id=survey.id,
                                    order_number=rule.skip_to_order
                                ).first()
                            break
                            
                # Fallback to legacy single skip condition if no new rules matched
                if not matched_rule and current_question.skip_condition and current_question.skip_to_order is not None:
                    if message_body.strip().lower() == current_question.skip_condition.strip().lower():
                        matched_rule = True
                        if current_question.skip_to_order == 0:
                            next_question = None
                        else:
                            next_question = SurveyQuestion.query.filter_by(
                                template_id=survey.id,
                                order_number=current_question.skip_to_order
                            ).first()

                if not matched_rule:
                    # No rules matched, or no rules exist — go to next question linearly
                    next_question = SurveyQuestion.query.filter_by(
                        template_id=survey.id,
                        order_number=current_question.order_number + 1
                    ).first()
                
                if next_question:
                    # Move to the next question
                    member.current_question_order = next_question.order_number
                    db.session.commit()
                    reply_text = f"Got it. Next question:\n\n{next_question.order_number}. {next_question.question_text}"
                    if next_question.question_type == 'multiple_choice' and next_question.options:
                         formatted_options = '\n'.join([opt.strip() for opt in str(next_question.options).split(',') if opt.strip()])
                         reply_text += f"\n\n{formatted_options}"
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
                    if first_question.question_type == 'multiple_choice' and first_question.options:
                         formatted_options = '\n'.join([opt.strip() for opt in str(first_question.options).split(',') if opt.strip()])
                         reply_text += f"\n\n{formatted_options}"
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
