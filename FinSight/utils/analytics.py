from datetime import datetime, date
from collections import Counter, defaultdict

def calculate_financial_health(user, expenses, budgets, investments, goals):
    """
    Calculates a comprehensive Financial Health Score (0 to 100)
    conforming to:
    - circular progress / gauge meter
    - health badge (Poor, Average, Good, Excellent)
    - breakdown categories (Spending, Savings, Investments, Debt/Budget Management)
    """
    # Initialize component scores (total max = 100)
    # 1. Savings Rate Score (max 30)
    # 2. Budget Discipline Score (max 25)
    # 3. Investment Setup Score (max 25)
    # 4. Goals Progress Score (max 20)
    
    total_income = sum(e.amount for e in expenses if e.type == "income")
    total_expense = sum(e.amount for e in expenses if e.type == "expense")
    
    # 1. Savings Rate Score (max 30)
    savings_rate_score = 0
    savings_rate = 0.0
    if total_income > 0:
        net_savings = total_income - total_expense
        savings_rate = (net_savings / total_income) * 100
        if savings_rate >= 30:
            savings_rate_score = 30
        elif savings_rate >= 20:
            savings_rate_score = 25
        elif savings_rate >= 10:
            savings_rate_score = 18
        elif savings_rate >= 0:
            savings_rate_score = 10
        else:
            savings_rate_score = 2 # negative savings rate
    else:
        # If no income, score is 5 if they have zero expenses, 0 if they have expenses
        savings_rate_score = 5 if total_expense == 0 else 0

    # 2. Budget Discipline Score (max 25)
    budget_discipline_score = 25
    if budgets:
        exceeded_count = 0
        for b in budgets:
            b_cat = (b.category or "").strip().lower()
            category_spent = sum(e.amount for e in expenses if e.type == "expense" and (e.category or "").strip().lower() == b_cat)
            if category_spent > b.amount_limit:
                exceeded_count += 1
        
        # Deduct points for each exceeded budget
        if len(budgets) > 0:
            penalty = (exceeded_count / len(budgets)) * 25
            budget_discipline_score = max(0, int(25 - penalty))
    else:
        # No budgets defined - mid-range score (12 points out of 25 as starting point)
        budget_discipline_score = 12

    # 3. Investment Setup Score (max 25)
    # Score based on existence and diversity of assets
    investment_setup_score = 0
    if investments:
        unique_assets = len(set(i.symbol for i in investments))
        total_value = sum(i.quantity * i.current_price for i in investments)
        
        if total_value > 0:
            if unique_assets >= 4:
                investment_setup_score = 25
            elif unique_assets >= 2:
                investment_setup_score = 20
            else:
                investment_setup_score = 12
    else:
        investment_setup_score = 0

    # 4. Goals Progress Score (max 20)
    goals_progress_score = 0
    if goals:
        total_progress_pct = 0.0
        for g in goals:
            if g.target_amount > 0:
                pct = (g.current_amount / g.target_amount) * 100
                total_progress_pct += min(100.0, pct)
        
        avg_progress = total_progress_pct / len(goals)
        goals_progress_score = int((avg_progress / 100) * 20)
    else:
        goals_progress_score = 8 # baseline score if no goals

    # Final calculation
    final_score = int(savings_rate_score + budget_discipline_score + investment_setup_score + goals_progress_score)
    final_score = max(0, min(100, final_score))
    
    # Categorization
    if final_score < 50:
        label = "Poor"
        badge_color = "danger"  # red
    elif final_score < 70:
        label = "Average"
        badge_color = "warning" # yellow/orange
    elif final_score < 85:
        label = "Good"
        badge_color = "info"    # blue
    else:
        label = "Excellent"
        badge_color = "success" # green
        
    return {
        "score": final_score,
        "label": label,
        "badge_color": badge_color,
        "breakdown": {
            "savings_rate_score": savings_rate_score,
            "budget_discipline_score": budget_discipline_score,
            "investment_setup_score": investment_setup_score,
            "goals_progress_score": goals_progress_score
        },
        "savings_rate": savings_rate
    }

