import csv
import io
import re
from datetime import datetime

from flask import Blueprint, make_response, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.decorators import admin_required
from app.models.survey import SurveySkipRule, SurveyTemplate, SurveyQuestion, SurveyResponse
from app.models.member import Member
from app.models.group import Group

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
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        
        # Validation: Ensure they didn't leave the title blank
        if not title:
            flash('Survey title is required.', 'danger')
            return redirect(url_for('surveys.create'))

        if len(title) > 200:
            flash('Survey title must not exceed 200 characters.', 'danger')
            return redirect(url_for('surveys.create'))

        if len(description) > 1000:
            flash('Description must not exceed 1000 characters.', 'danger')
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
        question_text = request.form.get('question_text', '').strip()
        question_type = request.form.get('question_type', '').strip()
        option_values = request.form.getlist('option_text[]')
        options = _build_options_text(option_values) if question_type == 'multiple_choice' else None
        
        skip_conditions = request.form.getlist('skip_condition[]')
        skip_to_orders = request.form.getlist('skip_to_order[]')
        
        if not question_text:
            flash('Question text cannot be empty.', 'danger')
            return redirect(url_for('surveys.view_survey', survey_id=survey.id))

        if len(question_text) > 500:
            flash('Question text must not exceed 500 characters.', 'danger')
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
        
    try:
        group = Group.query.get_or_404(int(group_id))
    except ValueError:
        flash('Please select a valid group.', 'danger')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))
    
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

    from app.whatsapp_service import WhatsAppNotConfiguredError, send_whatsapp_message

    dispatch_count = 0
    fail_count = 0

    for member in group.members:
        # Set the member's brain to remember they are taking this survey
        member.current_survey_id = survey.id
        member.current_question_order = first_question.order_number

        try:
            send_whatsapp_message(member, message_text)
            dispatch_count += 1
        except WhatsAppNotConfiguredError:
            db.session.rollback()
            flash('Twilio credentials are not configured. Please set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env', 'danger')
            return redirect(url_for('surveys.view_survey', survey_id=survey.id))
        except Exception as e:
            fail_count += 1
            print(f"[Twilio Error] Failed to send to {member.phone_number}: {e}")
        
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
    export_format = request.args.get('export')
    filters = {
        'member_name': request.args.get('member_name', '').strip(),
        'phone_number': request.args.get('phone_number', '').strip(),
        'start_date': request.args.get('start_date', '').strip(),
        'end_date': request.args.get('end_date', '').strip(),
        'group_by': request.args.get('group_by', '').strip(),
        'answers': {
            question.id: request.args.get(f'answer_{question.id}', '').strip()
            for question in questions
        },
    }
    
    responses_query = SurveyResponse.query.join(SurveyQuestion).filter(SurveyQuestion.template_id == survey_id)

    start_dt = None
    end_dt = None
    if filters['start_date']:
        try:
            start_dt = datetime.strptime(filters['start_date'], '%Y-%m-%d')
            responses_query = responses_query.filter(SurveyResponse.submitted_at >= start_dt)
        except ValueError:
            filters['start_date'] = ''
    if filters['end_date']:
        try:
            end_dt = datetime.strptime(filters['end_date'], '%Y-%m-%d')
            responses_query = responses_query.filter(
                SurveyResponse.submitted_at <= end_dt.replace(hour=23, minute=59, second=59)
            )
        except ValueError:
            filters['end_date'] = ''

    responses = responses_query.order_by(SurveyResponse.submitted_at.desc()).all()
    
    # Group responses by member
    # member_data = { member_id: { 'member': Member_obj, 'answers': { question_id: answer }, 'submitted_at': latest_response_date } }
    member_data = {}
    for response in responses:
        if response.member_id not in member_data:
            member_data[response.member_id] = {
                'member': Member.query.get(response.member_id),
                'answers': {},
                'submitted_at': response.submitted_at,
            }
        if response.question.id not in member_data[response.member_id]['answers']:
            member_data[response.member_id]['answers'][response.question.id] = response.answer
        if response.submitted_at and (
            not member_data[response.member_id]['submitted_at']
            or response.submitted_at > member_data[response.member_id]['submitted_at']
        ):
            member_data[response.member_id]['submitted_at'] = response.submitted_at

    member_rows = []
    for data in member_data.values():
        member = data['member']
        if not member:
            continue
        if filters['member_name'] and filters['member_name'].casefold() not in member.full_name.casefold():
            continue
        if filters['phone_number'] and filters['phone_number'] not in member.phone_number:
            continue

        answer_matches = True
        for question_id, answer_filter in filters['answers'].items():
            if not answer_filter:
                continue
            answer = str(data['answers'].get(question_id, ''))
            if answer_filter.casefold() not in answer.casefold():
                answer_matches = False
                break
        if not answer_matches:
            continue

        member_rows.append(data)

    member_rows.sort(
        key=lambda item: (
            item['member'].full_name.casefold(),
            item['submitted_at'] or datetime.min,
        )
    )

    grouped_rows = {'All Responses': member_rows}
    if filters['group_by'] == 'member_name':
        grouped_rows = {row['member'].full_name: [row] for row in member_rows}
    elif filters['group_by'] == 'submitted_date':
        grouped_rows = {}
        for row in sorted(member_rows, key=lambda item: item['submitted_at'] or datetime.min, reverse=True):
            key = row['submitted_at'].strftime('%Y-%m-%d') if row['submitted_at'] else 'Unknown Date'
            grouped_rows.setdefault(key, []).append(row)

    if export_format:
        return _export_survey_responses(survey, questions, member_rows, filters, export_format)

    return render_template(
        'surveys/responses.html',
        survey=survey,
        questions=questions,
        member_data={row['member'].id: row for row in member_rows},
        grouped_rows=grouped_rows,
        filters=filters,
    )


