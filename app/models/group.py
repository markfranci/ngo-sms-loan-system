from app import db
from datetime import datetime


class Group(db.Model):
    """
    Represents an SME group (e.g. 'Kilifi Women's Group').
    Members belong to groups. Staff are assigned to manage groups.
    """
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)

    # Name of the group — must be unique, cannot be blank
    name = db.Column(db.String(100), unique=True, nullable=False)

    # A short description of the group (optional)
    description = db.Column(db.String(255), nullable=True)

    # Which user (admin or staff) created this group
    # db.ForeignKey links this column to the 'id' column in the 'users' table
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------

    # One group has many members
    # 'back_populates' lets us go both ways:
    #   group.members    → gives all members in this group
    #   member.group     → gives the group a member belongs to
    members = db.relationship('Member', back_populates='group')

    # The user who created this group
    creator = db.relationship('User', foreign_keys=[created_by])

    def __repr__(self):
        return f'<Group {self.name}>'