def calculate_savings_streak(user, expenses):
    """
    Calculates the streak of consecutive calendar months where the user had a positive savings rate.
    Uses expenses and income. Group by year-month.
    """
    if not expenses:
        return 0
        
    monthly_data = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for e in expenses:
        # Group by YYYY-MM
        ym = e.date.strftime("%Y-%m")
        if e.type == "income":
            monthly_data[ym]["income"] += e.amount
        else:
            monthly_data[ym]["expense"] += e.amount
            
    # Sort key months chronologically
    sorted_months = sorted(monthly_data.keys())
    
    streak = 0
    max_streak = 0
    
    for ym in sorted_months:
        net = monthly_data[ym]["income"] - monthly_data[ym]["expense"]
        if net > 0:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0
            
    return streak

def get_rule_based_recommendations(user, expenses, budgets, investments, goals):
    """
    Generates intelligent rule-based AI recommendations conforming to:
    - Shopping > 30% -> Reduce shopping
    - Food > 40% -> Cook more at home
    - Budget exceeded -> Reduce unnecessary expenses
    - Savings < 20% -> Increase monthly savings
    - Investment Loss -> Review portfolio
    - Goal deadline approaching -> Increase monthly contribution
    """
    recommendations = []
    sym = getattr(user, "currency", "$") or "$"
    
    # Totals
    total_income = sum(e.amount for e in expenses if e.type == "income")
    total_expense = sum(e.amount for e in expenses if e.type == "expense")
    
    # 1. Shopping Category spending check
    shopping_spent = sum(e.amount for e in expenses if e.type == "expense" and (e.category or "").strip().lower() == "shopping")
    if total_expense > 0 and (shopping_spent / total_expense) > 0.30:
        recommendations.append({
            "title": "High Shopping Allocation Detected",
            "description": f"Your shopping purchases account for {int((shopping_spent / total_expense)*100)}% of your overall expenditures (above the recommended 30% soft threshold). Consider delaying optional retail purchases.",
            "impact": "High",
            "category": "Shopping",
            "action": "Reduce Shopping spending"
        })
        
    # 2. Food Category spending check
    food_spent = sum(e.amount for e in expenses if e.type == "expense" and (e.category or "").strip().lower() in ["food", "dining out", "groceries"])
    if total_expense > 0 and (food_spent / total_expense) > 0.40:
        recommendations.append({
            "title": "High Food & Dining Outlays",
            "description": f"Food and dining purchases make up {int((food_spent / total_expense)*100)}% of your expenses. Cooking more meals at home and preparing bulk lunches can unlock substantial weekly cash flows.",
            "impact": "Medium",
            "category": "Food",
            "action": "Cook more at home"
        })
        
    # 3. Budget Exceeded check
    for b in budgets:
        b_cat = (b.category or "").strip().lower()
        cat_spent = sum(e.amount for e in expenses if e.type == "expense" and (e.category or "").strip().lower() == b_cat)
        if cat_spent > b.amount_limit:
            recommendations.append({
                "title": f"Budget Exceeded in '{b.category}'",
                "description": f"You spent {sym}{cat_spent:,.2f} which exceeds your designated limit of {sym}{b.amount_limit:,.2f} by {sym}{cat_spent - b.amount_limit:,.2f}. Try pausing or scaling back discretionary purchases.",
                "impact": "High",
                "category": "Budget",
                "action": "Reduce unnecessary expenses"
            })
            
    # 4. Savings rate check
    if total_income > 0:
        savings_rate = ((total_income - total_expense) / total_income) * 100
        if savings_rate < 20:
            recommendations.append({
                "title": "Boost Your Monthly Savings Rate",
                "description": f"Your current savings rate is {savings_rate:.1f}%, which is below the benchmark 20%. Try setting up automatic direct-deposits into high-yield accounts on payday.",
                "impact": "High",
                "category": "Savings",
                "action": "Increase monthly savings"
            })
            
    # 5. Investment loss check
    portfolio_value = 0.0
    invested_capital = 0.0
    for inv in investments:
        portfolio_value += inv.quantity * inv.current_price
        invested_capital += inv.quantity * inv.buy_price
        
    if invested_capital > 0:
        overall_gain = portfolio_value - invested_capital
        if overall_gain < 0:
            recommendations.append({
                "title": "Investment Portfolio Review Needed",
                "description": f"Your current investment portfolio shows a net loss of {sym}{abs(overall_gain):,.2f} ({ (overall_gain/invested_capital)*100 :.1f}% return). It might be time to diversify into lower-cost index funds.",
                "impact": "Medium",
                "category": "Investment",
                "action": "Review portfolio allocation and rebalance"
            })
            
    # 6. Goal deadline approaching check
    for g in goals:
        if g.current_amount < g.target_amount:
            days_left = (g.deadline - date.today()).days
            if 0 < days_left <= 45: # under 45 days left
                shortfall = g.target_amount - g.current_amount
                recommendations.append({
                    "title": f"Goal Approaching: '{g.name}'",
                    "description": f"The deadline is in {days_left} days, and you are {sym}{shortfall:,.2f} away from your target. Boost your monthly contributions to cross the finish line in time.",
                    "impact": "High",
                    "category": "Goal",
                    "action": "Increase monthly contribution to goal"
                })
                
    # Add a fallback standard recommendation if list is empty
    if not recommendations:
        recommendations.append({
            "title": "Healthy Financial Standing!",
            "description": "Your current budgets are well-allocated and savings rates are sound. To further supercharge your wealth, investigate automatic dividend reinvestment strategies (DRIP).",
            "impact": "Low",
            "category": "General",
            "action": "Maintain healthy spending habits"
        })
        
    return recommendations

