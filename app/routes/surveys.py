import re

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.decorators import admin_required
from app.models.survey import SurveySkipRule, SurveyTemplate, SurveyQuestion, SurveyResponse
from app.models.member import Member
from app.models.group import Group
from app.models.sms_log import SMSLog

# Create a new Blueprint for surveys
surveys = Blueprint('surveys', __name__, url_prefix='/surveys')


def _split_options_text(options):
    if not options:
        return []

    parts = re.split(r'\n+|,\s*|\t+|\s+(?=\d+[\.\)])', str(options))
    cleaned_options = []
    for part in parts:
        option = re.sub(r'^\s*\d+[\.\)]\s*', '', part.strip())
        if option:
            cleaned_options.append(option)
    return cleaned_options


def _build_options_text(option_values):
    options = [value.strip() for value in option_values if value and value.strip()]
    return '\n'.join(
        f'{index}. {option}'
        for index, option in enumerate(options, start=1)
    )


@surveys.route('/')
@login_required
def index():
    from app.loan_assessment_surveys import ensure_default_loan_assessment_templates

    ensure_default_loan_assessment_templates()

    # Fetch all survey templates from the database, newest first
    all_templates = SurveyTemplate.query.order_by(SurveyTemplate.created_at.desc()).all()
    # Send them to the index page to be displayed in a table
    return render_template('surveys/index.html', templates=all_templates)

@surveys.route('/new', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        # Grab the text the user typed into the form
        title = request.form.get('title')
        description = request.form.get('description')
        
        # Validation: Ensure they didn't leave the title blank
        if not title:
            flash('Survey title is required.', 'danger')
            return redirect(url_for('surveys.create'))
            
        # Build a new SurveyTemplate object using the model we reviewed
        new_template = SurveyTemplate(
            title=title,
            description=description,
            created_by=current_user.id
        )
        
        # Save securely to MariaDB
        db.session.add(new_template)
        db.session.commit()
        
        flash('Survey template created successfully!', 'success')
        # Send them back to the list of surveys
        return redirect(url_for('surveys.index'))
        
    # If it's a GET request, just display the empty form
    return render_template('surveys/create_template.html')

@surveys.route('/<int:survey_id>', methods=['GET', 'POST'])
@login_required
def view_survey(survey_id):
    # 1. Fetch the exact survey by its ID. If typed wrong, return 404 Error.
    survey = SurveyTemplate.query.get_or_404(survey_id)
    groups = Group.query.all()
    
    if request.method == 'POST':
        # 2. Grab what you typed into the "Add Question" form
        question_text = request.form.get('question_text')
        question_type = request.form.get('question_type')
        option_values = request.form.getlist('option_text[]')
        options = _build_options_text(option_values) if question_type == 'multiple_choice' else None
        
        skip_conditions = request.form.getlist('skip_condition[]')
        skip_to_orders = request.form.getlist('skip_to_order[]')
        
        if not question_text:
            flash('Question text cannot be empty.', 'danger')
            return redirect(url_for('surveys.view_survey', survey_id=survey.id))

        if question_type not in ['text', 'number', 'multiple_choice']:
            flash('Invalid answer format selected.', 'danger')
            return redirect(url_for('surveys.view_survey', survey_id=survey.id))

        if question_type == 'multiple_choice' and not options:
            flash('Add at least one multiple choice option.', 'danger')
            return redirect(url_for('surveys.view_survey', survey_id=survey.id))
            
        # 3. Automatically set the order (if there are 3 questions, this new one is #4)
        next_order = len(survey.questions) + 1
        
        new_question = SurveyQuestion(
            template_id=survey.id,
            question_text=question_text,
            question_type=question_type,
            options=options,
            order_number=next_order
        )
        
        db.session.add(new_question)
        db.session.flush() # Get question ID
        
        from app.models.survey import SurveySkipRule
        for i in range(len(skip_conditions)):
            cond = skip_conditions[i].strip()
            order_raw = skip_to_orders[i].strip() if i < len(skip_to_orders) else ''
            
            if cond and order_raw.isdigit():
                rule = SurveySkipRule(
                    question_id=new_question.id,
                    condition=cond,
                    skip_to_order=int(order_raw)
                )
                db.session.add(rule)
        
        # 4. Save the new question permanently to MariaDB
        db.session.commit()
        
        flash('Question added to survey!', 'success')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))
        
    # 5. Display the dashboard for this specific survey
    question_options = {
        question.id: _split_options_text(question.options)
        for question in survey.questions
    }
    return render_template(
        'surveys/view_template.html',
        survey=survey,
        groups=groups,
        question_options=question_options,
    )

