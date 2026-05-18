from app import db
from app.models.survey import SurveyQuestion, SurveyTemplate


INVENTORY_ITEM_COUNT = 5
CASH_FLOW_MONTH_COUNT = 6

YES_NO_OPTIONS = "1. Yes\n2. No"


LOAN_ASSESSMENT_TEMPLATE_DEFINITIONS = [
    {
        "title": "Applicant Details",
        "description": "Default loan assessment survey for Applicant Details.",
        "questions": [
            {"text": "Applicant Details: County", "type": "text", "field": "county"},
            {"text": "Applicant Details: Sub-County", "type": "text", "field": "sub_county"},
            {"text": "Applicant Details: Ward", "type": "text", "field": "ward"},
            {"text": "Applicant Details: Male Participants", "type": "number", "field": "male_participants"},
            {"text": "Applicant Details: Female Participants", "type": "number", "field": "female_participants"},
        ],
    },
    {
        "title": "Business Details",
        "description": "Default loan assessment survey for Business Details.",
        "questions": [
            {"text": "Business Details: Business Location", "type": "text", "field": "business_location"},
            {"text": "Business Details: Nature of Business", "type": "text", "field": "nature_of_business"},
            {"text": "Business Details: Registration Number", "type": "text", "field": "registration_number"},
            {
                "text": "Business Details: Completed Required Training",
                "type": "multiple_choice",
                "options": YES_NO_OPTIONS,
                "field": "training_completion",
            },
        ],
    },
    {
        "title": "Balance Sheet",
        "description": "Default loan assessment survey for Balance Sheet.",
        "questions": [
            {"text": "Balance Sheet: Fixed Assets Amount", "type": "number", "field": "fixed_assets"},
            {"text": "Balance Sheet: Current Assets Amount", "type": "number", "field": "current_assets"},
            {"text": "Balance Sheet: Existing Debts or Liabilities Amount", "type": "number", "field": "liabilities"},
        ],
    },
    {
        "title": "Income Statement",
        "description": "Default loan assessment survey for Income Statement.",
        "questions": [
            {"text": "Income Statement: Estimated Monthly Revenue or Sales", "type": "number", "field": "revenue"},
            {"text": "Income Statement: Monthly Business Expenses", "type": "number", "field": "business_expenses"},
            {"text": "Income Statement: Monthly Family or Household Expenses", "type": "number", "field": "family_expenses"},
            {"text": "Income Statement: Monthly Net Profit or Disposable Income", "type": "number", "field": "disposable_income"},
        ],
    },
    {
        "title": "Inventory",
        "description": "Default loan assessment survey for Inventory.",
        "questions": [],
    },
    {
        "title": "Cash Flow",
        "description": "Default loan assessment survey for Cash Flow.",
        "questions": [],
    },
    {
        "title": "Recommendation",
        "description": "Default loan assessment survey for Recommendation.",
        "questions": [
            {"text": "Recommendation: Loan Amount Requested", "type": "number", "field": "amount_requested"},
            {"text": "Recommendation: Loan Term in Months", "type": "number", "field": "loan_term_months"},
            {"text": "Recommendation: Proposed Monthly Instalment", "type": "number", "field": "monthly_instalment"},
            {"text": "Recommendation: Loan Purpose", "type": "text", "field": "loan_purpose"},
            {"text": "Recommendation: Assessment Notes", "type": "text", "field": "notes"},
        ],
    },
]


for item_index in range(1, INVENTORY_ITEM_COUNT + 1):
    LOAN_ASSESSMENT_TEMPLATE_DEFINITIONS[4]["questions"].extend([
        {
            "text": f"Inventory: Item {item_index} Name",
            "type": "text",
            "field": f"inventory_{item_index}_item_name",
        },
        {
            "text": f"Inventory: Item {item_index} Quantity",
            "type": "number",
            "field": f"inventory_{item_index}_quantity",
        },
        {
            "text": f"Inventory: Item {item_index} Unit Price",
            "type": "number",
            "field": f"inventory_{item_index}_unit_price",
        },
    ])


for month_index in range(1, CASH_FLOW_MONTH_COUNT + 1):
    LOAN_ASSESSMENT_TEMPLATE_DEFINITIONS[5]["questions"].extend([
        {
            "text": f"Cash Flow: Month {month_index} Name",
            "type": "text",
            "field": f"cash_flow_{month_index}_month_name",
        },
        {
            "text": f"Cash Flow: Month {month_index} Cash Inflow",
            "type": "number",
            "field": f"cash_flow_{month_index}_cash_inflow",
        },
        {
            "text": f"Cash Flow: Month {month_index} Cash Outflow",
            "type": "number",
            "field": f"cash_flow_{month_index}_cash_outflow",
        },
    ])


LOAN_ASSESSMENT_FIELD_MAP = {
    question["text"].casefold(): question["field"]
    for template in LOAN_ASSESSMENT_TEMPLATE_DEFINITIONS
    for question in template["questions"]
}

NUMERIC_LOAN_ASSESSMENT_FIELDS = {
    question["field"]
    for template in LOAN_ASSESSMENT_TEMPLATE_DEFINITIONS
    for question in template["questions"]
    if question["type"] == "number"
}

CHECKBOX_LOAN_ASSESSMENT_FIELDS = {"training_completion"}


def ensure_default_loan_assessment_templates():
    created_or_updated = False

    for template_definition in LOAN_ASSESSMENT_TEMPLATE_DEFINITIONS:
        template = SurveyTemplate.query.filter_by(title=template_definition["title"]).first()

        if not template:
            template = SurveyTemplate(
                title=template_definition["title"],
                description=template_definition["description"],
            )
            db.session.add(template)
            db.session.flush()
            created_or_updated = True

        existing_questions = {
            question.question_text.casefold()
            for question in template.questions
        }

        next_order = len(template.questions) + 1
        for question_definition in template_definition["questions"]:
            if question_definition["text"].casefold() in existing_questions:
                continue

            db.session.add(SurveyQuestion(
                template_id=template.id,
                question_text=question_definition["text"],
                question_type=question_definition["type"],
                options=question_definition.get("options"),
                order_number=next_order,
            ))
            existing_questions.add(question_definition["text"].casefold())
            next_order += 1
            created_or_updated = True

    if created_or_updated:
        db.session.commit()

    return created_or_updated
