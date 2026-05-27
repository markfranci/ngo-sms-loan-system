from html import escape

from flask import Blueprint, request, jsonify, Response
from app import db
from app.models.sms_log import SMSLog
from app.models.member import Member, RegistrationSession
from app.models.survey import SurveyTemplate, SurveyQuestion, SurveyResponse
import re
from decimal import Decimal, InvalidOperation
from app.validators import is_valid_national_id, is_valid_person_name, title_case_name

whatsapp = Blueprint('whatsapp', __name__, url_prefix='/whatsapp')


def _clean_text_value(value):
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', str(value or ''))
    return re.sub(r'\s+', ' ', value).strip()


def _split_multiple_choice_options(options):
    parts = re.split(r'\n+|,\s*|\t+|\s+(?=(?:\d+|[A-Za-z])[\.\)])', str(options))
    return [_clean_text_value(part) for part in parts if _clean_text_value(part)]


def _option_label(option):
    return re.sub(r'^\s*(?:\d+|[A-Za-z])[\.\)]\s*', '', _clean_text_value(option))


def _format_multiple_choice_options(options):
    return '\n'.join(_split_multiple_choice_options(options))


def _matching_choice_answer(question, raw_answer):
    valid_options = _split_multiple_choice_options(question.options)
    user_input = _clean_text_value(raw_answer)
    user_keys = {
        user_input.casefold(),
        user_input.strip('.):;- ').casefold(),
    }

    for idx, option in enumerate(valid_options):
        label = _option_label(option)
        accepted_values = {
            option.casefold(),
            label.casefold(),
            str(idx + 1),
            chr(ord('a') + idx),
        }

        prefix_match = re.match(r'^\s*((?:\d+|[A-Za-z]))[\.\)]', option)
        if prefix_match:
            accepted_values.add(prefix_match.group(1).casefold())

        if user_keys.intersection(accepted_values):
            return label

    return None


def _normalize_text_answer(raw_answer):
    answer = _clean_text_value(raw_answer)
    if not answer:
        return ''
    return answer.casefold().capitalize()


def _normalize_number_answer(raw_answer):
    answer = _clean_text_value(raw_answer).replace(',', '')
    try:
        number = Decimal(answer)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    if number <= 0:
        return None
    return format(number.normalize(), 'f')


def _normalize_survey_answer(question, raw_answer):
    if question.question_type == 'number':
        answer = _normalize_number_answer(raw_answer)
        if answer is None:
            return None, "Please reply with a valid positive number (e.g., 5000)."
        return answer, ""

    if question.question_type == 'multiple_choice' and question.options:
        answer = _matching_choice_answer(question, raw_answer)
        if answer is None:
            return None, "Please reply with one of the valid options."
        return answer, ""

    answer = _normalize_text_answer(raw_answer)
    if not answer:
        return None, "Please reply with a valid answer."
    if len(answer) > 1000:
        return None, "Your answer is too long. Please keep it under 1000 characters."
    return answer, ""


def _normalize_skip_condition(question, condition):
    if question.question_type == 'multiple_choice' and question.options:
        return _matching_choice_answer(question, condition) or _normalize_text_answer(condition)
    if question.question_type == 'number':
        return _normalize_number_answer(condition) or _clean_text_value(condition)
    return _normalize_text_answer(condition)


def _clean_whatsapp_phone(sender_id):
    phone = sender_id.replace('whatsapp:', '').strip()
    if not re.fullmatch(r'\+?\d{7,15}', phone):
        return None
    return phone

@whatsapp.route('/incoming', methods=['POST'])
def incoming_message():
    sender_id = request.form.get('From', '')
    clean_phone = _clean_whatsapp_phone(sender_id)
    message_body = request.form.get('Body', '').strip()
    
    if not sender_id or not clean_phone or not message_body:
        return jsonify({'error': 'Missing data'}), 400

    if len(message_body) > 1000:
        return jsonify({'error': 'Message too long'}), 400

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
                if not is_valid_person_name(message_body):
                    reply_text = "Please reply with your real full name, using at least two names with letters only."
                else:
                    session.full_name = title_case_name(message_body)
                    session.step = 2
                    db.session.commit()
                    reply_text = f"Thanks, {session.full_name}. Now, please reply with your National ID Number (Numbers only)."
            elif session.step == 2:
                # Validation: ID must be digits and reasonable length
                clean_id = message_body.replace(' ', '').strip()
                existing_member = Member.query.filter_by(id_number=clean_id).first()
                if not is_valid_national_id(clean_id):
                    reply_text = "Please reply with a valid National ID Number (Numbers only, minimum 5 digits)."
                elif existing_member:
                    reply_text = "That National ID Number is already registered. Please contact support for assistance."
                else:
                    session.id_number = clean_id
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
                # ---------------------------------------------------------
                # INPUT VALIDATION ENGINE
                # ---------------------------------------------------------
                normalized_answer, error_msg = _normalize_survey_answer(current_question, message_body)

                if normalized_answer is None:
                    # Validation failed. Repeat the question.
                    reply_text = f"❌ {error_msg}\n\nPlease try again:\n{current_question.order_number}. {current_question.question_text}"
                    if current_question.question_type == 'multiple_choice' and current_question.options:
                         reply_text += f"\n\n{_format_multiple_choice_options(current_question.options)}"
                else:
                    # Input is valid! Save the cleaned, canonical answer.
                    new_response = SurveyResponse(
                        member_id=member.id,
                        question_id=current_question.id,
                        answer=normalized_answer
                    )
                    db.session.add(new_response)
                    
                    # ----- SKIP LOGIC ENGINE -----
                    # Decide which question comes next based on skip rules
                    next_question = None
                    matched_rule = False
                    
                    # Check new multiple skip rules first
                    if current_question.skip_rules:
                        for rule in current_question.skip_rules:
                            if normalized_answer.casefold() == _normalize_skip_condition(current_question, rule.condition).casefold():
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
                        if normalized_answer.casefold() == _normalize_skip_condition(current_question, current_question.skip_condition).casefold():
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
                             reply_text += f"\n\n{_format_multiple_choice_options(next_question.options)}"
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
                         reply_text += f"\n\n{_format_multiple_choice_options(first_question.options)}"
                else:
                    reply_text = "That survey does not exist or has no questions."
            except (IndexError, ValueError):
                reply_text = "Invalid format. Send 'START [ID]' to begin a survey."
        else:
             reply_text = f"Hello {member.full_name}, we received your message! Reply 'START 1' to take an assessment."

    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Message>{escape(reply_text)}</Message>
    </Response>
    """
    return Response(twiml_response, mimetype='text/xml')
