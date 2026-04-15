from app import db
from datetime import datetime


class SurveyTemplate(db.Model):
    """
    Represents a survey created by an Admin or Staff member.
    A survey is a collection of questions that will be sent to members via SMS.
    Example: 'Business Assessment Survey 2026'
    """
    __tablename__ = 'survey_templates'

    id = db.Column(db.Integer, primary_key=True)

    # The name/title of the survey
    title = db.Column(db.String(150), nullable=False)

    # An optional description explaining what this survey is about
    description = db.Column(db.String(255), nullable=True)

    # Which admin or staff member created this survey
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------

    # One survey template has many questions
    questions = db.relationship(
        'SurveyQuestion',
        back_populates='template',
        # 'order_by' makes sure questions always come back
        # in the correct order (question 1, then 2, then 3...)
        order_by='SurveyQuestion.order_number'
    )

    # The user who created this template
    creator = db.relationship('User', foreign_keys=[created_by])

    def __repr__(self):
        return f'<SurveyTemplate "{self.title}">'


# ====================================================================


class SurveyQuestion(db.Model):
    """
    Represents a single question inside a survey template.
    Example: "What is your monthly income?" (question 3 of 10)
    """
    __tablename__ = 'survey_questions'

    id = db.Column(db.Integer, primary_key=True)

    # Which survey template this question belongs to
    template_id = db.Column(
        db.Integer, db.ForeignKey('survey_templates.id'), nullable=False
    )

    # The actual question text that will be sent to the member via SMS
    question_text = db.Column(db.Text, nullable=False)

    # The type of answer expected from the member:
    # 'text'            = any written answer (e.g. business name)
    # 'number'          = a numeric answer (e.g. monthly income)
    # 'multiple_choice' = member picks from given options
    question_type = db.Column(db.String(20), nullable=False, default='text')

    # For multiple_choice questions, we store the options here as plain text
    # Example: "1. Farming 2. Trading 3. Services"
    # The member replies with the number of their choice
    options = db.Column(db.Text, nullable=True)

    # Controls the order in which questions appear in the survey
    # Question 1 is asked first, then 2, then 3, and so on
    order_number = db.Column(db.Integer, nullable=False, default=1)

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------

    # The template this question belongs to
    template = db.relationship('SurveyTemplate', back_populates='questions')

    # All responses members have given to this question
    responses = db.relationship('SurveyResponse', back_populates='question')

    def __repr__(self):
        return f'<SurveyQuestion #{self.order_number}: "{self.question_text[:40]}...">'


# ====================================================================


class SurveyResponse(db.Model):
    """
    Stores the answer a member gives to a specific survey question via SMS.
    Every time a member replies to a survey question, one row is created here.
    """
    __tablename__ = 'survey_responses'

    id = db.Column(db.Integer, primary_key=True)

    # Which member gave this answer
    member_id = db.Column(
        db.Integer, db.ForeignKey('members.id'), nullable=False
    )

    # Which question this answer is for
    question_id = db.Column(
        db.Integer, db.ForeignKey('survey_questions.id'), nullable=False
    )

    # The actual answer the member sent via SMS (stored as text)
    answer = db.Column(db.Text, nullable=False)

    # When the member sent this answer
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------

    # The member who gave this answer
    member = db.relationship('Member', back_populates='survey_responses')

    # The question this answer belongs to
    question = db.relationship('SurveyQuestion', back_populates='responses')

    def __repr__(self):
        return f'<SurveyResponse member={self.member_id} question={self.question_id}>'
