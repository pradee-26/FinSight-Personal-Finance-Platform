import os
import shutil
from collections import defaultdict
from datetime import datetime, date, timedelta
from flask import Flask, render_template, redirect, url_for, request, flash, send_file, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename

# Import local modules
from config import Config
from models import db, User, Expense, Budget, Investment, Goal, Notification
from utils.analytics import (
    calculate_financial_health,
    calculate_savings_streak,
    get_rule_based_recommendations,
    get_expense_insights,
    get_investment_insights
)
from utils.csv_gen import (
    export_expenses_csv,
    export_budgets_csv,
    export_investments_csv,
    export_goals_csv
)
from utils.excel_gen import (
    export_expenses_excel,
    export_budgets_excel,
    export_investments_excel,
    export_goals_excel
)

# Optional imports with grace fallbacks
try:
    from utils.pdf_gen import generate_financial_pdf
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# Try importing Google GenAI
try:
    from google import genai
    from google.genai import types
    GEMINI_SUPPORT = True
except ImportError:
    GEMINI_SUPPORT = False

# Initialize Flask application
app = Flask(__name__)
app.config.from_object(Config)

# Configure ProxyFix and session cookies for cross-origin iframe security compatibility
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
app.autocorrect_location_header = False

# Configure session cookie settings for cross-origin iframe compatibility
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_HTTPONLY"] = True

# Ensure required storage directories exist
os.makedirs(app.config["RECEIPT_FOLDER"], exist_ok=True)
os.makedirs(app.config["PROFILE_FOLDER"], exist_ok=True)
os.makedirs(app.config["BACKUP_FOLDER"], exist_ok=True)

# Initialize extensions
db.init_app(app)
bcrypt = Bcrypt(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message_category = "info"
login_manager.init_app(app)

# Set up Gemini AI Client
ai_client = None
if GEMINI_SUPPORT and os.environ.get("GEMINI_API_KEY"):
    try:
        ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    except Exception as e:
        print(f"Failed to initialize Gemini Client: {e}")

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

@app.context_processor
def inject_global_vars():
    if current_user and current_user.is_authenticated:
        unread_notifications = [n for n in current_user.notifications if not n.read]
        return {
            "currency_symbol": getattr(current_user, "currency", "$") or "$",
            "unread_notifications": unread_notifications
        }
    return {
        "currency_symbol": "$",
        "unread_notifications": []
    }

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]

def trigger_auto_notifications(user):
    """
    Checks the user's financial profile and automatically populates notifications
    for budget overruns, upcoming goal deadlines, etc.
    """
    try:
        now = datetime.utcnow()
        
        # 1. Check Budgets
        sym = getattr(user, "currency", "$") or "$"
        for b in user.budgets:
            b_cat = (b.category or "").strip().lower()
            spent = sum(e.amount for e in user.expenses if e.type == "expense" and (e.category or "").strip().lower() == b_cat)
            if b.amount_limit and b.amount_limit > 0:
                if spent > b.amount_limit:
                    msg = f"Budget Alert: You have exceeded your limit of {sym}{b.amount_limit:,.2f} for '{b.category}' (Current spent: {sym}{spent:,.2f})."
                    existing = Notification.query.filter_by(user_id=user.id, message=msg).first()
                    if not existing:
                        notif = Notification(user_id=user.id, type="warning", message=msg, read=False)
                        db.session.add(notif)
                elif spent > b.amount_limit * 0.8:
                    msg = f"Budget Watch: Spending on '{b.category}' is at {int((spent/b.amount_limit)*100)}% of your monthly limit ({sym}{spent:,.2f} of {sym}{b.amount_limit:,.2f})."
                    existing = Notification.query.filter_by(user_id=user.id, message=msg).first()
                    if not existing:
                        notif = Notification(user_id=user.id, type="info", message=msg, read=False)
                        db.session.add(notif)
                    
        # 2. Check Goal Deadlines
        for g in user.goals:
            if g.target_amount and g.target_amount > 0 and g.current_amount < g.target_amount:
                if g.deadline:
                    days_left = (g.deadline - date.today()).days
                    if 0 < days_left <= 30:
                        msg = f"Goal Deadline Approaching: Your '{g.name}' goal target date is in {days_left} days. You need {sym}{g.target_amount - g.current_amount:,.2f} more."
                        existing = Notification.query.filter_by(user_id=user.id, message=msg).first()
                        if not existing:
                            notif = Notification(user_id=user.id, type="warning", message=msg, read=False)
                            db.session.add(notif)
                if g.current_amount / g.target_amount >= 0.5:
                    pct = int((g.current_amount / g.target_amount) * 100)
                    if pct in [50, 75, 90, 100]:
                        msg = f"Goal Milestone: Congratulations, you've funded {pct}% of your '{g.name}' goal!"
                        existing = Notification.query.filter_by(user_id=user.id, message=msg).first()
                        if not existing:
                            notif = Notification(user_id=user.id, type="success", message=msg, read=False)
                            db.session.add(notif)
                            
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error in auto notifications: {e}")

