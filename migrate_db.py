from app import create_app, db

app = create_app()

with app.app_context():
    db.create_all()
    from app.loan_assessment_surveys import ensure_default_loan_assessment_templates

    ensure_default_loan_assessment_templates()
    print("Database tables created successfully!")