def _survey_response_rows(questions, member_rows):
    rows = []
    for data in member_rows:
        submitted_at = data['submitted_at'].strftime('%Y-%m-%d %H:%M') if data['submitted_at'] else ''
        rows.append([
            data['member'].full_name,
            data['member'].phone_number,
            submitted_at,
            *[data['answers'].get(question.id, '') for question in questions],
        ])
    return rows


def _export_survey_responses(survey, questions, member_rows, filters, export_format):
    headers = [
        'Member Name',
        'Phone Number',
        'Submitted At',
        *[f'Q{question.order_number}: {question.question_text}' for question in questions],
    ]
    rows = _survey_response_rows(questions, member_rows)
    filename_base = f"survey_{survey.id}_responses"

    if export_format == 'pdf':
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError:
            return make_response('PDF export requires reportlab to be installed.', 500)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        story = [Paragraph(f'Responses: {survey.title}', styles['Title'])]

        active_filters = []
        if filters.get('member_name'):
            active_filters.append(f"Member: {filters['member_name']}")
        if filters.get('phone_number'):
            active_filters.append(f"Phone: {filters['phone_number']}")
        if filters.get('start_date'):
            active_filters.append(f"From: {filters['start_date']}")
        if filters.get('end_date'):
            active_filters.append(f"To: {filters['end_date']}")
        if active_filters:
            story.append(Paragraph(' | '.join(active_filters), styles['BodyText']))
            story.append(Spacer(1, 8))

        table = Table([[Paragraph(str(cell), styles['BodyText']) for cell in headers]] + rows, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#18181B')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#d4d4d8')),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(table)
        doc.build(story)

        response = make_response(buffer.getvalue())
        response.headers['Content-Disposition'] = f'attachment; filename={filename_base}.pdf'
        response.headers['Content-Type'] = 'application/pdf'
        return response

    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(headers)
    writer.writerows(rows)
    response = make_response(si.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename_base}.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response


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
    question_type = request.form.get('question_type', 'text').strip()
    option_values = request.form.getlist('option_text[]')
    options = _build_options_text(option_values) if question_type == 'multiple_choice' else None
    skip_conditions = request.form.getlist('skip_condition[]')
    skip_to_orders = request.form.getlist('skip_to_order[]')

    if not question_text:
        flash('Question text cannot be empty.', 'danger')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))

    if len(question_text) > 500:
        flash('Question text must not exceed 500 characters.', 'danger')
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