def seed_demo_data(user):
    """
    Seeds detailed historical and sample transactions to let the dashboard
    look immediately complete and highly realistic for a first-time user.
    """
    # Create Expenses and Incomes (past 3 months)
    today = date.today()
    
    demo_expenses = [
        # Month 1 Income & Expense
        {"category": "Salary", "amount": 5500.0, "date": today - timedelta(days=60), "type": "income", "desc": "Corporate Monthly Tech Salary"},
        {"category": "Housing", "amount": 1400.0, "date": today - timedelta(days=58), "type": "expense", "desc": "Apartment Rental Payment"},
        {"category": "Groceries", "amount": 220.0, "date": today - timedelta(days=55), "type": "expense", "desc": "Whole Foods Market"},
        {"category": "Dining Out", "amount": 95.0, "date": today - timedelta(days=54), "type": "expense", "desc": "Downtown Sushi Bar"},
        {"category": "Utilities", "amount": 130.0, "date": today - timedelta(days=50), "type": "expense", "desc": "Electricity & Gas"},
        {"category": "Shopping", "amount": 180.0, "date": today - timedelta(days=48), "type": "expense", "desc": "Summer Clothes Purchase"},
        {"category": "Transportation", "amount": 45.0, "date": today - timedelta(days=45), "type": "expense", "desc": "Gas Refueling"},
        {"category": "Entertainment", "amount": 15.0, "date": today - timedelta(days=40), "type": "expense", "desc": "Netflix Subscription"},
        
        # Month 2 Income & Expense
        {"category": "Salary", "amount": 5500.0, "date": today - timedelta(days=30), "type": "income", "desc": "Corporate Monthly Tech Salary"},
        {"category": "Housing", "amount": 1400.0, "date": today - timedelta(days=28), "type": "expense", "desc": "Apartment Rental Payment"},
        {"category": "Groceries", "amount": 250.0, "date": today - timedelta(days=25), "type": "expense", "desc": "Trader Joe's"},
        {"category": "Dining Out", "amount": 110.0, "date": today - timedelta(days=22), "type": "expense", "desc": "Italian Diner"},
        {"category": "Utilities", "amount": 125.0, "date": today - timedelta(days=20), "type": "expense", "desc": "Electricity & Gas"},
        {"category": "Transportation", "amount": 48.0, "date": today - timedelta(days=15), "type": "expense", "desc": "Gas Refueling"},
        {"category": "Entertainment", "amount": 30.0, "date": today - timedelta(days=10), "type": "expense", "desc": "Cinema tickets"},
        {"category": "Shopping", "amount": 90.0, "date": today - timedelta(days=5), "type": "expense", "desc": "Running Shoes"},
        
        # Current Month (recent days)
        {"category": "Salary", "amount": 5500.0, "date": today - timedelta(days=1), "type": "income", "desc": "Corporate Monthly Tech Salary"},
        {"category": "Housing", "amount": 1400.0, "date": today, "type": "expense", "desc": "Apartment Rental Payment"},
        {"category": "Groceries", "amount": 190.0, "date": today - timedelta(days=2), "type": "expense", "desc": "Costco Bulk Groceries"},
        {"category": "Dining Out", "amount": 65.0, "date": today - timedelta(days=3), "type": "expense", "desc": "Ramen Lunch"},
        {"category": "Transportation", "amount": 40.0, "date": today - timedelta(days=4), "type": "expense", "desc": "Gas station"},
    ]
    
    for item in demo_expenses:
        exp = Expense(
            user_id=user.id,
            category=item["category"],
            amount=item["amount"],
            date=item["date"],
            description=item["desc"],
            type=item["type"]
        )
        db.session.add(exp)
        
    # Budgets
    demo_budgets = [
        {"category": "Groceries", "limit": 400.0},
        {"category": "Dining Out", "limit": 250.0},
        {"category": "Transportation", "limit": 150.0},
        {"category": "Shopping", "limit": 300.0}
    ]
    
    for item in demo_budgets:
        bud = Budget(
            user_id=user.id,
            category=item["category"],
            amount_limit=item["limit"],
            period="monthly"
        )
        db.session.add(bud)
        
    # Investments
    demo_investments = [
        {"symbol": "AAPL", "name": "Apple Inc.", "quantity": 10.0, "buy_price": 172.50, "current_price": 195.40, "asset_type": "stock", "p_date": today - timedelta(days=120)},
        {"symbol": "MSFT", "name": "Microsoft Corp.", "quantity": 6.0, "buy_price": 340.20, "current_price": 420.55, "asset_type": "stock", "p_date": today - timedelta(days=90)},
        {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF", "quantity": 25.0, "buy_price": 218.40, "current_price": 262.10, "asset_type": "etf", "p_date": today - timedelta(days=150)},
        {"symbol": "BTC", "name": "Bitcoin", "quantity": 0.05, "buy_price": 43500.00, "current_price": 62800.00, "asset_type": "crypto", "p_date": today - timedelta(days=100)}
    ]
    
    for item in demo_investments:
        inv = Investment(
            user_id=user.id,
            symbol=item["symbol"],
            name=item["name"],
            quantity=item["quantity"],
            buy_price=item["buy_price"],
            current_price=item["current_price"],
            asset_type=item["asset_type"],
            purchase_date=item["p_date"]
        )
        db.session.add(inv)
        
    # Goals
    demo_goals = [
        {"name": "Emergency Fund", "target": 12000.0, "current": 7500.0, "deadline": today + timedelta(days=180), "category": "Savings"},
        {"name": "Europe Summer Trip", "target": 5000.0, "current": 1800.0, "deadline": today + timedelta(days=90), "category": "Travel"},
        {"name": "New Gaming Rig", "target": 2500.0, "current": 2500.0, "deadline": today - timedelta(days=5), "category": "Other"}
    ]
    
    for item in demo_goals:
        goal = Goal(
            user_id=user.id,
            name=item["name"],
            target_amount=item["target"],
            current_amount=item["current"],
            deadline=item["deadline"],
            category=item["category"]
        )
        db.session.add(goal)
        
    # Set default static streak based on 2 positive months
    user.savings_streak = 2
    user.monthly_income = 5500.0
    
    db.session.commit()
    
    # Generate automatic initial notifications
    trigger_auto_notifications(user)


# ==================== CONTROLLER ROUTES ====================

@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

# --- AUTHENTICATION ---

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
        
    if request.method == "POST":
        login_input = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        
        if not login_input or not password:
            flash("Please enter both email/username and password.", "danger")
            return render_template("login.html")
            
        # Support login by email OR username (case-insensitive)
        user = User.query.filter(
            (db.func.lower(User.email) == login_input.lower()) | 
            (db.func.lower(User.username) == login_input.lower())
        ).first()
        
        if user and bcrypt.check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            flash("Welcome back to FinSight Financial Platform!", "success")
            next_page = request.args.get("next")
            if not next_page or not next_page.startswith("/"):
                next_page = url_for("dashboard")
            return redirect(next_page)
        else:
            flash("Invalid email/username or password. Please try again.", "danger")
            
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
        
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        security_question = (request.form.get("security_question") or "").strip()
        security_answer = (request.form.get("security_answer") or "").strip().lower()
        
        try:
            monthly_income = float(request.form.get("monthly_income", 0.0) or 0.0)
        except (ValueError, TypeError):
            monthly_income = 0.0
        
        # 1. Field presence validation
        if not username or not email or not password:
            flash("Username, email, and password are required.", "danger")
            return render_template("register.html")
            
        # 2. Password match check
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")
            
        # 3. Precise duplicate checks (only trigger if matching record actually exists in DB)
        existing_email = User.query.filter(db.func.lower(User.email) == email).first()
        if existing_email:
            flash("An account with this email address already exists. Please log in or use a different email.", "danger")
            return render_template("register.html")
            
        existing_username = User.query.filter(db.func.lower(User.username) == username.lower()).first()
        if existing_username:
            flash("This username is already taken. Please choose a different username.", "danger")
            return render_template("register.html")
            
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        # Profile picture handling
        profile_pic_filename = "default_avatar.png"
        profile_file = request.files.get("profile_pic")
        if profile_file and allowed_file(profile_file.filename):
            filename = secure_filename(profile_file.filename)
            unique_name = f"profile_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            profile_file.save(os.path.join(app.config["PROFILE_FOLDER"], unique_name))
            profile_pic_filename = unique_name
            
        currency = request.form.get("currency", "$")
        if currency == "custom":
            currency = (request.form.get("custom_currency") or "$").strip() or "$"
            
        new_user = User(
            username=username,
            email=email,
            password_hash=hashed_password,
            security_question=security_question,
            security_answer=security_answer,
            monthly_income=monthly_income,
            profile_pic=profile_pic_filename,
            currency=currency
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            
            # Seed demo data for rich dashboard experience
            seed_demo_data(new_user)
            
            # Log in the user and redirect straight to dashboard
            login_user(new_user, remember=True)
            flash("Registration successful! Welcome to your FinSight banking dashboard.", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            db.session.rollback()
            print(f"Error registering user: {e}")
            flash("An error occurred during registration. Please try again.", "danger")
            return render_template("register.html")
        
    return render_template("register.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have successfully signed out of your session.", "info")
    return redirect(url_for("login"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
        
    step = 1
    email = ""
    question = ""
    
    if request.method == "POST":
        action = request.form.get("action")
        email = request.form.get("email")
        
        if action == "find_user":
            user = User.query.filter_by(email=email).first()
            if user:
                question = user.security_question
                step = 2
            else:
                flash("No registered user found with that email address.", "danger")
                
        elif action == "reset_pass":
            user = User.query.filter_by(email=email).first()
            answer = request.form.get("security_answer", "").strip().lower()
            new_password = request.form.get("new_password")
            confirm_password = request.form.get("confirm_password")
            
            if user:
                if user.security_answer.strip().lower() == answer:
                    if new_password == confirm_password:
                        hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
                        user.password_hash = hashed_password
                        db.session.commit()
                        flash("Your password has been reset successfully. Please sign in.", "success")
                        return redirect(url_for("login"))
                    else:
                        flash("Passwords do not match.", "danger")
                        question = user.security_question
                        step = 2
                else:
                    flash("Incorrect answer to your security challenge.", "danger")
                    question = user.security_question
                    step = 2
            else:
                flash("An unexpected error occurred. Please try again.", "danger")
                
    return render_template("forgot_password.html", step=step, email=email, question=question)

# --- THEME MODE TOGGLE ---

@app.route("/theme/toggle", methods=["POST"])
@login_required
def toggle_theme():
    current_user.theme_mode = "dark" if current_user.theme_mode == "light" else "light"
    db.session.commit()
    return jsonify({"success": True, "theme": current_user.theme_mode})

# --- DASHBOARD & NAVIGATION ALIASES ---

@app.route("/income")
@login_required
def income():
    return redirect(url_for("expenses", type="income"))

@app.route("/accounts")
@login_required
def accounts():
    return redirect(url_for("profile"))

@app.route("/reports")
@login_required
def reports():
    return redirect(url_for("analytics"))

@app.route("/settings")
@login_required
def settings():
    return redirect(url_for("profile"))

@app.route("/dashboard")
@login_required
def dashboard():
    # Recalculate Savings Streak dynamically
    current_user.savings_streak = calculate_savings_streak(current_user, current_user.expenses)
    db.session.commit()
    
    # Auto notifications trigger on dashboard load
    trigger_auto_notifications(current_user)
    
    # Compute basic stats
    today = date.today()
    
    # Today's expenses
    today_expenses_val = sum(e.amount for e in current_user.expenses if e.type == "expense" and e.date == today)
    
    # Monthly Income & Expenses
    start_of_month = today.replace(day=1)
    monthly_expenses_val = sum(e.amount for e in current_user.expenses if e.type == "expense" and e.date >= start_of_month)
    monthly_income_val = sum(e.amount for e in current_user.expenses if e.type == "income" and e.date >= start_of_month)
    
    # Savings
    current_savings = monthly_income_val - monthly_expenses_val
    
    # Budget progress
    total_budget_limit = sum(b.amount_limit for b in current_user.budgets)
    total_budget_spent = 0.0
    for b in current_user.budgets:
        b_cat = (b.category or "").strip().lower()
        total_budget_spent += sum(e.amount for e in current_user.expenses if e.type == "expense" and (e.category or "").strip().lower() == b_cat and e.date >= start_of_month)
        
    budget_pct = int((total_budget_spent / total_budget_limit) * 100) if total_budget_limit > 0 else 0
    
    # Portfolio valuations
    portfolio_value = sum(i.quantity * i.current_price for i in current_user.investments)
    
    # Health Score
    health = calculate_financial_health(current_user, current_user.expenses, current_user.budgets, current_user.investments, current_user.goals)
    
    # Recent Transactions
    recent_transactions = sorted(current_user.expenses, key=lambda x: x.date, reverse=True)[:5]
    
    # Unread notifications
    unread_notifications = [n for n in current_user.notifications if not n.read]
    
    return render_template(
        "dashboard.html",
        today_expenses=today_expenses_val,
        current_savings=current_savings,
        monthly_income=monthly_income_val,
        monthly_expenses=monthly_expenses_val,
        budget_pct=budget_pct,
        total_budget_limit=total_budget_limit,
        total_budget_spent=total_budget_spent,
        portfolio_value=portfolio_value,
        health=health,
        recent_transactions=recent_transactions,
        unread_notifications=unread_notifications
    )

# --- EXPENSE TRACKER ---

@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    if request.method == "POST":
        # Check action (add/edit/delete/replace)
        action = request.form.get("action", "add")
        
        if action == "add":
            category = request.form.get("category")
            amount = float(request.form.get("amount") or 0.0)
            date_str = request.form.get("date")
            description = request.form.get("description")
            tx_type = request.form.get("type", "expense") # expense or income
            
            exp_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
            
            # Receipt File
            receipt_filename = None
            receipt_file = request.files.get("receipt")
            if receipt_file and allowed_file(receipt_file.filename):
                filename = secure_filename(receipt_file.filename)
                unique_name = f"receipt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                receipt_file.save(os.path.join(app.config["RECEIPT_FOLDER"], unique_name))
                receipt_filename = unique_name
                
            new_tx = Expense(
                user_id=current_user.id,
                category=category,
                amount=amount,
                date=exp_date,
                description=description,
                type=tx_type,
                receipt_filename=receipt_filename
            )
            db.session.add(new_tx)
            db.session.commit()
            
            # Trigger automatic notifications update
            trigger_auto_notifications(current_user)
            
            flash("Transaction successfully added!", "success")
            
        elif action == "delete":
            tx_id = int(request.form.get("tx_id"))
            tx = Expense.query.get_or_404(tx_id)
            if tx.user_id == current_user.id:
                # Remove receipt file
                if tx.receipt_filename:
                    try:
                        os.remove(os.path.join(app.config["RECEIPT_FOLDER"], tx.receipt_filename))
                    except:
                        pass
                db.session.delete(tx)
                db.session.commit()
                flash("Transaction successfully deleted.", "success")
            else:
                abort(403)
                
        elif action == "replace_receipt":
            tx_id = int(request.form.get("tx_id"))
            tx = Expense.query.get_or_404(tx_id)
            if tx.user_id == current_user.id:
                receipt_file = request.files.get("receipt")
                if receipt_file and allowed_file(receipt_file.filename):
                    # Delete old receipt
                    if tx.receipt_filename:
                        try:
                            os.remove(os.path.join(app.config["RECEIPT_FOLDER"], tx.receipt_filename))
                        except:
                            pass
                    # Save new receipt
                    filename = secure_filename(receipt_file.filename)
                    unique_name = f"receipt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                    receipt_file.save(os.path.join(app.config["RECEIPT_FOLDER"], unique_name))
                    tx.receipt_filename = unique_name
                    db.session.commit()
                    flash("Receipt image successfully updated.", "success")
                else:
                    flash("Invalid file format. Supported formats are JPG, JPEG, PNG under 5MB.", "danger")
            else:
                abort(403)
                
        elif action == "delete_receipt":
            tx_id = int(request.form.get("tx_id"))
            tx = Expense.query.get_or_404(tx_id)
            if tx.user_id == current_user.id:
                if tx.receipt_filename:
                    try:
                        os.remove(os.path.join(app.config["RECEIPT_FOLDER"], tx.receipt_filename))
                    except:
                        pass
                    tx.receipt_filename = None
                    db.session.commit()
                    flash("Receipt image deleted successfully.", "success")
            else:
                abort(403)
                
        return redirect(url_for("expenses"))
        
    # Get parameters for filters and sorting
    search_query = request.args.get("search", "")
    category_filter = request.args.get("category", "")
    type_filter = request.args.get("type", "")
    sort_by = request.args.get("sort", "date_desc")
    
    query = Expense.query.filter_by(user_id=current_user.id)
    
    # Advanced search filters
    if search_query:
        query = query.filter(
            Expense.description.ilike(f"%{search_query}%") |
            Expense.category.ilike(f"%{search_query}%")
        )
    if category_filter:
        query = query.filter(Expense.category == category_filter)
    if type_filter:
        query = query.filter(Expense.type == type_filter)
        
    # Sorting options
    if sort_by == "date_desc":
        query = query.order_by(Expense.date.desc())
    elif sort_by == "date_asc":
        query = query.order_by(Expense.date.asc())
    elif sort_by == "amount_desc":
        query = query.order_by(Expense.amount.desc())
    elif sort_by == "amount_asc":
        query = query.order_by(Expense.amount.asc())
        
    all_expenses = query.all()
    
    # Distinct categories for filter
    distinct_categories = sorted(list(set(e.category for e in current_user.expenses if e.category)))
    
    return render_template(
        "expenses.html",
        expenses=all_expenses,
        categories=distinct_categories,
        search=search_query,
        category_filter=category_filter,
        type_filter=type_filter,
        sort_by=sort_by
    )

# --- BUDGET MANAGEMENT ---

@app.route("/budgets", methods=["GET", "POST"])
@login_required
def budgets():
    if request.method == "POST":
        action = request.form.get("action", "add")
        
        if action == "add":
            category = request.form.get("category")
            amount_limit = float(request.form.get("amount_limit") or 0.0)
            period = request.form.get("period", "monthly")
            
            # Check if budget already exists for this category, update if it does, else add
            existing = Budget.query.filter_by(user_id=current_user.id, category=category).first()
            if existing:
                existing.amount_limit = amount_limit
                existing.period = period
            else:
                new_budget = Budget(
                    user_id=current_user.id,
                    category=category,
                    amount_limit=amount_limit,
                    period=period
                )
                db.session.add(new_budget)
                
            db.session.commit()
            trigger_auto_notifications(current_user)
            flash("Monthly budget successfully set!", "success")
            
        elif action == "delete":
            budget_id = int(request.form.get("budget_id"))
            bud = Budget.query.get_or_404(budget_id)
            if bud.user_id == current_user.id:
                db.session.delete(bud)
                db.session.commit()
                flash("Category budget deleted.", "success")
            else:
                abort(403)
                
        return redirect(url_for("budgets"))
        
    # Process budget statistics
    today = date.today()
    start_of_month = today.replace(day=1)
    
    budget_details = []
    for b in current_user.budgets:
        spent = sum(e.amount for e in current_user.expenses if e.type == "expense" and e.category.lower() == b.category.lower() and e.date >= start_of_month)
        pct = (spent / b.amount_limit) * 100 if b.amount_limit > 0 else 0
        budget_details.append({
            "budget": b,
            "spent": spent,
            "pct": int(min(100, pct)),
            "is_over": spent > b.amount_limit
        })
        
    # Budget recommendations engine (from local analytics rule)
    recs = get_rule_based_recommendations(current_user, current_user.expenses, current_user.budgets, current_user.investments, current_user.goals)
    budget_recs = [r for r in recs if r["category"] in ["Budget", "Food", "Shopping", "Savings"]]
    
    return render_template(
        "budgets.html",
        budget_details=budget_details,
        recommendations=budget_recs
    )

# --- INVESTMENT PORTFOLIO TRACKER ---

@app.route("/investments", methods=["GET", "POST"])
@login_required
def investments():
    if request.method == "POST":
        action = request.form.get("action", "add")
        
        if action == "add":
            symbol = request.form.get("symbol").upper()
            name = request.form.get("name")
            quantity = float(request.form.get("quantity") or 0.0)
            buy_price = float(request.form.get("buy_price") or 0.0)
            current_price = float(request.form.get("current_price", buy_price) or buy_price)
            asset_type = request.form.get("asset_type", "stock")
            purchase_date_str = request.form.get("purchase_date")
            
            p_date = datetime.strptime(purchase_date_str, "%Y-%m-%d").date() if purchase_date_str else date.today()
            
            new_inv = Investment(
                user_id=current_user.id,
                symbol=symbol,
                name=name,
                quantity=quantity,
                buy_price=buy_price,
                current_price=current_price,
                asset_type=asset_type,
                purchase_date=p_date
            )
            db.session.add(new_inv)
            db.session.commit()
            flash("Investment transaction added!", "success")
            
        elif action == "delete":
            inv_id = int(request.form.get("inv_id"))
            inv = Investment.query.get_or_404(inv_id)
            if inv.user_id == current_user.id:
                db.session.delete(inv)
                db.session.commit()
                flash("Holding deleted from portfolio.", "success")
            else:
                abort(403)
                
        elif action == "update_price":
            inv_id = int(request.form.get("inv_id"))
            inv = Investment.query.get_or_404(inv_id)
            if inv.user_id == current_user.id:
                new_price = float(request.form.get("current_price") or 0.0)
                inv.current_price = new_price
                db.session.commit()
                flash(f"Current price for {inv.symbol} updated.", "success")
            else:
                abort(403)
                
        return redirect(url_for("investments"))
        
    # Calculate returns details
    total_invested_val = 0.0
    total_current_val = 0.0
    
    investment_list = []
    for inv in current_user.investments:
        cost = inv.quantity * inv.buy_price
        current = inv.quantity * inv.current_price
        gain_val = current - cost
        gain_pct = (gain_val / cost) * 100 if cost > 0 else 0
        
        total_invested_val += cost
        total_current_val += current
        
        investment_list.append({
            "holding": inv,
            "cost": cost,
            "current_value": current,
            "gain_val": gain_val,
            "gain_pct": gain_pct
        })
        
    portfolio_gain_val = total_current_val - total_invested_val
    portfolio_gain_pct = (portfolio_gain_val / total_invested_val) * 100 if total_invested_val > 0 else 0
    
    # Insights
    insights = get_investment_insights(current_user.investments)
    
    return render_template(
        "investments.html",
        investments=investment_list,
        total_invested=total_invested_val,
        total_current=total_current_val,
        portfolio_gain=portfolio_gain_val,
        portfolio_gain_pct=portfolio_gain_pct,
        insights=insights
    )

# --- FINANCIAL GOALS TRACKER ---

@app.route("/goals", methods=["GET", "POST"])
@login_required
def goals():
    if request.method == "POST":
        action = request.form.get("action", "add")
        
        if action == "add":
            name = request.form.get("name")
            target_amount = float(request.form.get("target_amount") or 0.0)
            current_amount = float(request.form.get("current_amount") or 0.0)
            deadline_str = request.form.get("deadline") or request.form.get("target_date")
            category = request.form.get("category", "Savings")
            
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date() if deadline_str else date.today()
            
            new_goal = Goal(
                user_id=current_user.id,
                name=name,
                target_amount=target_amount,
                current_amount=current_amount,
                deadline=deadline,
                category=category
            )
            db.session.add(new_goal)
            db.session.commit()
            trigger_auto_notifications(current_user)
            flash("Financial target goal created successfully!", "success")
            
        elif action in ("add_contribution", "contribute"):
            goal_id = int(request.form.get("goal_id"))
            contribution = float(request.form.get("contribution") or 0.0)
            goal = Goal.query.get_or_404(goal_id)
            if goal.user_id == current_user.id:
                goal.current_amount += contribution
                db.session.commit()
                trigger_auto_notifications(current_user)
                sym = getattr(current_user, "currency", "$") or "$"
                flash(f"Added contribution of {sym}{contribution:,.2f} towards your '{goal.name}' goal.", "success")
            else:
                abort(403)
                
        elif action == "delete":
            goal_id = int(request.form.get("goal_id"))
            goal = Goal.query.get_or_404(goal_id)
            if goal.user_id == current_user.id:
                db.session.delete(goal)
                db.session.commit()
                flash("Financial goal deleted.", "success")
            else:
                abort(403)
                
        return redirect(url_for("goals"))
        
    total_target = sum(g.target_amount for g in current_user.goals)
    total_saved = sum(g.current_amount for g in current_user.goals)
        
    return render_template("goals.html", goals=current_user.goals, total_target=total_target, total_saved=total_saved)

# --- ANALYTICS ENGINE ---

@app.route("/analytics")
@login_required
def analytics():
    # Filters: Support both timeframe (30, 90, 180, 365 from dropdown) and filter_mode
    timeframe = request.args.get("timeframe")
    today = date.today()
    
    if timeframe:
        if timeframe == "30":
            start_date = today - timedelta(days=30)
            filter_mode = "1M"
        elif timeframe == "90":
            start_date = today - timedelta(days=90)
            filter_mode = "3M"
        elif timeframe == "180":
            start_date = today - timedelta(days=180)
            filter_mode = "6M"
        elif timeframe == "365":
            start_date = today - timedelta(days=365)
            filter_mode = "12M"
        else:
            start_date = today - timedelta(days=180)
            filter_mode = "6M"
            timeframe = "180"
    else:
        timeframe = "180"  # default matching the 180 days dropdown default
        filter_mode = request.args.get("filter", "6M")
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        
        # Calculate starting date based on filters
        if filter_mode == "2M":
            start_date = today - timedelta(days=60)
        elif filter_mode == "3M":
            start_date = today - timedelta(days=90)
        elif filter_mode == "12M":
            start_date = today - timedelta(days=365)
        elif filter_mode == "current_year":
            start_date = date(today.year, 1, 1)
        elif filter_mode == "prev_year":
            start_date = date(today.year - 1, 1, 1)
            # also restrict end_date
            end_date_val = date(today.year - 1, 12, 31)
        elif filter_mode == "custom" and start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            today = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        else: # Default 6M
            start_date = today - timedelta(days=180)
            filter_mode = "6M"
            
    # Get expenses/income within range
    query = Expense.query.filter_by(user_id=current_user.id).filter(Expense.date >= start_date)
    if not timeframe and filter_mode == "prev_year":
        query = query.filter(Expense.date <= end_date_val)
    elif not timeframe and filter_mode == "custom" and end_date_str:
        query = query.filter(Expense.date <= today)
        
    range_expenses = query.all()
    
    # Category Distribution (Chart.js)
    category_totals = defaultdict(float)
    income_vs_expense = {"income": 0.0, "expense": 0.0}
    
    for e in range_expenses:
        if e.type == "expense":
            category_totals[e.category] += e.amount
            income_vs_expense["expense"] += e.amount
        else:
            income_vs_expense["income"] += e.amount
            
    # Sorted categories
    top_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    highest_category = top_categories[0][0] if top_categories else "None"
    lowest_category = top_categories[-1][0] if top_categories and len(top_categories) > 1 else "None"
    
    # Format categories for Chart.js
    chart_cat_labels = [c[0] for c in top_categories[:5]]
    chart_cat_values = [c[1] for c in top_categories[:5]]
    
    # Add an 'Other' bucket if more than 5 categories
    if len(top_categories) > 5:
        other_sum = sum(c[1] for c in top_categories[5:])
        chart_cat_labels.append("Other")
        chart_cat_values.append(other_sum)
        
    # Monthly trend line calculations
    monthly_trend = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for e in range_expenses:
        ym = e.date.strftime("%b %Y")
        if e.type == "income":
            monthly_trend[ym]["income"] += e.amount
        else:
            monthly_trend[ym]["expense"] += e.amount
            
    # Sort months sequentially
    sorted_trend_months = sorted(monthly_trend.keys(), key=lambda x: datetime.strptime(x, "%b %Y"))
    chart_trend_income = [monthly_trend[m]["income"] for m in sorted_trend_months]
    chart_trend_expense = [monthly_trend[m]["expense"] for m in sorted_trend_months]
    
    # Financial Health breakdown
    health = calculate_financial_health(current_user, current_user.expenses, current_user.budgets, current_user.investments, current_user.goals)
    
    # Performance rating
    score = health["score"]
    if score >= 85:
        rating = "Outstanding"
    elif score >= 70:
        rating = "Strong / On Track"
    elif score >= 50:
        rating = "Moderate / Capable"
    else:
        rating = "Needs Action Plan"
        
    # Insights
    expense_insights = get_expense_insights(current_user.expenses)
    
    # Calculate metrics for the analytics template
    total_income = sum(e.amount for e in range_expenses if e.type == "income")
    total_expenses = sum(e.amount for e in range_expenses if e.type == "expense")
    
    savings_rate = 0.0
    if total_income > 0:
        savings_rate = ((total_income - total_expenses) / total_income) * 100
        
    avg_monthly_spent = expense_insights.get("monthly_average", 0.0)
    
    # liquid cash = all-time savings (all income - all expenses)
    all_time_income = sum(e.amount for e in current_user.expenses if e.type == "income")
    all_time_expense = sum(e.amount for e in current_user.expenses if e.type == "expense")
    liquid_cash = max(0.0, all_time_income - all_time_expense)
    
    liquidity_ratio = 0.0
    if avg_monthly_spent > 0:
        liquidity_ratio = liquid_cash / avg_monthly_spent
    else:
        liquidity_ratio = 6.0  # Safe/ideal standard fallback
        
    portfolio_value = sum(i.quantity * i.current_price for i in current_user.investments)
    investment_coefficient = 0.0
    if all_time_income > 0:
        investment_coefficient = (portfolio_value / all_time_income) * 100
        
    top_spending_category = highest_category if highest_category != "None" else "None"
    
    metrics = {
        "savings_rate": savings_rate,
        "liquidity_ratio": liquidity_ratio,
        "investment_coefficient": investment_coefficient,
        "top_spending_category": top_spending_category,
        "avg_monthly_spent": avg_monthly_spent,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "categories_breakdown": category_totals
    }
    
    return render_template(
        "analytics.html",
        filter_mode=filter_mode,
        timeframe=timeframe,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=today.strftime("%Y-%m-%d"),
        highest_category=highest_category,
        lowest_category=lowest_category,
        income_vs_expense=income_vs_expense,
        chart_cat_labels=chart_cat_labels,
        chart_cat_values=chart_cat_values,
        chart_trend_months=sorted_trend_months,
        chart_trend_income=chart_trend_income,
        chart_trend_expense=chart_trend_expense,
        health=health,
        performance_rating=rating,
        expense_insights=expense_insights,
        metrics=metrics
    )

# --- AI FINANCIAL ADVISOR ---

@app.route("/advisor")
@login_required
def advisor_view():
    return render_template("advisor.html")


def generate_fallback_report(user):
    from collections import defaultdict
    expenses = user.expenses
    budgets = user.budgets
    investments = user.investments
    goals = user.goals
    
    currency = getattr(user, "currency", "$") or "$"
    
    # 1. Cash flow stats
    total_income = sum(e.amount for e in expenses if e.type == "income")
    total_expense = sum(e.amount for e in expenses if e.type == "expense")
    net_savings = total_income - total_expense
    savings_rate = (net_savings / total_income * 100) if total_income > 0 else 0.0
    
    # 2. Category totals
    category_spending = defaultdict(float)
    for e in expenses:
        if e.type == "expense":
            category_spending[e.category] += e.amount
            
    highest_cat = "None"
    highest_amount = 0.0
    lowest_cat = "None"
    lowest_amount = float('inf')
    
    for cat, val in category_spending.items():
        if val > highest_amount:
            highest_amount = val
            highest_cat = cat
        if val < lowest_amount:
            lowest_amount = val
            lowest_cat = cat
            
    if lowest_cat == "None" or lowest_amount == float('inf'):
        lowest_cat = "None"
        lowest_amount = 0.0
        
    # 3. Budget performance
    budget_alerts = []
    for b in budgets:
        spent = category_spending.get(b.category, 0.0)
        if spent > b.amount_limit:
            budget_alerts.append(f"Exceeded **{b.category}** budget by **{currency}{spent - b.amount_limit:,.2f}** (Limit: {currency}{b.amount_limit:,.2f}, Spent: {currency}{spent:,.2f})")
            
    # 4. Investment stats
    portfolio_cost = sum(i.quantity * i.buy_price for i in investments)
    portfolio_value = sum(i.quantity * i.current_price for i in investments)
    growth_rate = 0.0
    if portfolio_cost > 0:
        growth_rate = ((portfolio_value - portfolio_cost) / portfolio_cost) * 100
        
    # 5. Goal progress
    goal_details = []
    total_progress = 0.0
    for g in goals:
        progress = (g.current_amount / g.target_amount * 100) if g.target_amount > 0 else 0.0
        goal_details.append(f"**{g.name}** ({progress:.1f}% funded: {currency}{g.current_amount:,.2f} of {currency}{g.target_amount:,.2f})")
        total_progress += progress
    avg_goal_progress = (total_progress / len(goals)) if goals else 0.0
    
    # 6. Overall Rating
    if savings_rate >= 30:
        rating = "Excellent"
        summary_vibe = "outstanding. You are compounding your net worth exceptionally fast and displaying superb budget discipline."
    elif savings_rate >= 15:
        rating = "Strong Growth"
        summary_vibe = "healthy and poised for continuous wealth growth. Your saving habits are highly commendable."
    elif savings_rate >= 0:
        rating = "Balanced"
        summary_vibe = "stable but holds significant optimization opportunities. Tweaking key categories could rapidly double your investment velocities."
    else:
        rating = "Action Required"
        summary_vibe = "experiencing capital contraction. Your outgoing expenses exceed your logged income, which poses liquidity risks."
        
    # Build suggestions dynamically
    suggestions = []
    if budget_alerts:
        suggestions.append(f"Deploy structural limits on **{highest_cat}** spending immediately, as it is your leading outlay at {currency}{highest_amount:,.2f}.")
    else:
        suggestions.append(f"Continue your diligent budgeting structure. Consider allocating an extra 5% of surplus income to high-growth assets.")
        
    if growth_rate > 0:
        suggestions.append(f"Reinvest dividends from your top stock positions to leverage compound interest benefits. Current portfolio growth is a solid **{growth_rate:.1f}%**.")
    else:
        suggestions.append(f"Initiate low-cost index fund dollar-cost averaging to seed your investment footprint.")
        
    if goals:
        suggestions.append(f"Set up automated sub-account routing to fund the remaining balances for **{goals[0].name}** on every payroll cycle.")
    else:
        suggestions.append(f"Map out at least one short-term savings goal (e.g. 3-Month emergency runway) to keep your surplus capital target-focused.")

    report = f"""### Overall Financial Health Summary
Your financial health rating is **{rating}**. Currently, your overall cash flow structure is **{summary_vibe}** With a savings rate of **{savings_rate:.1f}%**, you are steadily steering towards long-term fiscal freedom.

### Monthly Income vs Expenses
• **Logged Inflows**: {currency}{total_income:,.2f}
• **Logged Outlays**: {currency}{total_expense:,.2f}
• **Net Capital Surplus**: {currency}{net_savings:,.2f}

### Current Savings
Your current cash savings represent a positive reserve. Your average monthly outlays indicate that you have seeded a stable foundational buffer.

### Budget Performance
{"<br>".join(budget_alerts) if budget_alerts else "Superb discipline! None of your category budgets have exceeded their defined monthly thresholds. Your proactive capital boundaries are working perfectly."}

### Highest Spending Category
Your highest outlay is concentrated in **{highest_cat}** at **{currency}{highest_amount:,.2f}**. This category remains your primary optimization channel where even minor curtailments could compound your savings rate dramatically.

### Lowest Spending Category
Your lowest outlay is observed in **{lowest_cat}** at **{currency}{lowest_amount:,.2f}**. This demonstrates highly optimized constraints on secondary outlays.

### Investment Performance
Your portfolio value stands at **{currency}{portfolio_value:,.2f}** against a cost basis of **{currency}{portfolio_cost:,.2f}**, reflecting an unrealized return of **{growth_rate:+.1f}%**. Your asset allocation is building durable long-term exposure.

### Goal Progress
You are tracking **{len(goals)} active financial goals**. Average funding progress sits at **{avg_goal_progress:.1f}%**. 
{"<br>".join(goal_details) if goal_details else "No active financial goals configured yet. We recommend establishing a milestone to harness goal-driven savings velocities!"}

### Recent Spending Behaviour
Outlays exhibit moderate transactional frequency. Category-level outlays reveal a highly structured profile, though optimizing top categories will unlock supplementary investment capital.

### Top Financial Risks
1. **{highest_cat if highest_cat != 'None' else 'High Outlays'} Concentration**: Represents a major proportion of outlays, leaving you exposed to lifestyle inflation.
2. **Emergency Runway**: Ensure you have a solid 3-6 months cash runway before scaling aggressive speculative assets.

### Positive Financial Habits
1. **Goal Awareness**: Actively configuring and funding designated goals maintains high motivational focus.
2. **Diligent Expense Logging**: Maintaining real-time logs of transactional entries is the foundation of high-performance personal finance.

### Personalized Suggestions
1. **Optimize Category Caps**: {suggestions[0]}
2. **Scale Portfolio Compounding**: {suggestions[1]}
3. **Automate Goal Funding**: {suggestions[2]}

### Overall Financial Rating
**{rating}**

### Short Monthly Summary
A well-constructed overview showing strong potential. By optimizing discretionary categories and systematically funneling the surplus into your investments and goals, you are securely charting a course to true financial independence.
"""
    questions = [
        f"I noticed your {highest_cat} expenses represent your highest outlay. Would you like tips to optimize this category?",
        f"Your goals are {avg_goal_progress:.1f}% funded on average. Should we build a tactical savings plan to accelerate them?",
        "Your investments reflect positive exposure. Would you like a detailed review of asset compounding options?"
    ]
    return {
        "report": report,
        "proactive_questions": questions,
        "rating": rating
    }


def generate_fallback_chat_reply(user, user_message):
    from collections import defaultdict
    currency = getattr(user, "currency", "$") or "$"
    msg_lower = user_message.lower()
    
    expenses = user.expenses
    total_income = sum(e.amount for e in expenses if e.type == "income")
    total_expense = sum(e.amount for e in expenses if e.type == "expense")
    net_savings = total_income - total_expense
    savings_rate = (net_savings / total_income * 100) if total_income > 0 else 0.0
    
    # Category spending
    category_spending = defaultdict(float)
    for e in expenses:
        if e.type == "expense":
            category_spending[e.category] += e.amount
    highest_cat = "None"
    highest_amount = 0.0
    for cat, val in category_spending.items():
        if val > highest_amount:
            highest_amount = val
            highest_cat = cat

    if "save" in msg_lower or "saving" in msg_lower:
        reply = f"""To increase your savings rate from **{savings_rate:.1f}%** to a high-performance **30%**, we recommend focusing on these three optimization steps:
        
1. **Cap discretionary leaks**: Discretionary outlays are led by **{highest_cat}** at **{currency}{highest_amount:,.2f}**. Cutting this category by just 15% will instantly unlock **{currency}{highest_amount * 0.15:,.2f}** per month.
2. **Automate savings routing**: Set up a split-deposit on your payroll so that 15% of your income is automatically funneled to your goals before you have a chance to spend it.
3. **Audit subscriptions**: Go through your transaction logs and eliminate any recurring subscriptions that you have not utilized in the last 30 days.

Would you like me to help you design a customized monthly budget to make this easy?"""
    elif "expense" in msg_lower or "spend" in msg_lower:
        reply = f"""Here is a detailed breakdown of your top logged outlays:
        
• **Total Expenses Logged**: {currency}{total_expense:,.2f}
• **Primary Spending Driver**: **{highest_cat}** at **{currency}{highest_amount:,.2f}** (representing **{(highest_amount/total_expense*100) if total_expense > 0 else 0:.1f}%** of total outlays).

**Advisor Recommendation**:
To keep your budget optimized, discretionary categories like food or shopping should never exceed 30% of your total net income. Your current primary category is taking up **{(highest_amount/total_income*100) if total_income > 0 else 0:.1f}%** of your total monthly income coefficient. 

Should we run a simulation to see the impact of trimming this category by 20%?"""
    elif "budget" in msg_lower:
        over_budgets = []
        for b in user.budgets:
            spent = category_spending.get(b.category, 0.0)
            if spent > b.amount_limit:
                over_budgets.append(f"• **{b.category}**: Limit {currency}{b.amount_limit:,.2f}, Spent {currency}{spent:,.2f} (Exceeded by **{currency}{spent - b.amount_limit:,.2f}**)")
        
        if over_budgets:
            over_budgets_str = "\n".join(over_budgets)
            reply = f"""I found the following category budget exceedances in your current cycle:
            
{over_budgets_str}

**Tactical Plan**:
1. Temporarily freeze discretionary purchases in these categories for the next 7 days.
2. Re-allocate unused limits from under-budget categories to cover these deficits.
3. We can help you adjust these budget thresholds to better fit your real-world spending velocities.

Would you like to re-align your monthly budget limits?"""
        else:
            reply = f"""Fantastic news! All of your category budgets are fully within their limits. Your current spending discipline is highly optimized:
            
• **Active Budgets Monitored**: {len(user.budgets)} categories.
• **Budget Health**: 100% compliant.

Since you are maintaining strong discretionary boundaries, would you like to explore allocating a portion of your cash surplus into your investment portfolio to accelerate compounding?"""
    elif "investment" in msg_lower or "portfolio" in msg_lower or "stock" in msg_lower:
        portfolio_value = sum(i.quantity * i.current_price for i in user.investments)
        reply = f"""Your current investment portfolio is valued at **{currency}{portfolio_value:,.2f}** across **{len(user.investments)} unique positions**.

**Strategic Recommendations**:
1. **Asset Allocation**: Ensure you maintain broad-based exposure (low-cost ETFs or index funds) to shield your portfolio against individual stock volatility.
2. **Consistency**: Automate recurring small investments rather than trying to time the market (Dollar-Cost Averaging).
3. **Compound Growth**: Reinvest all dividends immediately to let the compound interest effect build wealth over time.

Would you like me to analyze your individual investment positions for potential risk exposure?"""
    elif "goal" in msg_lower:
        goals = user.goals
        if goals:
            goal_lines = []
            for g in goals:
                progress = (g.current_amount / g.target_amount * 100) if g.target_amount > 0 else 0.0
                goal_lines.append(f"• **{g.name}**: {progress:.1f}% funded ({currency}{g.current_amount:,.2f} of {currency}{g.target_amount:,.2f})")
            goal_lines_str = "\n".join(goal_lines)
            reply = f"""Here is the status of your active financial goals:
            
{goal_lines_str}

**Advisor Strategy**:
You are making steady progress! To accelerate your timeline:
1. Try to fund an extra {currency}25-50 per week by cutting down on discretionary leaks.
2. Any unexpected windfalls (bonuses, cash gifts) should be routed directly to your top priority goals.

Would you like a detailed savings schedule to reach your next goal 3 months faster?"""
        else:
            reply = f"""You do not have any active financial goals configured at the moment. 

Establishing specific, target-focused goals is the single most effective way to maintain long-term saving momentum. We recommend starting with a **3-Month Emergency Fund** or a **Major Purchase Goal**.

Would you like to define a new financial goal now?"""
    else:
        reply = f"""As your AI Financial Advisor, I am here to help you optimize your finances and build long-term wealth.

Based on your current portfolio:
• **Logged Savings Rate**: **{savings_rate:.1f}%**
• **Top Expenditure Channel**: **{highest_cat}** ({currency}{highest_amount:,.2f})
• **Investment Capital**: **{currency}{sum(i.quantity * i.current_price for i in user.investments):,.2f}**

You can ask me questions such as:
• *How can I save more money?*
• *Where is my money going?*
• *Tell me about my budget health.*
• *How are my investments performing?*
• *Am I on track to meet my goals?*

What aspect of your personal finances would you like to optimize today?"""

    questions = [
        "How can I save more money?",
        f"What should I do about my {highest_cat if highest_cat != 'None' else 'discretionary'} expenses?",
        "How can I optimize my budgets?"
    ]
    return {
        "reply": reply,
        "proactive_questions": questions
    }


@app.route("/api/advisor/analyze", methods=["GET"])
@login_required
def api_advisor_analyze():
    import json
    
    user = current_user
    currency = getattr(user, "currency", "$") or "$"
    
    # Pre-calculate data summaries for Gemini context
    total_income = sum(e.amount for e in user.expenses if e.type == "income")
    total_expense = sum(e.amount for e in user.expenses if e.type == "expense")
    net_savings = total_income - total_expense
    
    recent_tx = []
    for e in sorted(user.expenses, key=lambda x: x.date, reverse=True)[:15]:
        recent_tx.append(f"- Date: {e.date}, Category: {e.category}, Amount: {currency}{e.amount:,.2f}, Type: {e.type}, Description: {e.description or ''}")
    recent_transactions_str = "\n".join(recent_tx) or "No transactions logged yet."

    active_budgets = []
    for b in user.budgets:
        active_budgets.append(f"- Category: {b.category}, Limit: {currency}{b.amount_limit:,.2f}, Period: {b.period}")
    active_budgets_str = "\n".join(active_budgets) or "No category budgets configured."

    investments_list = []
    for i in user.investments:
        investments_list.append(f"- Symbol: {i.symbol}, Name: {i.name}, Quantity: {i.quantity}, Buy Price: {currency}{i.buy_price:,.2f}, Current Price: {currency}{i.current_price:,.2f}, Asset Type: {i.asset_type}")
    investments_str = "\n".join(investments_list) or "No portfolio investments registered."

    goals_list = []
    for g in user.goals:
        goals_list.append(f"- Name: {g.name}, Target: {currency}{g.target_amount:,.2f}, Current Saved: {currency}{g.current_amount:,.2f}, Deadline: {g.deadline}")
    goals_str = "\n".join(goals_list) or "No savings goals registered."

    if ai_client:
        try:
            prompt = f"""
            You are FinSight AI, a premier personal banking and expert financial advisor. 
            Analyze the following financial data of the user:
            Username: {user.username}
            Monthly Income Coefficient: {currency}{getattr(user, "monthly_income", 0.0):,.2f}
            Recent transactions logged:
            {recent_transactions_str}
            
            Active Category Budgets:
            {active_budgets_str}
            
            Investments Portfolio:
            {investments_str}
            
            Financial Goals:
            {goals_str}
            
            Generate a comprehensive, highly personalized, professional financial advisory report in JSON format.
            The report MUST be written in simple, natural English, like an elite professional financial advisor.
            Never display raw JSON, database values, SQL, or technical calculations in the report text itself.
            Keep the advice elegant, positive, and action-oriented.
            
            The JSON output must have EXACTLY the following keys:
            1. "report": A beautifully styled markdown string containing:
               - "Overall Financial Health Summary": A detailed evaluation of the user's financial standing and saving/investment habits.
               - "Monthly Income vs Expenses": A clear, textual comparison of recent inflows vs outflows.
               - "Current Savings": A conversational description of their cash savings and what it means for them.
               - "Budget Performance": Analysis of which categories are on track and which are exceeded.
               - "Highest Spending Category": Discussion on the top expenditure area and how to optimize it.
               - "Lowest Spending Category": Discussion on the lowest outlay category.
               - "Investment Performance": Insights on their stock/asset allocation and growth.
               - "Goal Progress": Motivation and trajectory analysis for their financial goals.
               - "Recent Spending Behaviour": Narrative regarding their lifestyle outlays and habits.
               - "Top Financial Risks": 1-2 key vulnerabilities (e.g. high food spend, low emergency fund, lacks asset diversity).
               - "Positive Financial Habits": 1-2 bright spots to keep doing.
               - "Personalized Suggestions": 3 highly specific, actionable, numerical tips to save or invest more.
               - "Overall Financial Rating": A rating like "Excellent", "Strong Growth", "Balanced", "Needs Optimization", or "Action Required".
               - "Short Monthly Summary": A 1-2 sentence concluding summary.

            2. "proactive_questions": An array of EXACTLY 3-4 highly intelligent, personalized follow-up questions based on the user's actual data.
               Each question should be a direct, short, highly relevant prompt that the user can click. Examples:
               - "I noticed your shopping expenses increased this month. Would you like to know how you can reduce them?"
               - "Your investments have grown by 12%. Would you like a detailed investment performance report?"
               - "You exceeded your Food budget. Shall I suggest a better monthly budget?"
               - "You are close to reaching your Car Savings Goal. Would you like a savings plan to achieve it faster?"
               - "I found three spending categories where you can save more money. Would you like to see them?"
               - "You have enough surplus income to start investing. Would you like investment suggestions?"
            
            3. "rating": A rating like "Excellent", "Strong Growth", "Balanced", "Needs Optimization", or "Action Required".

            Return ONLY a valid JSON object matching this structure. Do not wrap the JSON in markdown code blocks like ```json ... ```. Just return raw JSON.
            """
            
            response = ai_client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            # Clean response text just in case Gemini added markdown code blocks
            resp_text = response.text.strip()
            if resp_text.startswith("```"):
                lines = resp_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                resp_text = "\n".join(lines).strip()
                
            result = json.loads(resp_text)
            return jsonify({
                "success": True,
                "report": result.get("report", ""),
                "proactive_questions": result.get("proactive_questions", []),
                "rating": result.get("rating", "Balanced")
            })
            
        except Exception as e:
            print(f"Gemini AI advisor report generation failed: {e}")
            
    # Fallback response
    fallback_data = generate_fallback_report(user)
    return jsonify({
        "success": True,
        "report": fallback_data["report"],
        "proactive_questions": fallback_data["proactive_questions"],
        "rating": fallback_data["rating"]
    })


@app.route("/api/advisor/chat", methods=["POST"])
@login_required
def api_advisor_chat():
    import json
    
    req_data = request.json or {}
    user_message = req_data.get("message", "").strip()
    history = req_data.get("history", [])
    
    user = current_user
    currency = getattr(user, "currency", "$") or "$"
    
    # Summary of user data
    total_income = sum(e.amount for e in user.expenses if e.type == "income")
    total_expense = sum(e.amount for e in user.expenses if e.type == "expense")
    net_savings = total_income - total_expense
    
    recent_tx = []
    for e in sorted(user.expenses, key=lambda x: x.date, reverse=True)[:15]:
        recent_tx.append(f"- Date: {e.date}, Category: {e.category}, Amount: {currency}{e.amount:,.2f}, Type: {e.type}, Description: {e.description or ''}")
    recent_transactions_str = "\n".join(recent_tx) or "No transactions logged yet."

    active_budgets = []
    for b in user.budgets:
        active_budgets.append(f"- Category: {b.category}, Limit: {currency}{b.amount_limit:,.2f}, Period: {b.period}")
    active_budgets_str = "\n".join(active_budgets) or "No category budgets configured."

    investments_list = []
    for i in user.investments:
        investments_list.append(f"- Symbol: {i.symbol}, Name: {i.name}, Quantity: {i.quantity}, Buy Price: {currency}{i.buy_price:,.2f}, Current Price: {currency}{i.current_price:,.2f}, Asset Type: {i.asset_type}")
    investments_str = "\n".join(investments_list) or "No portfolio investments registered."

    goals_list = []
    for g in user.goals:
        goals_list.append(f"- Name: {g.name}, Target: {currency}{g.target_amount:,.2f}, Current Saved: {currency}{g.current_amount:,.2f}, Deadline: {g.deadline}")
    goals_str = "\n".join(goals_list) or "No savings goals registered."

    # Format history as context for the API
    formatted_history = ""
    for msg in history[-10:]:  # Keep last 10 messages for context window stability
        role = "User" if msg.get("role") == "user" else "Assistant"
        formatted_history += f"{role}: {msg.get('content')}\n\n"

    if ai_client:
        try:
            prompt = f"""
            You are FinSight AI, a premier personal banking and expert financial advisor. 
            Respond to the user's message in simple, natural, and warm English, behaving like an elite professional financial advisor.
            Never display raw JSON, database values, SQL, or technical calculations.
            Structure your response elegantly with markdown format. Highlight stats or key points in bold.
            
            User's Personal Financial Data Context:
            Username: {user.username}
            Monthly Income Coefficient: {currency}{getattr(user, "monthly_income", 0.0):,.2f}
            Recent transactions logged:
            {recent_transactions_str}
            
            Active Category Budgets:
            {active_budgets_str}
            
            Investments Portfolio:
            {investments_str}
            
            Financial Goals:
            {goals_str}
            
            Conversation History so far:
            {formatted_history}
            
            User's new message:
            "{user_message}"
            
            The response must be returned in JSON format.
            The JSON output must have EXACTLY the following keys:
            1. "reply": Your complete markdown formatted reply to the user's message.
            2. "proactive_questions": An array of EXACTLY 3 highly intelligent, personalized clickable suggestion chips / follow-up questions related to the conversation topic or the user's financial situation.
            
            Return ONLY a valid JSON object matching this structure. Do not wrap the JSON in markdown code blocks like ```json ... ```. Just return raw JSON.
            """
            
            response = ai_client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            resp_text = response.text.strip()
            if resp_text.startswith("```"):
                lines = resp_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                resp_text = "\n".join(lines).strip()
                
            result = json.loads(resp_text)
            return jsonify({
                "success": True,
                "reply": result.get("reply", ""),
                "proactive_questions": result.get("proactive_questions", [])
            })
            
        except Exception as e:
            print(f"Gemini AI advisor chat response failed: {e}")
            
    # Fallback chat response
    fallback_data = generate_fallback_chat_reply(user, user_message)
    return jsonify({
        "success": True,
        "reply": fallback_data["reply"],
        "proactive_questions": fallback_data["proactive_questions"]
    })

# --- NOTIFICATION CENTER ---

@app.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "mark_all_read":
            notifs = Notification.query.filter_by(user_id=current_user.id, read=False).all()
            for n in notifs:
                n.read = True
            db.session.commit()
            flash("All alerts marked as read.", "success")
        elif action == "clear_all":
            Notification.query.filter_by(user_id=current_user.id).delete()
            db.session.commit()
            flash("Notification center successfully cleared.", "success")
        elif action == "mark_read":
            notif_id = request.form.get("notif_id")
            if notif_id:
                notif = Notification.query.filter_by(id=int(notif_id), user_id=current_user.id).first()
                if notif:
                    notif.read = True
                    db.session.commit()
                    flash("Alert marked as read.", "success")
        elif action == "delete":
            notif_id = request.form.get("notif_id")
            if notif_id:
                notif = Notification.query.filter_by(id=int(notif_id), user_id=current_user.id).first()
                if notif:
                    db.session.delete(notif)
                    db.session.commit()
                    flash("Alert removed.", "success")
        return redirect(url_for("notifications"))

    # Clear / read handles
    unread_count = Notification.query.filter_by(user_id=current_user.id, read=False).count()
    all_notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    
    return render_template("notifications.html", notifications=all_notifs, unread_count=unread_count)

@app.route("/notifications/read/<int:notif_id>", methods=["POST"])
@login_required
def read_notification(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id == current_user.id:
        notif.read = True
        db.session.commit()
        return jsonify({"success": True})
    return abort(403)

@app.route("/notifications/delete/<int:notif_id>", methods=["POST"])
@login_required
def delete_notification(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id == current_user.id:
        db.session.delete(notif)
        db.session.commit()
        return jsonify({"success": True})
    return abort(403)

@app.route("/notifications/read-all", methods=["POST"])
@login_required
def read_all_notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id, read=False).all()
    for n in notifs:
        n.read = True
    db.session.commit()
    flash("All alerts marked as read.", "success")
    return redirect(url_for("notifications"))

@app.route("/notifications/clear-all", methods=["POST"])
@login_required
def clear_all_notifications():
    Notification.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash("Notification center successfully cleared.", "success")
    return redirect(url_for("notifications"))

# --- PROFILE MANAGEMENT ---

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        action = request.form.get("action", "update_profile")
        
        if action == "update_profile":
            username = request.form.get("username")
            email = request.form.get("email")
            monthly_income = float(request.form.get("monthly_income") or 0.0)
            currency = request.form.get("currency", "$")
            if currency == "custom":
                currency = request.form.get("custom_currency", "$").strip() or "$"
            
            # Check if username or email is taken by other user
            existing_user = User.query.filter(User.username == username, User.id != current_user.id).first()
            existing_email = User.query.filter(User.email == email, User.id != current_user.id).first()
            
            if existing_user or existing_email:
                flash("Username or Email is already taken by another account.", "danger")
            else:
                current_user.username = username
                current_user.email = email
                current_user.monthly_income = monthly_income
                current_user.currency = currency
                
                # Profile Photo Update
                profile_file = request.files.get("profile_pic")
                if profile_file and allowed_file(profile_file.filename):
                    filename = secure_filename(profile_file.filename)
                    unique_name = f"profile_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                    profile_file.save(os.path.join(app.config["PROFILE_FOLDER"], unique_name))
                    current_user.profile_pic = unique_name
                    
                db.session.commit()
                flash("Profile details updated successfully.", "success")
                
        elif action == "change_password":
            old_password = request.form.get("old_password")
            new_password = request.form.get("new_password")
            confirm_password = request.form.get("confirm_password")
            
            if bcrypt.check_password_hash(current_user.password_hash, old_password):
                if new_password == confirm_password:
                    current_user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
                    db.session.commit()
                    flash("Password changed successfully.", "success")
                else:
                    flash("Passwords do not match.", "danger")
            else:
                flash("Incorrect current password.", "danger")
                
        return redirect(url_for("profile"))
        
    # Account statistics for profile view
    tx_count = len(current_user.expenses)
    total_spent = sum(e.amount for e in current_user.expenses if e.type == "expense")
    total_savings = sum(e.amount for e in current_user.expenses if e.type == "income") - total_spent
    
    return render_template(
        "profile.html",
        tx_count=tx_count,
        total_spent=total_spent,
        total_savings=total_savings
    )

# --- BACKUP & RESTORE SYSTEM ---

@app.route("/backup")
@login_required
def backup_database():
    """
    Backs up the SQLite database to a unique backup file in backup folder.
    """
    db_path = os.path.join("instance", "database.db")
    if not os.path.exists(db_path):
        # Fallback if SQLite runs directly in root
        db_path = "database.db"
        
    if not os.path.exists(db_path):
        flash("Local active database.db not found for backup operations.", "danger")
        return redirect(url_for("profile"))
        
    try:
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        dest_path = os.path.join(app.config["BACKUP_FOLDER"], backup_name)
        shutil.copy2(db_path, dest_path)
        
        # Flash message & serve the file directly as downloadable zip/file attachment
        return send_file(dest_path, as_attachment=True, download_name=backup_name)
    except Exception as e:
        flash(f"Failed to generate backup: {e}", "danger")
        return redirect(url_for("profile"))

@app.route("/restore", methods=["POST"])
@login_required
def restore_database():
    """
    Restores SQLite database from a uploaded .db file.
    """
    restore_file = request.files.get("backup_file")
    if restore_file and restore_file.filename.endswith(".db"):
        db_path = os.path.join("instance", "database.db")
        if not os.path.exists(db_path):
            db_path = "database.db"
            
        try:
            # Save upload as temporary
            temp_path = os.path.join("instance", "temp_restore.db")
            restore_file.save(temp_path)
            
            # Shut down existing database session before swapping
            db.session.remove()
            db.engine.dispose()
            
            # Replace active DB file
            shutil.copy2(temp_path, db_path)
            os.remove(temp_path)
            
            flash("Database restored successfully. Please sign in with restored credentials.", "success")
            logout_user()
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Failed to restore database: {e}", "danger")
    else:
        flash("Invalid file format. Please upload a valid .db backup file.", "danger")
        
    return redirect(url_for("profile"))

# --- EXPORTS & PDF REPORTS ---

@app.route("/export/csv/<string:module>")
@login_required
def export_csv(module):
    if module == "expenses":
        csv_data = export_expenses_csv(current_user.expenses)
        filename = "expenses_export.csv"
    elif module == "budgets":
        csv_data = export_budgets_csv(current_user.budgets)
        filename = "budgets_export.csv"
    elif module == "investments":
        csv_data = export_investments_csv(current_user.investments)
        filename = "investments_export.csv"
    elif module == "goals":
        csv_data = export_goals_csv(current_user.goals)
        filename = "goals_export.csv"
    else:
        return abort(404)
        
    return send_file(
        io.BytesIO(b'\xef\xbb\xbf' + csv_data.encode('utf-8')),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )

@app.route("/export/excel/<string:module>")
@login_required
def export_excel(module):
    if module == "expenses":
        excel_data = export_expenses_excel(current_user.expenses)
        filename = "expenses_export.xlsx"
    elif module == "budgets":
        excel_data = export_budgets_excel(current_user.budgets)
        filename = "budgets_export.xlsx"
    elif module == "investments":
        excel_data = export_investments_excel(current_user.investments)
        filename = "investments_export.xlsx"
    elif module == "goals":
        excel_data = export_goals_excel(current_user.goals)
        filename = "goals_export.xlsx"
    else:
        return abort(404)
        
    return send_file(
        io.BytesIO(excel_data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )

import io

@app.route("/export/pdf")
@login_required
def export_pdf():
    if not PDF_SUPPORT:
        flash("PDF Report generation system is configuring. Please try again shortly.", "warning")
        return redirect(url_for("dashboard"))
        
    # Generate recommendations for context
    recs = get_rule_based_recommendations(current_user, current_user.expenses, current_user.budgets, current_user.investments, current_user.goals)
    health = calculate_financial_health(current_user, current_user.expenses, current_user.budgets, current_user.investments, current_user.goals)
    
    try:
        pdf_bytes = generate_financial_pdf(
            user=current_user,
            health=health,
            expenses=current_user.expenses,
            budgets=current_user.budgets,
            investments=current_user.investments,
            goals=current_user.goals,
            recommendations=recs
        )
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"finsight_financial_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
        )
    except Exception as e:
        flash(f"Error during PDF compilation: {e}", "danger")
        return redirect(url_for("dashboard"))

# --- RULE-BASED AND GEMINI AI recommendations ---

@app.route("/api/ai/recommendations", methods=["POST"])
@login_required
def ai_recommendations():
    """
    Returns AI-powered budget recommendations, spending analyses, and portfolio advice.
    Integrates Gemini server-side if API key is defined, else defaults to smart local heuristics.
    """
    custom_prompt = request.json.get("customPrompt", "") if request.is_json else ""
    
    # Generate stats for context
    total_income = sum(e.amount for e in current_user.expenses if e.type == "income")
    total_expense = sum(e.amount for e in current_user.expenses if e.type == "expense")
    net_savings = total_income - total_expense
    
    category_spending = defaultdict(float)
    for e in current_user.expenses:
        if e.type == "expense":
            category_spending[e.category] += e.amount
            
    # Compile portfolio structure
    portfolio_value = sum(i.quantity * i.current_price for i in current_user.investments)
    
    # Dynamic rules fallback (high quality)
    local_recs = get_rule_based_recommendations(current_user, current_user.expenses, current_user.budgets, current_user.investments, current_user.goals)
    
    if ai_client:
        try:
            # Build intelligent structured query context
            data_context = {
                "profile": {
                    "username": current_user.username,
                    "monthly_income": current_user.monthly_income,
                    "savings_streak_months": current_user.savings_streak,
                },
                "cash_flow": {
                    "total_income": total_income,
                    "total_expenses": total_expense,
                    "net_savings": net_savings
                },
                "spending_categories": dict(category_spending),
                "budgets": [{"category": b.category, "limit": b.amount_limit} for b in current_user.budgets],
                "portfolio_investments": [{"symbol": i.symbol, "quantity": i.quantity, "purchase_price": i.buy_price, "current_price": i.current_price, "type": i.asset_type} for i in current_user.investments],
                "financial_goals": [{"name": g.name, "target": g.target_amount, "saved": g.current_amount, "deadline": g.deadline.strftime("%Y-%m-%d")} for g in current_user.goals],
                "user_prompt": custom_prompt
            }
            
            prompt = f"""
            As FinSight AI, a premier personal banking and asset advisor, analyze the user's detailed portfolio & expense structures.
            UserData: {data_context}
            
            Provide:
            1. An executive summary insight regarding category outlays, savings rate and asset exposure.
            2. 3 highly specific, numerical, tactical actions to optimize budgets, reduce food/shopping leaks, and compound portfolio wealth.
            3. A short prediction on emergency funding milestones.
            
            Structure the advice elegantly using markdown formatting. Highlight statistics in bold.
            """
            
            response = ai_client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt
            )
            
            ai_text = response.text
            return jsonify({"success": True, "source": "Gemini AI Advisor", "response": ai_text})
            
        except Exception as e:
            print(f"Gemini AI recommendation failed: {e}")
            
    # Default high-quality local rule-based builder response if Gemini is not set or fails
    insight_text = f"Based on your recent transactions, your **savings rate** is **{(net_savings/total_income*100) if total_income > 0 else 0:.1f}%**. "
    if user_shopping := category_spending.get("Shopping", 0.0):
        if total_expense > 0 and (user_shopping / total_expense) > 0.3:
            insight_text += "Your **Shopping** category is currently representing a large share of outlays. "
            
    recs_formatted = []
    for r in local_recs:
        impact_color = "text-danger" if r["impact"] == "High" else "text-warning"
        recs_formatted.append(f"<li><span class='badge bg-light text-dark'>{r['category']}</span> <strong class='{impact_color}'>[{r['impact']} Impact]</strong> <strong>{r['title']}</strong>: {r['description']} (Action: <em>{r['action']}</em>)</li>")
        
    html_fallback = f"""
    <h4><strong>Platform Intelligence Analysis</strong></h4>
    <p>{insight_text}</p>
    <h5><strong>Automated Strategic Actions:</strong></h5>
    <ul class="ps-3">
        {"".join(recs_formatted)}
    </ul>
    """
    return jsonify({"success": True, "source": "Rule-based AI Engine", "response": html_fallback})


# Initialize Database & Tables
with app.app_context():
    # Store SQLite db inside the standard instance path
    db.create_all()
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('users')]
        if 'currency' not in columns:
            db.session.execute(db.text("ALTER TABLE users ADD COLUMN currency VARCHAR(10) DEFAULT '$'"))
            db.session.commit()
            print("Successfully added currency column to users table.")
    except Exception as e:
        print(f"Error migration: {e}")

    try:
        if not User.query.filter_by(email="demo@finsight.com").first():
            # Create a default demo user
            hashed_pw = bcrypt.generate_password_hash("password123").decode('utf-8')
            demo_user = User(
                username="DemoUser",
                email="demo@finsight.com",
                password_hash=hashed_pw,
                security_question="What is your favorite financial asset?",
                security_answer="bitcoin",
                monthly_income=5500.0,
                profile_pic="default_avatar.png",
                currency="$"
            )
            db.session.add(demo_user)
            db.session.commit()
            seed_demo_data(demo_user)
            print("Successfully pre-seeded default demo user: demo@finsight.com / password123")
    except Exception as e:
        print(f"Error seeding default user: {e}")


if __name__ == "__main__":
    # Ensure standard binding to Port 3000 for server architecture compliance
    app.run(host="0.0.0.0", port=3000, debug=True)
