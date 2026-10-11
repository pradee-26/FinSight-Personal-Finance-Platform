from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __tablename__ = "users"
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # Security question for forgot password password reset
    security_question = db.Column(db.String(256), nullable=False)
    security_answer = db.Column(db.String(256), nullable=False)
    
    # Profile information
    profile_pic = db.Column(db.String(256), nullable=True, default="default_avatar.png")
    monthly_income = db.Column(db.Float, nullable=False, default=0.0)
    
    # Visual preference ('light' or 'dark')
    theme_mode = db.Column(db.String(10), nullable=False, default="light")
    
    # Currency preference (e.g. '$', '₹', '£')
    currency = db.Column(db.String(10), nullable=False, default="$")
    
    # Streaks
    savings_streak = db.Column(db.Integer, nullable=False, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    expenses = db.relationship("Expense", backref="user", lazy=True, cascade="all, delete-orphan")
    budgets = db.relationship("Budget", backref="user", lazy=True, cascade="all, delete-orphan")
    investments = db.relationship("Investment", backref="user", lazy=True, cascade="all, delete-orphan")
    goals = db.relationship("Goal", backref="user", lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship("Notification", backref="user", lazy=True, cascade="all, delete-orphan")

class Expense(db.Model):
    __tablename__ = "expenses"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(256), nullable=True)
    type = db.Column(db.String(10), nullable=False, default="expense") # 'expense' or 'income'
    receipt_filename = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Budget(db.Model):
    __tablename__ = "budgets"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    amount_limit = db.Column(db.Float, nullable=False)
    period = db.Column(db.String(20), nullable=False, default="monthly") # 'monthly' or 'weekly'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Investment(db.Model):
    __tablename__ = "investments"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    buy_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float, nullable=False)
    asset_type = db.Column(db.String(50), nullable=False) # 'stock', 'crypto', 'etf', 'bond', 'other'
    purchase_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Goal(db.Model):
    __tablename__ = "goals"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    target_amount = db.Column(db.Float, nullable=False)
    current_amount = db.Column(db.Float, nullable=False, default=0.0)
    deadline = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(100), nullable=False) # 'Savings', 'Education', 'Travel', 'Retirement', 'Property', 'Other'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def remaining_amount(self):
        return max(0.0, self.target_amount - self.current_amount)

    @property
    def pct(self):
        if self.target_amount <= 0:
            return 0
        return int(min(100.0, (self.current_amount / self.target_amount) * 100))

    @property
    def days_remaining(self):
        from datetime import date
        return (self.deadline - date.today()).days

    @property
    def status(self):
        if self.pct >= 100:
            return "Completed"
        elif self.days_remaining < 0:
            return "Overdue"
        else:
            return "In Progress"

class Notification(db.Model):
    __tablename__ = "notifications"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False, default="info") # 'info', 'warning', 'recommendation', 'success'
    message = db.Column(db.String(512), nullable=False)
    read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