def get_expense_insights(expenses):
    """
    Shows:
    - Most expensive day
    - Most frequent category
    - Largest expense
    - Smallest expense
    - Monthly average
    """
    exp_only = [e for e in expenses if e.type == "expense"]
    if not exp_only:
        return {
            "most_expensive_day": "None",
            "most_frequent_category": "None",
            "largest_expense": 0.0,
            "smallest_expense": 0.0,
            "monthly_average": 0.0
        }
        
    # Most expensive day
    day_spend = defaultdict(float)
    for e in exp_only:
        day_spend[e.date.strftime("%A")] += e.amount
    most_expensive_day = max(day_spend, key=day_spend.get)
    
    # Most frequent category
    categories = [e.category for e in exp_only]
    most_frequent_category = Counter(categories).most_common(1)[0][0]
    
    # Largest and Smallest
    largest_expense = max(e.amount for e in exp_only)
    smallest_expense = min(e.amount for e in exp_only)
    
    # Monthly average
    total_spent = sum(e.amount for e in exp_only)
    unique_months = len(set(e.date.strftime("%Y-%m") for e in exp_only))
    unique_months = max(1, unique_months)
    monthly_average = total_spent / unique_months
    
    return {
        "most_expensive_day": most_expensive_day,
        "most_frequent_category": most_frequent_category,
        "largest_expense": largest_expense,
        "smallest_expense": smallest_expense,
        "monthly_average": monthly_average
    }

def get_investment_insights(investments):
    """
    Shows:
    - Best Performing Asset
    - Worst Performing Asset
    - Highest Return (value)
    - Lowest Return (value)
    - Portfolio Allocation (pcts)
    """
    if not investments:
        return {
            "best_performing": "None",
            "worst_performing": "None",
            "highest_return_val": 0.0,
            "lowest_return_val": 0.0,
            "portfolio_value": 0.0,
            "allocation": {}
        }
        
    portfolio_value = sum(i.quantity * i.current_price for i in investments)
    
    performance = []
    allocation = defaultdict(float)
    
    for i in investments:
        cost = i.quantity * i.buy_price
        current = i.quantity * i.current_price
        gain_pct = ((i.current_price - i.buy_price) / i.buy_price) * 100 if i.buy_price > 0 else 0
        gain_val = current - cost
        
        performance.append({
            "symbol": i.symbol,
            "gain_pct": gain_pct,
            "gain_val": gain_val
        })
        
        allocation[i.asset_type.capitalize()] += current
        
    # Sort performance
    sorted_perf = sorted(performance, key=lambda x: x["gain_pct"])
    best_performing = sorted_perf[-1]["symbol"] if sorted_perf else "None"
    worst_performing = sorted_perf[0]["symbol"] if sorted_perf else "None"
    
    highest_return_val = max(p["gain_val"] for p in performance)
    lowest_return_val = min(p["gain_val"] for p in performance)
    
    # Allocation Percentages
    allocation_pcts = {}
    if portfolio_value > 0:
        for k, v in allocation.items():
            allocation_pcts[k] = (v / portfolio_value) * 100
            
    return {
        "best_performing": best_performing,
        "worst_performing": worst_performing,
        "highest_return_val": highest_return_val,
        "lowest_return_val": lowest_return_val,
        "portfolio_value": portfolio_value,
        "allocation": allocation_pcts
    }
