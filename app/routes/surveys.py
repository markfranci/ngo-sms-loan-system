from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models.survey import SurveyTemplate, SurveyQuestion, SurveyResponse
from app.models.member import Member

# Create a new Blueprint for surveys
surveys = Blueprint('surveys', __name__, url_prefix='/surveys')

@surveys.route('/')
@login_required
def index():
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
    
    if request.method == 'POST':
        # 2. Grab what you typed into the "Add Question" form
        question_text = request.form.get('question_text')
        question_type = request.form.get('question_type')
        options = request.form.get('options') # Only used if they picked Multiple Choice
        
        if not question_text:
            flash('Question text cannot be empty.', 'danger')
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
        
        # 4. Save the new question permanently to MariaDB
        db.session.add(new_question)
        db.session.commit()
        
        flash('Question added to survey!', 'success')
        return redirect(url_for('surveys.view_survey', survey_id=survey.id))
        
    # 5. Display the dashboard for this specific survey
    return render_template('surveys/view_template.html', survey=survey)

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
