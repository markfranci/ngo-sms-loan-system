from app import create_app, db
from sqlalchemy import inspect, text

app = create_app()

with app.app_context():
    db.create_all()

    inspector = inspect(db.engine)
    if 'users' in inspector.get_table_names():
        existing_columns = {
            column['name']
            for column in inspector.get_columns('users')
        }
        user_column_migrations = {
            'invitation_token': 'ALTER TABLE users ADD COLUMN invitation_token VARCHAR(128) UNIQUE NULL',
            'invitation_sent_at': 'ALTER TABLE users ADD COLUMN invitation_sent_at DATETIME NULL',
            'invitation_accepted_at': 'ALTER TABLE users ADD COLUMN invitation_accepted_at DATETIME NULL',
        }
        for column_name, statement in user_column_migrations.items():
            if column_name not in existing_columns:
                db.session.execute(text(statement))
        db.session.commit()

    if 'loans' in inspector.get_table_names():
        db.session.execute(text(
            "UPDATE loans SET status = 'submitted' WHERE status = 'pending'"
        ))
        db.session.commit()

    from app.loan_assessment_surveys import ensure_default_loan_assessment_templates

    ensure_default_loan_assessment_templates()
    print("Database tables created successfully!")
