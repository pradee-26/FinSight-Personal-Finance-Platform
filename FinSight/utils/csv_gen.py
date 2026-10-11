import csv
import io

def export_expenses_csv(expenses):
    """
    Generates a CSV string containing all expenses.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(["ID", "Category", "Amount", "Date", "Description", "Type", "Receipt Filename"])
    
    for e in expenses:
        writer.writerow([
            e.id,
            e.category,
            e.amount,
            e.date.strftime("%Y-%m-%d"),
            e.description or "",
            e.type,
            e.receipt_filename or ""
        ])
        
    return output.getvalue()

def export_budgets_csv(budgets):
    """
    Generates a CSV string containing all budgets.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(["ID", "Category", "Amount Limit", "Period"])
    
    for b in budgets:
        writer.writerow([
            b.id,
            b.category,
            b.amount_limit,
            b.period
        ])
        
    return output.getvalue()

def export_investments_csv(investments):
    """
    Generates a CSV string containing all investments.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(["ID", "Symbol", "Name", "Quantity", "Buy Price", "Current Price", "Asset Type", "Purchase Date"])
    
    for i in investments:
        writer.writerow([
            i.id,
            i.symbol,
            i.name,
            i.quantity,
            i.buy_price,
            i.current_price,
            i.asset_type,
            i.purchase_date.strftime("%Y-%m-%d")
        ])
        
    return output.getvalue()

def export_goals_csv(goals):
    """
    Generates a CSV string containing all financial goals.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(["ID", "Goal Name", "Target Amount", "Current Saved Amount", "Deadline", "Category", "Completion %"])
    
    for g in goals:
        pct = (g.current_amount / g.target_amount) * 100 if g.target_amount > 0 else 0
        writer.writerow([
            g.id,
            g.name,
            g.target_amount,
            g.current_amount,
            g.deadline.strftime("%Y-%m-%d"),
            g.category,
            f"{pct:.1f}%"
        ])
        
    return output.getvalue()
