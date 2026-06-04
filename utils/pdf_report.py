import os
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from utils.logger import get_logger

logger = get_logger("PDFReport")

# Color scheme
NAVY = HexColor("#0b132b")
GOLD = HexColor("#e0a96d")
CHARCOAL = HexColor("#222222")
LIGHT_GREY = HexColor("#f4f6f9")
WHITE = HexColor("#ffffff")
GREEN = HexColor("#2e7d32")
RED = HexColor("#c62828")
ORANGE = HexColor("#ef6c00")

class NumberedCanvas(canvas.Canvas):
    """
    Custom canvas to enable 2-pass page numbering ('Page X of Y')
    and premium header/footer.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        
        # Header - Draw thin gold line & brand name
        self.setStrokeColor(GOLD)
        self.setLineWidth(1)
        self.line(54, 738, 558, 738)
        
        self.setFont("Helvetica-Bold", 10)
        self.setFillColor(NAVY)
        self.drawString(54, 744, "SMART LOAN ADVISOR")
        
        self.setFont("Helvetica", 8)
        self.setFillColor(CHARCOAL)
        self.drawRightString(558, 744, "Personalized Credit & Loan Advisory Report")
        
        # Footer - Draw thin grey line & page number
        self.setStrokeColor(HexColor("#e0e0e0"))
        self.line(54, 54, 558, 54)
        
        # Page Number: 'Page X of Y'
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.setFont("Helvetica", 9)
        self.setFillColor(CHARCOAL)
        self.drawRightString(558, 40, page_text)
        
        # Date footer
        date_str = datetime.now().strftime("%d %B %Y")
        self.drawString(54, 40, f"Generated on {date_str} | Confidential")
        
        self.restoreState()

def get_badge_style(status):
    """
    Returns text color, background color, and label based on eligibility status.
    """
    stat = status.upper()
    if "ELIGIBLE" in stat and "NOT" not in stat and "CONDITION" not in stat:
        return WHITE, GREEN, "ELIGIBLE"
    elif "CONDITION" in stat:
        return WHITE, ORANGE, "CONDITIONALLY ELIGIBLE"
    else:
        return WHITE, RED, "NOT ELIGIBLE"

def generate_pdf_report(customer, eligibility, comparisons, recommendations, tips, output_path):
    """
    Builds the 5-page PDF report.
    """
    try:
        # Create directories if they do not exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Setup document template with 0.75-inch margins (54 points)
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            leftMargin=54,
            rightMargin=54,
            topMargin=72,
            bottomMargin=72
        )
        
        styles = getSampleStyleSheet()
        
        # Custom Typography Styles
        title_style = ParagraphStyle(
            'ReportTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=24,
            leading=28,
            textColor=NAVY,
            spaceAfter=20
        )
        
        section_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=16,
            leading=20,
            textColor=NAVY,
            spaceBefore=15,
            spaceAfter=12,
            keepWithNext=True
        )
        
        body_style = ParagraphStyle(
            'ReportBody',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=CHARCOAL,
            spaceAfter=8
        )
        
        bold_body_style = ParagraphStyle(
            'ReportBodyBold',
            parent=body_style,
            fontName='Helvetica-Bold'
        )

        meta_label_style = ParagraphStyle(
            'MetaLabel',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=12,
            textColor=NAVY
        )
        
        table_cell_style = ParagraphStyle(
            'TableCell',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            textColor=CHARCOAL
        )

        table_header_style = ParagraphStyle(
            'TableHeader',
            parent=table_cell_style,
            fontName='Helvetica-Bold',
            textColor=WHITE
        )

        rec_card_title_style = ParagraphStyle(
            'RecCardTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=12,
            leading=15,
            textColor=NAVY,
            spaceAfter=4
        )

        bullet_style = ParagraphStyle(
            'ReportBullet',
            parent=body_style,
            leftIndent=15,
            bulletIndent=5,
            spaceAfter=4
        )
        
        story = []
        
        # ==========================================
        # PAGE 1: COVER & CUSTOMER SUMMARY
        # ==========================================
        story.append(Paragraph("SMART LOAN ADVISOR", ParagraphStyle('LogoText', fontName='Helvetica-Bold', fontSize=14, textColor=GOLD, spaceAfter=30)))
        story.append(Paragraph("Personalized Loan Recommendation Report", title_style))
        story.append(Paragraph("An intelligent financial profile evaluation, eligibility check, and side-by-side product comparison prepared specifically for your loan requirement.", body_style))
        story.append(Spacer(1, 20))
        
        story.append(Paragraph("1. Customer Financial Profile", section_style))
        
        # Construct summary table
        profile_data = [
            [Paragraph("Field", table_header_style), Paragraph("Detail Value", table_header_style)],
            [Paragraph("Full Name", meta_label_style), Paragraph(customer.get("name", "N/A"), body_style)],
            [Paragraph("Age", meta_label_style), Paragraph(str(customer.get("age", "N/A")), body_style)],
            [Paragraph("City", meta_label_style), Paragraph(customer.get("city", "N/A"), body_style)],
            [Paragraph("Employment Type", meta_label_style), Paragraph(customer.get("employment_type", "N/A"), body_style)],
            [Paragraph("Net Monthly Income", meta_label_style), Paragraph(f"INR {customer.get('monthly_income', 0):,.2f}", body_style)],
            [Paragraph("Existing EMIs", meta_label_style), Paragraph(f"INR {customer.get('existing_emis', 0):,.2f}", body_style)],
            [Paragraph("Credit Score", meta_label_style), Paragraph(str(customer.get("credit_score", "N/A")), body_style)],
            [Paragraph("Loan Purpose", meta_label_style), Paragraph(customer.get("loan_purpose", "N/A"), body_style)],
            [Paragraph("Desired Loan Amount", meta_label_style), Paragraph(f"INR {customer.get('desired_amount', 0):,.2f}", body_style)],
            [Paragraph("Preferred Tenure", meta_label_style), Paragraph(f"{customer.get('preferred_tenure', 0)} Years", body_style)],
            [Paragraph("Collateral / Assets Available", meta_label_style), Paragraph("Yes" if customer.get("has_collateral") else "No", body_style)],
        ]
        
        t1 = Table(profile_data, colWidths=[200, 304])
        t1.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (1,0), NAVY),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, LIGHT_GREY]),
            ('GRID', (0,0), (-1,-1), 0.5, HexColor("#d0d0d0")),
        ]))
        story.append(t1)
        story.append(PageBreak())
        
        # ==========================================
        # PAGE 2: ELIGIBILITY EVALUATION
        # ==========================================
        story.append(Paragraph("2. Loan Eligibility Evaluation Summary", section_style))
        story.append(Paragraph(f"Our Credit Risk analysis evaluated your profile against banking rules. Based on your Net Monthly Income (INR {customer.get('monthly_income',0):,.2f}) and obligations (INR {customer.get('existing_emis',0):,.2f}), your Debt-to-Income (DTI) ratio is <b>{eligibility.get('dti_ratio', 0):.2f}%</b>.", body_style))
        if eligibility.get("is_high_risk"):
            story.append(Paragraph("<b>WARNING:</b> Your financial profile is flagged as High Risk due to a DTI ratio exceeding 50% or a low credit score. This will restrict your options.", ParagraphStyle('WarningText', parent=body_style, textColor=RED, fontName='Helvetica-Bold')))
        story.append(Spacer(1, 10))
        
        # Map eligibility to table rows
        elig_headers = [
            Paragraph("Loan Category", table_header_style), 
            Paragraph("Eligibility Status", table_header_style), 
            Paragraph("Decision Details & Policy Reason", table_header_style)
        ]
        elig_data_table = [elig_headers]
        
        for loan_type, details in eligibility.get("loan_type_eligibility", {}).items():
            status_val = "Not Eligible"
            reason_val = "N/A"
            if isinstance(details, str):
                status_val = details
            elif isinstance(details, dict):
                status_val = details.get("status", "Not Eligible")
                reason_val = details.get("reason") or "N/A"
                
            txt_color, bg_color, label = get_badge_style(status_val)
            
            badge = Table([[Paragraph(f"<b>{label}</b>", ParagraphStyle('BadgeText', fontName='Helvetica-Bold', fontSize=8, textColor=txt_color, alignment=1))]], colWidths=[120])
            badge.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), bg_color),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 4),
            ]))
            
            elig_data_table.append([
                Paragraph(f"<b>{loan_type}</b>", table_cell_style),
                badge,
                Paragraph(reason_val, table_cell_style)
            ])
            
        t2 = Table(elig_data_table, colWidths=[110, 130, 264])
        t2.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), NAVY),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 0.5, HexColor("#d0d0d0")),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, LIGHT_GREY]),
        ]))
        story.append(t2)
        story.append(PageBreak())
        
        # ==========================================
        # PAGE 3: LOAN PRODUCT COMPARISON
        # ==========================================
        story.append(Paragraph("3. Side-by-Side Cost Comparison Table", section_style))
        story.append(Paragraph("Below is a quantitative comparison of all eligible loan products from our catalog. Monthly EMIs and total costs are calculated using standard amortization formulas.", body_style))
        story.append(Spacer(1, 10))
        
        comp_headers = [
            Paragraph("Bank & Product", table_header_style),
            Paragraph("Int. Rate", table_header_style),
            Paragraph("Tenure", table_header_style),
            Paragraph("Monthly EMI", table_header_style),
            Paragraph("Processing Fee", table_header_style),
            Paragraph("Total Cost", table_header_style),
            Paragraph("Afford. Score", table_header_style)
        ]
        comp_data_table = [comp_headers]
        
        for item in comparisons.get("comparisons", []):
            comp_data_table.append([
                Paragraph(f"<b>{item.get('bank_name')}</b><br/>{item.get('loan_id')}", table_cell_style),
                Paragraph(f"{item.get('interest_rate_used')}%", table_cell_style),
                Paragraph(f"{item.get('tenure_months')} M", table_cell_style),
                Paragraph(f"INR {item.get('monthly_emi', 0):,.2f}", table_cell_style),
                Paragraph(f"INR {item.get('processing_fee_amount', 0):,.2f}", table_cell_style),
                Paragraph(f"INR {item.get('total_amount_payable', 0):,.2f}", table_cell_style),
                Paragraph(f"<b>{item.get('affordability_score')}/100</b>", table_cell_style)
            ])
            
        t3 = Table(comp_data_table, colWidths=[104, 55, 45, 80, 80, 90, 50])
        t3.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), NAVY),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 0.5, HexColor("#d0d0d0")),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, LIGHT_GREY]),
        ]))
        story.append(t3)
        story.append(PageBreak())
        
        # ==========================================
        # PAGE 4: TOP 3 RECOMMENDATIONS
        # ==========================================
        story.append(Paragraph("4. Recommended Loan Options", section_style))
        story.append(Paragraph("Our financial planning advisor agent selected the following top recommendations based on overall cost, approval probability, and matching criteria.", body_style))
        story.append(Spacer(1, 10))
        
        for rec in recommendations.get("recommendations", []):
            rec_num = rec.get("rank", 1)
            loan_id = rec.get("loan_id")
            
            # Find matching comparison
            comp = {}
            for c in comparisons.get("comparisons", []):
                if c.get("loan_id") == loan_id:
                    comp = c
                    break
                    
            emi_val = f"INR {comp.get('monthly_emi', 0):,.2f}" if comp.get("monthly_emi") else "N/A"
            rate_val = f"{comp.get('interest_rate_used')}%" if comp.get("interest_rate_used") else "N/A"
            cost_val = f"INR {comp.get('total_amount_payable', 0):,.2f}" if comp.get("total_amount_payable") else "N/A"
            aff_val = f"{comp.get('affordability_score')}/100" if comp.get("affordability_score") is not None else "N/A"
            
            rec_box = []
            choice_labels = {1: "1st Choice", 2: "2nd Choice", 3: "3rd Choice"}
            choice_str = choice_labels.get(rec_num, f"{rec_num}th Choice")
            
            rec_box.append(Paragraph(f"<b>{choice_str}: {rec.get('bank_name')} ({rec.get('loan_type', 'Loan')})</b>", rec_card_title_style))
            rec_box.append(Paragraph(f"<b>Loan Product ID:</b> {loan_id} | <b>Suitability Match: {rec.get('suitability_score')}/100</b>", bold_body_style))
            
            # Financial details row
            fin_details = f"<b>Interest Rate:</b> {rate_val} | <b>Monthly EMI:</b> {emi_val} | <b>Total Cost:</b> {cost_val} | <b>Affordability:</b> {aff_val}"
            rec_box.append(Paragraph(fin_details, body_style))
            
            # Why recommended (AI explanation)
            rec_box.append(Paragraph(f"<b>Why Recommended:</b> {rec.get('why_suits')}", body_style))
            
            # Advantages
            advs = "<br/>".join([f"&bull; {adv}" for adv in rec.get("advantages", [])])
            rec_box.append(Paragraph(f"<b>Key Advantages:</b><br/>{advs}", body_style))
            
            # Risks
            rsks = "<br/>".join([f"&bull; {rsk}" for rsk in rec.get("risks", [])])
            rec_box.append(Paragraph(f"<b>Important Considerations / Risks:</b><br/>{rsks}", body_style))
            
            rec_box.append(Paragraph(f"<b>Suggested Tenure:</b> {rec.get('suggested_tenure')}", body_style))
            rec_box.append(Paragraph(f"<b>Negotiation Tip:</b> {rec.get('negotiation_tip')}", body_style))
            rec_box.append(Spacer(1, 10))
            
            tb_rec = Table([[rec_box]], colWidths=[504])
            tb_rec.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), LIGHT_GREY),
                ('BOX', (0,0), (-1,-1), 1, NAVY if rec_num == 1 else HexColor("#cccccc")),
                ('TOPPADDING', (0,0), (-1,-1), 10),
                ('BOTTOMPADDING', (0,0), (-1,-1), 10),
                ('LEFTPADDING', (0,0), (-1,-1), 12),
                ('RIGHTPADDING', (0,0), (-1,-1), 12),
            ]))
            
            story.append(tb_rec)
            story.append(Spacer(1, 15))
            
        story.append(PageBreak())
        
        # ==========================================
        # PAGE 5: PERSONALIZED FINANCIAL TIPS
        # ==========================================
        story.append(Paragraph("5. Personalized Credit & Financial Advice", section_style))
        story.append(Paragraph("To improve your borrowing eligibility, score higher with lenders, and secure the lowest rates on future credits, follow these structured guidelines:", body_style))
        story.append(Spacer(1, 15))
        
        for i, tip in enumerate(tips, 1):
            story.append(Paragraph(f"<b>Tip {i}: {tip.get('title', 'Financial Advice')}</b>", bold_body_style))
            story.append(Paragraph(tip.get('description', 'N/A'), body_style))
            story.append(Spacer(1, 10))
            
        # Build Document
        doc.build(story, canvasmaker=NumberedCanvas)
        logger.info(f"PDF report built successfully at: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to generate PDF report: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
