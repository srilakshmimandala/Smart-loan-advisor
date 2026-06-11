import os
import json
import traceback
import re
import time
from datetime import datetime
from dotenv import load_dotenv
from crewai import Crew, Process

def extract_json_block(text):
    text_str = str(text).strip()
    
    # Try finding the first '{'
    start = text_str.find("{")
    if start == -1:
        return text_str
        
    s = text_str[start:]
    try:
        decoder = json.JSONDecoder()
        obj, end_idx = decoder.raw_decode(s)
        return json.dumps(obj)
    except Exception:
        pass
        
    # Manual matching fallback
    braces_count = 0
    end = -1
    for i, char in enumerate(s):
        if char == "{":
            braces_count += 1
        elif char == "}":
            braces_count -= 1
            if braces_count == 0:
                end = i
                break
    if end != -1:
        return s[:end+1].strip()
        
    return text_str

def safe_parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        # Extract JSON object or array from messy LLM output
        match = re.search(r'\{.*\}|\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {}

# Utility imports
from utils.logger import get_logger, log_agent_action
from utils.llm_client import get_crewai_llm
from backend.database import (
    save_customer_profile,
    save_recommendations,
    save_agent_log,
    get_all_loan_products
)

# Agent imports
from agents.data_collector import get_data_collector_agent, get_data_collector_task
from agents.eligibility_analyzer import get_eligibility_analyzer_agent, get_eligibility_analyzer_task
from agents.loan_comparator import get_loan_comparator_agent, get_loan_comparator_task
from agents.recommendation_engine import get_recommendation_engine_agent, get_recommendation_engine_task
from agents.report_generator import get_report_generator_agent, get_report_generator_task

# Load environment
load_dotenv()
logger = get_logger("CrewMain")

def generate_recommendation_details(customer, comparisons_list):
    """
    Selects the top products from comparisons and uses Groq to generate
    personalized recommendation details with why_suits explanation.
    """
    import json
    from utils.llm_client import get_raw_gemini_model
    
    # Sort comparisons by interest rate ascending (lowest interest rate first)
    sorted_comps = sorted(
        comparisons_list,
        key=lambda x: x.get("interest_rate_used", 99)
    )
    
    # Take top 3
    top_comps = sorted_comps[:3]
    
    # If comparisons list is empty, return a default template
    if not top_comps:
        return {"recommendations": []}
        
    # Prepare selected products description for prompt
    selected_products_info = []
    for idx, comp in enumerate(top_comps, 1):
        selected_products_info.append({
            "rank": idx,
            "loan_id": comp.get("loan_id"),
            "bank_name": comp.get("bank_name"),
            "loan_type": comp.get("loan_type", customer.get("loan_purpose", "Personal") + " Loan"),
            "interest_rate_used": comp.get("interest_rate_used"),
            "monthly_emi": comp.get("monthly_emi"),
            "total_amount_payable": comp.get("total_amount_payable"),
            "affordability_score": comp.get("affordability_score")
        })
        
    model = get_raw_gemini_model()
    prompt = f"""
    You are the Personal Financial Advisor. Analyze this client's details and the top selected loan products:
    
    Client Details:
    - Name: {customer.get('name')}
    - Age: {customer.get('age')}
    - Monthly Income: INR {customer.get('monthly_income'):,.2f}
    - Existing EMIs: INR {customer.get('existing_emis'):,.2f}
    - Credit Score: {customer.get('credit_score')}
    - Desired Loan: {customer.get('loan_purpose')} Loan of INR {customer.get('desired_amount'):,.2f} for {customer.get('preferred_tenure')} years
    
    Selected Loan Products:
    {json.dumps(selected_products_info, indent=2)}
    
    Generate the personalized recommendation advisory details.
    For each selected product, generate:
    1. why_suits: A 2-3 sentence personalized explanation of why this specific loan is recommended for this customer.
    2. advantages: At least 2 key advantages or special features of this product for their situation.
    3. risks: At least 1 potential risk, prepayment penalty, rate hike risk, or caution note.
    4. suggested_tenure: Recommended tenure to balance monthly payment size against overall interest cost (e.g. "36 months").
    5. negotiation_tip: A clear, actionable tip they can use to negotiate better terms based on their profile.
    6. suitability_score: Suitability score (0 to 100) reflecting how well it fits.
    
    Output ONLY a JSON-parsable structure with the key:
    - recommendations: a list of objects containing:
      * rank: integer (from 1 to {len(top_comps)})
      * loan_id: string
      * bank_name: string
      * loan_type: string
      * suitability_score: integer (0-100)
      * why_suits: string (2-3 sentences explanation)
      * advantages: list of strings (at least 2 advantages)
      * risks: list of strings (at least 1 risk)
      * suggested_tenure: string
      * negotiation_tip: string
      
    Return ONLY the raw JSON string. Do not include markdown formatting or blocks.
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # Clean markdown if returned
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
            
        import re
        def safe_parse_json_local(text):
            try:
                return json.loads(text)
            except Exception:
                match = re.search(r'\{.*\}|\[.*\]', text, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group())
                    except Exception:
                        pass
                return {}
                
        plan = safe_parse_json_local(text)
        if "recommendations" in plan and isinstance(plan["recommendations"], list) and len(plan["recommendations"]) > 0:
            return plan
    except Exception as e:
        logger.error(f"Error generating recommendation details from Groq: {str(e)}")
        
    # Programmatic fallback if LLM query fails
    fallback_recs = []
    for idx, comp in enumerate(top_comps, 1):
        loan_id = comp.get("loan_id")
        bank_name = comp.get("bank_name")
        loan_type = comp.get("loan_type", customer.get("loan_purpose", "Personal") + " Loan")
        rate = comp.get("interest_rate_used")
        emi = comp.get("monthly_emi")
        score = comp.get("affordability_score")
        
        fallback_recs.append({
            "rank": idx,
            "loan_id": loan_id,
            "bank_name": bank_name,
            "loan_type": loan_type,
            "suitability_score": int(score or 80),
            "why_suits": f"This loan is recommended because of its competitive interest rate of {rate}% and manageable EMI of INR {emi:,.2f}, which aligns well with {customer.get('name')}'s monthly income of INR {customer.get('monthly_income'):,.2f}.",
            "advantages": [
                f"Competitive interest rate of {rate}%",
                f"Manageable EMI of INR {emi:,.2f} per month"
            ],
            "risks": [
                "Prepayment penalties may apply if paid early"
            ],
            "suggested_tenure": f"{comp.get('tenure_months')} months",
            "negotiation_tip": f"Request processing fee waiver based on credit score of {customer.get('credit_score')}."
        })
    return {"recommendations": fallback_recs}

def run_loan_advisory_pipeline(raw_profile, customer_id=None, pdf_path=None):
    """
    Runs the full sequential CrewAI pipeline for a customer.
    Saves outputs to SQLite database and generates the PDF.
    """
    try:
        logger.info(f"Starting Smart Loan Advisor Pipeline for: {raw_profile.get('name', 'Anonymous')}")
        
        # -------------------------------------------------------------
        # STEP 1: GATHER & VALIDATE DATA (Agent 1)
        # -------------------------------------------------------------
        print("\n=== [Agent 1] Customer Data Collection & Validation ===")
        log_agent_action("DataCollectorAgent", "Intake Validation", "STARTED")
        
        collector_agent = get_data_collector_agent()
        collector_task = get_data_collector_task(collector_agent, json.dumps(raw_profile))
        
        crew_1 = Crew(agents=[collector_agent], tasks=[collector_task], process=Process.sequential)
        collector_output = crew_1.kickoff()
        time.sleep(3)
        
        validated_profile = safe_parse_json(extract_json_block(collector_output))
        
        if not validated_profile.get("valid", True):
            error_msg = validated_profile.get("error_message", "Profile validation failed.")
            log_agent_action("DataCollectorAgent", "Intake Validation", "FAILED", error_msg)
            if customer_id:
                save_agent_log(customer_id, "DataCollectorAgent", "Intake Validation", "FAILED", error_msg)
            return {"status": "error", "message": error_msg}
            
        log_agent_action("DataCollectorAgent", "Intake Validation", "SUCCESS", "Profile validated.")
        
        # Save validated profile to DB if customer_id not provided
        if not customer_id:
            customer_id = save_customer_profile(validated_profile)
            
        save_agent_log(customer_id, "DataCollectorAgent", "Intake Validation", "SUCCESS", "Profile validated and structured.")

        # Load database products and policy rules
        products = get_all_loan_products()
        
        rules_path = os.path.join(os.path.dirname(__file__), "data", "eligibility_rules.json")
        with open(rules_path, 'r', encoding='utf-8') as f:
            rules = json.load(f)

        # -------------------------------------------------------------
        # STEP 2: ELIGIBILITY ANALYSIS (Agent 2)
        # -------------------------------------------------------------
        print("\n=== [Agent 2] Eligibility Rule Verification ===")
        log_agent_action("EligibilityAnalyzerAgent", "Eligibility Check", "STARTED")
        
        analyzer_agent = get_eligibility_analyzer_agent()
        analyzer_task = get_eligibility_analyzer_task(
            analyzer_agent, 
            json.dumps(validated_profile), 
            json.dumps(products), 
            json.dumps(rules)
        )
        
        crew_2 = Crew(agents=[analyzer_agent], tasks=[analyzer_task], process=Process.sequential)
        analyzer_output = crew_2.kickoff()
        time.sleep(3)
        
        eligibility_results = safe_parse_json(extract_json_block(analyzer_output))
        log_agent_action("EligibilityAnalyzerAgent", "Eligibility Check", "SUCCESS", f"Eligible for {len(eligibility_results.get('eligible_products', []))} products.")
        save_agent_log(customer_id, "EligibilityAnalyzerAgent", "Eligibility Check", "SUCCESS", f"Found {len(eligibility_results.get('eligible_products', []))} eligible products.")

        # -------------------------------------------------------------
        # STEP 3: LOAN COST COMPARISON (Agent 3)
        # -------------------------------------------------------------
        print("\n=== [Agent 3] Side-by-Side Cost Comparison ===")
        log_agent_action("LoanComparatorAgent", "Loan Cost Comparison", "STARTED")
        
        comparator_agent = get_loan_comparator_agent()
        comparator_task = get_loan_comparator_task(
            comparator_agent,
            json.dumps(validated_profile),
            json.dumps(eligibility_results.get("eligible_products", [])),
            json.dumps(products)
        )
        
        crew_3 = Crew(agents=[comparator_agent], tasks=[comparator_task], process=Process.sequential)
        comparator_output = crew_3.kickoff()
        time.sleep(3)
        
        comparison_results = safe_parse_json(extract_json_block(comparator_output))
        
        # Fallback if comparator agent output is invalid or empty JSON
        if not comparison_results or not comparison_results.get("comparisons"):
            logger.info("Comparison agent output invalid/empty. Computing comparisons programmatically...")
            comp_list = []
            for p in products:
                if p["loan_id"] in eligibility_results.get("eligible_products", []):
                    # Rate based on credit score
                    interest_rate = p["interest_rate_min"]
                    if validated_profile["credit_score"] < 750:
                        interest_rate = (p["interest_rate_min"] + p["interest_rate_max"]) / 2
                    if validated_profile["credit_score"] < 650:
                        interest_rate = p["interest_rate_max"]
                        
                    tenure_months = min(validated_profile["preferred_tenure"] * 12, p["max_tenure_months"])
                    
                    from utils.emi_calculator import calculate_emi, calculate_total_interest
                    new_emi = calculate_emi(validated_profile["desired_amount"], interest_rate, tenure_months)
                    total_interest = calculate_total_interest(validated_profile["desired_amount"], new_emi, tenure_months)
                    total_payable = validated_profile["desired_amount"] + total_interest
                    processing_fee = validated_profile["desired_amount"] * (p["processing_fee_percent"] / 100)
                    ear = ((1 + interest_rate / 1200) ** 12 - 1) * 100
                    
                    new_dti = ((validated_profile["existing_emis"] + new_emi) / validated_profile["monthly_income"]) * 100
                    aff_score = max(0, min(100, int(100 - (new_dti * 1.5))))
                    
                    comp_list.append({
                        "loan_id": p["loan_id"],
                        "bank_name": p["bank_name"],
                        "interest_rate_used": round(interest_rate, 3),
                        "tenure_months": int(tenure_months),
                        "monthly_emi": round(new_emi, 2),
                        "total_interest": round(total_interest, 2),
                        "total_amount_payable": round(total_payable, 2),
                        "processing_fee_amount": round(processing_fee, 2),
                        "effective_annual_rate": round(ear, 2),
                        "affordability_score": int(aff_score)
                    })
            comp_list = sorted(comp_list, key=lambda x: x["affordability_score"], reverse=True)
            
            lowest_emi_rank = [x["loan_id"] for x in sorted(comp_list, key=lambda x: x["monthly_emi"])]
            lowest_total_cost_rank = [x["loan_id"] for x in sorted(comp_list, key=lambda x: x["total_amount_payable"])]
            best_rate_rank = [x["loan_id"] for x in sorted(comp_list, key=lambda x: x["interest_rate_used"])]
            
            comparison_results = {
                "comparisons": comp_list,
                "rankings": {
                    "lowest_emi": lowest_emi_rank,
                    "lowest_total_cost": lowest_total_cost_rank,
                    "best_rate": best_rate_rank
                }
            }
            
        log_agent_action("LoanComparatorAgent", "Loan Cost Comparison", "SUCCESS", "Comparison calculations complete.")
        save_agent_log(customer_id, "LoanComparatorAgent", "Loan Cost Comparison", "SUCCESS", "Comparison and rankings completed.")

        # Save comparison and eligibility to database immediately in case recommendation fails
        try:
            save_recommendations(
                customer_id=customer_id,
                recommendation_data={"recommendations": []},
                comparison_data=comparison_results,
                eligibility_data=eligibility_results
            )
        except Exception as db_save_err:
            logger.error(f"Failed to save comparison data early: {str(db_save_err)}")

        # -------------------------------------------------------------
        # STEP 4: RECOMMENDATION ENGINE (Agent 4)
        # -------------------------------------------------------------
        print("\n=== [Agent 4] Gemini Personalized Recommendations ===")
        log_agent_action("RecommendationEngineAgent", "Advisory Recommendations", "STARTED")
        
        comparisons_list = comparison_results.get("comparisons", [])
        
        # Try running recommendation engine, with robust fallback
        try:
            recommendation_results = generate_recommendation_details(validated_profile, comparisons_list)
            if not recommendation_results or not recommendation_results.get("recommendations"):
                raise ValueError("Recommendation results list is empty.")
            log_agent_action("RecommendationEngineAgent", "Advisory Recommendations", "SUCCESS", "Top recommendations generated.")
            save_agent_log(customer_id, "RecommendationEngineAgent", "Advisory Recommendations", "SUCCESS", "Personalized recommendations generated.")
        except Exception as rec_err:
            logger.error(f"Recommendation engine failed: {str(rec_err)}. Using programmatic fallback...")
            log_agent_action("RecommendationEngineAgent", "Advisory Recommendations", "FAILED", f"Error: {str(rec_err)}")
            
            # Programmatic fallback using comparisons list directly
            fallback_recs = []
            for idx, comp in enumerate(comparisons_list[:3], 1):
                loan_id = comp.get("loan_id")
                bank_name = comp.get("bank_name")
                loan_type = comp.get("loan_type", validated_profile.get("loan_purpose", "Personal") + " Loan")
                rate = comp.get("interest_rate_used")
                emi = comp.get("monthly_emi")
                score = comp.get("affordability_score")
                
                fallback_recs.append({
                    "rank": idx,
                    "loan_id": loan_id,
                    "bank_name": bank_name,
                    "loan_type": loan_type,
                    "suitability_score": int(score or 80),
                    "why_suits": f"This loan is recommended because of its competitive interest rate of {rate}% and manageable EMI of INR {emi:,.2f}.",
                    "advantages": [
                        f"Competitive interest rate of {rate}%",
                        f"Manageable EMI of INR {emi:,.2f} per month"
                    ],
                    "risks": [
                        "Prepayment penalties may apply if paid early"
                    ],
                    "suggested_tenure": f"{comp.get('tenure_months')} months",
                    "negotiation_tip": f"Request processing fee waiver based on credit score of {validated_profile.get('credit_score')}."
                })
            recommendation_results = {"recommendations": fallback_recs}
            save_agent_log(customer_id, "RecommendationEngineAgent", "Advisory Recommendations", "SUCCESS", "Personalized recommendations generated via fallback.")

        # -------------------------------------------------------------
        # STEP 5: PDF REPORT GENERATION (Agent 5)
        # -------------------------------------------------------------
        print("\n=== [Agent 5] Professional PDF Compilation ===")
        log_agent_action("ReportGeneratorAgent", "PDF Generation", "STARTED")
        
        if not pdf_path:
            clean_name = "".join(x for x in validated_profile.get("name", "client") if x.isalnum()).lower()
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_path = f"reports/loan_report_{clean_name}_{date_str}.pdf"
            
        # Ensure directory
        os.makedirs(os.path.dirname(pdf_path) if os.path.dirname(pdf_path) else ".", exist_ok=True)
        
        # Save recommendations, comparison and eligibility to database first
        save_recommendations(
            customer_id=customer_id,
            recommendation_data=recommendation_results,
            comparison_data=comparison_results,
            eligibility_data=eligibility_results
        )
        
        # Direct generation of PDF report to avoid LLM rate limit delays or hangs
        try:
            from utils.pdf_report import generate_pdf_report
            tips_list = recommendation_results.get("tips", [])
            if not tips_list:
                tips_list = [
                    {"title": "Reduce Debt Obligations", "description": "Prioritize paying off existing high-interest debts to lower your Debt-to-Income (DTI) ratio."},
                    {"title": "Monitor Credit Utilization", "description": "Keep your credit card utilization below 30% to maintain and boost your credit score."},
                    {"title": "Maintain On-Time Payments", "description": "Ensure all EMIs and credit card bills are paid on time to avoid negative credit history entries."},
                    {"title": "Build an Emergency Fund", "description": "Establish a savings buffer of 3-6 months' expenses to avoid taking high-interest loans in emergencies."},
                    {"title": "Check Credit Reports", "description": "Regularly review your credit reports to identify and correct any reporting errors promptly."}
                ]
            
            pdf_ok = generate_pdf_report(
                customer=validated_profile,
                eligibility=eligibility_results,
                comparisons=comparison_results,
                recommendations=recommendation_results,
                tips=tips_list,
                output_path=pdf_path
            )
            if pdf_ok:
                log_agent_action("ReportGeneratorAgent", "PDF Generation", "SUCCESS", f"PDF report built successfully at: {pdf_path}")
                save_agent_log(customer_id, "ReportGeneratorAgent", "PDF Generation", "SUCCESS", f"PDF report built successfully: {pdf_path}")
            else:
                logger.error("generate_pdf_report returned False")
                save_agent_log(customer_id, "ReportGeneratorAgent", "PDF Generation", "FAILED", "PDF generation failed.")
        except Exception as pdf_err:
            logger.error(f"Error calling PDF report generation directly: {str(pdf_err)}")
            save_agent_log(customer_id, "ReportGeneratorAgent", "PDF Generation", "FAILED", str(pdf_err))
        
        return {
            "status": "success",
            "customer_id": customer_id,
            "customer_profile": validated_profile,
            "eligibility": eligibility_results,
            "comparisons": comparison_results,
            "recommendations": recommendation_results,
            "pdf_path": os.path.abspath(pdf_path)
        }
        
    except Exception as e:
        logger.error(f"Pipeline error: {str(e)}")
        logger.error(traceback.format_exc())
        if customer_id:
            save_agent_log(customer_id, "PipelineOrchestrator", "Execution", "FAILED", f"Pipeline error: {str(e)}")
        return {"status": "error", "message": f"Pipeline failure: {str(e)}"}

if __name__ == "__main__":
    # Run end-to-end pipeline test
    from backend.database import init_db
    
    # Initialize DB first
    init_db()
    
    # Test Profile 1: High Income, Excellent Credit -> Premium Housing Loan
    profile_high = {
        "name": "Arjun Sharma",
        "age": 35,
        "city": "Mumbai",
        "employment_type": "Salaried",
        "monthly_income": 120000,
        "existing_emis": 15000,
        "credit_score": 780,
        "loan_purpose": "Home",
        "desired_amount": 5000000,
        "preferred_tenure": 15,
        "has_collateral": True
    }
    
    print("\n" + "="*50)
    print("RUNNING PIPELINE FOR PROFILE 1: HIGH INCOME, EXCELLENT CREDIT")
    print("="*50)
    res_high = run_loan_advisory_pipeline(profile_high, pdf_path="reports/test_arjun_sharma.pdf")
    
    if res_high.get("status") == "success":
        print(f"\nPipeline Successful! Customer ID: {res_high['customer_id']}")
        print(f"PDF Report created at: {res_high['pdf_path']}")
    else:
        print(f"\nPipeline Failed: {res_high.get('message')}")
