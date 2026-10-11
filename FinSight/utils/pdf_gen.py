from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io
from datetime import datetime

def generate_financial_pdf(user, health, expenses, budgets, investments, goals, recommendations):
    """
    Generates a beautifully structured PDF Report containing:
    - Income, Expenses, Budget, Goals, Investments
    - Health Score (Value, Badge, breakdowns)
    - Actionable AI Recommendations
    Returns the PDF as bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    # Custom elegant styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        textColor=colors.HexColor("#0d6efd"), # Blue accent
        spaceAfter=15,
        alignment=1 # Centered
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=10,
        textColor=colors.HexColor("#6c757d"),
        spaceAfter=25,
        alignment=1
    )
    
    h1_style = ParagraphStyle(
        'HeadingSection',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=colors.HexColor("#0f172a"), # Dark Blue/Charcoal
        spaceBefore=15,
        spaceAfter=10,
        borderColor=colors.HexColor("#cbd5e1"),
        borderWidth=1,
        borderPadding=4
    )
    
    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor("#334155"),
        spaceAfter=6
    )
    
    bold_style = ParagraphStyle(
        'BodyTextBoldCustom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor=colors.HexColor("#0f172a")
    )
    
    story = []
    
    # Title & Header
    story.append(Paragraph("FinSight Financial Intelligence Report", title_style))
    story.append(Paragraph(f"Generated for {user.username} ({user.email}) | Date: {date_format()}", subtitle_style))
    story.append(Spacer(1, 10))
    
    # Section 1: Financial Health Score
    story.append(Paragraph("1. Overall Financial Health Summary", h1_style))
    
    health_data = [
        [Paragraph("<b>Financial Health Score:</b>", body_style), Paragraph(f"<font color='#0d6efd'><b>{health['score']} / 100</b></font> ({health['label']})", bold_style)],
        [Paragraph("<b>Active Savings Rate:</b>", body_style), Paragraph(f"{health['savings_rate']:.1f}% of monthly income", body_style)],
        [Paragraph("<b>Savings Streak:</b>", body_style), Paragraph(f"{user.savings_streak} Months Saved", body_style)]
    ]
    
    health_table = Table(health_data, colWidths=[200, 300])
    health_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor("#f1f5f9")),
    ]))
    story.append(health_table)
    story.append(Spacer(1, 15))
    
    # Section 2: Cash Flow Summary
    story.append(Paragraph("2. Cash Flow & Monthly Transactions Summary", h1_style))
    
    total_income = sum(e.amount for e in expenses if e.type == "income")
    total_expense = sum(e.amount for e in expenses if e.type == "expense")
    net_savings = total_income - total_expense
    
    cash_flow_data = [
        [Paragraph("<b>Financial Vector</b>", bold_style), Paragraph("<b>Total Volume ($)</b>", bold_style), Paragraph("<b>Status</b>", bold_style)],
        [Paragraph("Total Logged Income", body_style), Paragraph(f"${total_income:,.2f}", body_style), Paragraph("Inflow", body_style)],
        [Paragraph("Total Logged Expenses", body_style), Paragraph(f"${total_expense:,.2f}", body_style), Paragraph("Outflow", body_style)],
        [Paragraph("Net Monthly Savings", body_style), Paragraph(f"${net_savings:,.2f}", bold_style), Paragraph("Compounding Capital" if net_savings >= 0 else "Net Deficit", bold_style)]
    ]
    
    cf_table = Table(cash_flow_data, colWidths=[200, 150, 150])
    cf_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f8fafc")),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor("#cbd5e1")),
        ('LINEBELOW', (0,1), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    story.append(cf_table)
    story.append(Spacer(1, 15))
    
    # Section 3: Budget Allocations
    story.append(Paragraph("3. Category Budgets & Overspending Alerts", h1_style))
    if budgets:
        budget_headers = [Paragraph("<b>Category</b>", bold_style), Paragraph("<b>Budget Limit ($)</b>", bold_style), Paragraph("<b>Current Spent ($)</b>", bold_style), Paragraph("<b>Status Badge</b>", bold_style)]
        budget_rows = [budget_headers]
        
        for b in budgets:
            spent = sum(e.amount for e in expenses if e.type == "expense" and e.category.lower() == b.category.lower())
            is_over = spent > b.amount_limit
            status = f"<font color='red'>Overspent by ${(spent - b.amount_limit):,.2f}</font>" if is_over else f"<font color='green'>Safe (${(b.amount_limit - spent):,.2f} left)</font>"
            budget_rows.append([
                Paragraph(b.category, body_style),
                Paragraph(f"${b.amount_limit:,.2f}", body_style),
                Paragraph(f"${spent:,.2f}", body_style),
                Paragraph(status, body_style)
            ])
            
        b_table = Table(budget_rows, colWidths=[150, 100, 100, 150])
        b_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f8fafc")),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor("#cbd5e1")),
            ('LINEBELOW', (0,1), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ]))
        story.append(b_table)
    else:
        story.append(Paragraph("No monthly category budgets established yet. Create category limits inside the Budget module to prevent overspending leaks.", body_style))
    story.append(Spacer(1, 15))
    
    # Section 4: Investment Portfolio Valuation
    story.append(Paragraph("4. Investment Portfolio Valuations", h1_style))
    if investments:
        inv_headers = [Paragraph("<b>Symbol</b>", bold_style), Paragraph("<b>Name</b>", bold_style), Paragraph("<b>Quantity</b>", bold_style), Paragraph("<b>Buy Price ($)</b>", bold_style), Paragraph("<b>Current ($)</b>", bold_style), Paragraph("<b>Total Value ($)</b>", bold_style)]
        inv_rows = [inv_headers]
        
        total_value = 0.0
        for i in investments:
            val = i.quantity * i.current_price
            total_value += val
            inv_rows.append([
                Paragraph(i.symbol, body_style),
                Paragraph(i.name, body_style),
                Paragraph(f"{i.quantity:,.4f}", body_style),
                Paragraph(f"${i.buy_price:,.2f}", body_style),
                Paragraph(f"${i.current_price:,.2f}", body_style),
                Paragraph(f"${val:,.2f}", body_style)
            ])
        
        # Add summary line
        inv_rows.append([Paragraph("<b>Total Portfolio Valuation</b>", bold_style), Paragraph("", body_style), Paragraph("", body_style), Paragraph("", body_style), Paragraph("", body_style), Paragraph(f"<b>${total_value:,.2f}</b>", bold_style)])
        
        i_table = Table(inv_rows, colWidths=[60, 130, 70, 70, 70, 100])
        i_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f8fafc")),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor("#cbd5e1")),
            ('LINEBELOW', (0,1), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
            ('LINEBELOW', (0,-1), (-1,-1), 1, colors.HexColor("#0d6efd")),
        ]))
        story.append(i_table)
    else:
        story.append(Paragraph("No active investments logged inside the platform. Start early to leverage compounding growth dynamics.", body_style))
    story.append(Spacer(1, 15))
    
    # Section 5: Financial Goals Track
    story.append(Paragraph("5. Long-term Financial Goals", h1_style))
    if goals:
        goal_headers = [Paragraph("<b>Goal Name</b>", bold_style), Paragraph("<b>Target ($)</b>", bold_style), Paragraph("<b>Current Saved ($)</b>", bold_style), Paragraph("<b>Completion %</b>", bold_style), Paragraph("<b>Deadline</b>", bold_style)]
        goal_rows = [goal_headers]
        
        for g in goals:
            pct = (g.current_amount / g.target_amount) * 100 if g.target_amount > 0 else 0
            goal_rows.append([
                Paragraph(g.name, body_style),
                Paragraph(f"${g.target_amount:,.2f}", body_style),
                Paragraph(f"${g.current_amount:,.2f}", body_style),
                Paragraph(f"{pct:.1f}%", body_style),
                Paragraph(g.deadline.strftime("%Y-%m-%d"), body_style)
            ])
            
        g_table = Table(goal_rows, colWidths=[150, 90, 90, 80, 90])
        g_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f8fafc")),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor("#cbd5e1")),
            ('LINEBELOW', (0,1), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ]))
        story.append(g_table)
    else:
        story.append(Paragraph("No long-term financial goals defined yet. Define goals like Emergency Funds or Travel targets inside the Goal tracker.", body_style))
    story.append(Spacer(1, 15))
    
    # Section 6: AI Generated Recommendations
    story.append(Paragraph("6. Platform Intelligence Advisory", h1_style))
    
    if recommendations:
        for idx, rec in enumerate(recommendations, 1):
            impact_text = f"<font color='red'><b>[{rec.get('impact', 'Medium')} Impact]</b></font>" if rec.get('impact') == "High" else f"<font color='orange'><b>[{rec.get('impact', 'Medium')} Impact]</b></font>"
            story.append(Paragraph(f"<b>Recommendation {idx}: {rec.get('title')}</b> - {impact_text}", bold_style))
            story.append(Paragraph(f"<i>Category: {rec.get('category')} | Suggested Action: {rec.get('action')}</i>", body_style))
            story.append(Paragraph(rec.get('description'), body_style))
            story.append(Spacer(1, 8))
    else:
        story.append(Paragraph("FinSight Intelligence has no urgent advice. Continue logging transactions to trigger deeper recommendations.", body_style))
        
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def date_format():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