@surveys.route('/<int:survey_id>/dispatch', methods=['POST'])
@login_required
def dispatch_survey(survey_id):
    survey = SurveyTemplate.query.get_or_404(survey_id)
    group_id = request.form.get('group_id')
    
    if not group_id:
        flash('Please select a group.', 'danger')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))
        
    group = Group.query.get_or_404(int(group_id))
    
    if not survey.questions:
        flash('Cannot dispatch an empty survey. Please add questions first.', 'danger')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))

    # Build the message with the first question
    first_question = survey.questions[0]
    message_text = f"Starting {survey.title}:\n\n1. {first_question.question_text}"
    if first_question.question_type == 'multiple_choice' and first_question.options:
        formatted_options = '\n'.join(
            f'{index}. {option}'
            for index, option in enumerate(_split_options_text(first_question.options), start=1)
        )
        message_text += f"\n\n{formatted_options}"

    # Initialize the Twilio client for sending WhatsApp messages
    from twilio.rest import Client
    from flask import current_app

    account_sid = current_app.config.get('TWILIO_ACCOUNT_SID')
    auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
    from_number = current_app.config.get('TWILIO_WHATSAPP_NUMBER')

    if not account_sid or not auth_token:
        flash('Twilio credentials are not configured. Please set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env', 'danger')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))

    client = Client(account_sid, auth_token)

    dispatch_count = 0
    fail_count = 0

    for member in group.members:
        # Set the member's brain to remember they are taking this survey
        member.current_survey_id = survey.id
        member.current_question_order = first_question.order_number

        # Actually send the WhatsApp message via Twilio
        try:
            twilio_message = client.messages.create(
                body=message_text,
                from_=from_number,
                to=f'whatsapp:{member.phone_number}'
            )
            sms_status = 'sent'
            dispatch_count += 1
        except Exception as e:
            sms_status = 'failed'
            fail_count += 1
            print(f"[Twilio Error] Failed to send to {member.phone_number}: {e}")

        # Log the outgoing message
        new_sms = SMSLog(
            sender='System',
            recipient=member.phone_number,
            message=message_text,
            direction='outgoing',
            status=sms_status,
            member_id=member.id
        )
        db.session.add(new_sms)
        
    db.session.commit()

    if fail_count > 0:
        flash(f'Survey dispatched to {dispatch_count} members, {fail_count} failed. Check logs for details.', 'warning')
    else:
        flash(f'Survey successfully dispatched to {dispatch_count} members in {group.name}!', 'success')
    return redirect(url_for('surveys.view_survey', survey_id=survey.id))

@surveys.route('/<int:survey_id>/responses')
@login_required
def view_responses(survey_id):
    survey = SurveyTemplate.query.get_or_404(survey_id)
    questions = survey.questions
    
    # Get all responses for these questions
    responses = SurveyResponse.query.join(SurveyQuestion).filter(SurveyQuestion.template_id == survey_id).all()
    
    # Group responses by member
    # member_data = { member_id: { 'member': Member_obj, 'answers': { question_id: answer } } }
    member_data = {}
    for response in responses:
        if response.member_id not in member_data:
            member_data[response.member_id] = {
                'member': Member.query.get(response.member_id),
                'answers': {}
            }
        member_data[response.member_id]['answers'][response.question.id] = response.answer
        
    return render_template('surveys/responses.html', survey=survey, questions=questions, member_data=member_data)


@surveys.route('/<int:survey_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_template(survey_id):
    survey = SurveyTemplate.query.get_or_404(survey_id)

    Member.query.filter_by(current_survey_id=survey.id).update(
        {
            'current_survey_id': None,
            'current_question_order': None,
        },
        synchronize_session=False,
    )

    for question in list(survey.questions):
        SurveyResponse.query.filter_by(question_id=question.id).delete(synchronize_session=False)
        SurveySkipRule.query.filter_by(question_id=question.id).delete(synchronize_session=False)
        db.session.delete(question)

    db.session.flush()
    db.session.delete(survey)
    db.session.commit()

    flash('Survey template deleted successfully.', 'success')
    return redirect(url_for('surveys.index'))


@surveys.route('/<int:survey_id>/questions/<int:question_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_question(survey_id, question_id):
    survey = SurveyTemplate.query.get_or_404(survey_id)
    question = SurveyQuestion.query.filter_by(id=question_id, template_id=survey.id).first_or_404()

    question_text = request.form.get('question_text', '').strip()
    question_type = request.form.get('question_type', 'text')
    option_values = request.form.getlist('option_text[]')
    options = _build_options_text(option_values) if question_type == 'multiple_choice' else None
    skip_conditions = request.form.getlist('skip_condition[]')
    skip_to_orders = request.form.getlist('skip_to_order[]')

    if not question_text:
        flash('Question text cannot be empty.', 'danger')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))

    if question_type not in ['text', 'number', 'multiple_choice']:
        flash('Invalid answer format selected.', 'danger')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))

    if question_type == 'multiple_choice' and not options:
        flash('Add at least one multiple choice option.', 'danger')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))

    question.question_text = question_text
    question.question_type = question_type
    question.options = options
    question.skip_condition = None
    question.skip_to_order = None

    SurveySkipRule.query.filter_by(question_id=question.id).delete()
    for index, condition in enumerate(skip_conditions):
        condition = condition.strip()
        order_raw = skip_to_orders[index].strip() if index < len(skip_to_orders) else ''
        if condition and order_raw.isdigit():
            db.session.add(SurveySkipRule(
                question_id=question.id,
                condition=condition,
                skip_to_order=int(order_raw),
            ))

    db.session.commit()
    flash('Question updated successfully.', 'success')
    return redirect(url_for('surveys.view_survey', survey_id=survey.id))


@surveys.route('/<int:survey_id>/questions/<int:question_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_question(survey_id, question_id):
    survey = SurveyTemplate.query.get_or_404(survey_id)
    question = SurveyQuestion.query.filter_by(id=question_id, template_id=survey.id).first_or_404()

    SurveyResponse.query.filter_by(question_id=question.id).delete()
    SurveySkipRule.query.filter_by(question_id=question.id).delete()
    db.session.delete(question)
    db.session.flush()

    remaining_questions = SurveyQuestion.query.filter_by(template_id=survey.id).order_by(SurveyQuestion.order_number).all()
    for index, remaining_question in enumerate(remaining_questions, start=1):
        remaining_question.order_number = index

    Member.query.filter_by(current_survey_id=survey.id).update(
        {'current_question_order': None}
    )
    db.session.commit()

    flash('Question removed from survey successfully.', 'success')
    return redirect(url_for('surveys.view_survey', survey_id=survey.id))
