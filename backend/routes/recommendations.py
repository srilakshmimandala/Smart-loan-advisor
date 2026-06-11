import os
import json
from flask import Blueprint, request, jsonify, send_file
from database import get_recommendations, get_customer_profile, get_all_loan_products
from crew_main import run_loan_advisory_pipeline
from utils.logger import get_logger
from utils.emi_calculator import calculate_emi, calculate_total_interest, calculate_affordability_ratio
from utils.llm_client import get_raw_gemini_model

logger = get_logger("RecommendationsRoutes")
recommendations_bp = Blueprint("recommendations", __name__)

@recommendations_bp.route("/run-pipeline", methods=["POST"])
def run_pipeline():
    """
    Triggers the sequential CrewAI pipeline for a submitted customer.
    """
    try:
        data = request.json
        if not data or "customer_id" not in data:
            return jsonify({"status": "error", "message": "customer_id is required."}), 400
            
        customer_id = int(data["customer_id"])
        profile = get_customer_profile(customer_id)
        if not profile:
            return jsonify({"status": "error", "message": "Customer profile not found in database."}), 404
            
        # Run sequential CrewAI pipeline
        try:
            result = run_loan_advisory_pipeline(profile, customer_id=customer_id)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        
        if result.get("status") == "success":
            try:
                recs = result.get("recommendations", {})
                comps = result.get("comparisons", {})
                elig = result.get("eligibility", {})
                
                # Check if recommendations list is empty
                rec_list = recs.get("recommendations", []) if isinstance(recs, dict) else []
                if not rec_list:
                    logger.info("Recommendations empty in run-pipeline. Falling back to comparison top 3...")
                    comp_list = comps.get("comparisons", []) if isinstance(comps, dict) else []
                    sorted_comps = sorted(comp_list, key=lambda x: x.get("affordability_score", 0), reverse=True)
                    fallback_recs = []
                    for idx, comp in enumerate(sorted_comps[:3], 1):
                        loan_id = comp.get("loan_id")
                        bank_name = comp.get("bank_name")
                        loan_type = comp.get("loan_type", profile.get("loan_purpose", "Personal") + " Loan")
                        rate = comp.get("interest_rate_used")
                        emi = comp.get("monthly_emi")
                        score = comp.get("affordability_score")
                        
                        fallback_recs.append({
                            "rank": idx,
                            "loan_id": loan_id,
                            "bank_name": bank_name,
                            "loan_type": loan_type,
                            "suitability_score": int(score or 80),
                            "why_suits": f"Recommended based on highest affordability score of {score} and rate of {rate}%.",
                            "advantages": [
                                f"Competitive interest rate of {rate}%",
                                f"Monthly EMI of INR {emi:,.2f}"
                            ],
                            "risks": [
                                "Prepayment penalties may apply."
                            ],
                            "suggested_tenure": f"{comp.get('tenure_months')} months",
                            "negotiation_tip": f"Request processing fee waiver based on credit score of {profile.get('credit_score')}."
                        })
                    recs = {"recommendations": fallback_recs}
                
                return jsonify({
                    "status": "success",
                    "message": "CrewAI pipeline completed successfully.",
                    "customer_id": customer_id,
                    "recommendations": recs,
                    "comparisons": comps,
                    "eligibility": elig
                }), 200
            except Exception as assemble_err:
                logger.error(f"Failed to assemble pipeline output JSON: {str(assemble_err)}")
                return jsonify({
                    "status": "error",
                    "message": f"Pipeline completed but output serialization failed: {str(assemble_err)}"
                }), 500
        else:
            return jsonify({"status": "error", "message": result.get("message")}), 500
            
    except Exception as e:
        logger.error(f"Error running pipeline route: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@recommendations_bp.route("/recommendations/<int:customer_id>", methods=["GET"])
def get_customer_recommendations(customer_id):
    """
    Retrieves existing recommendations for a customer.
    """
    try:
        customer = get_customer_profile(customer_id)
        if not customer:
            return jsonify({"status": "error", "message": "Customer profile not found."}), 404
            
        data = get_recommendations(customer_id)
        needs_generation = False
        if not data:
            needs_generation = True
        else:
            rec_data = data.get("recommendation_data")
            if not rec_data or not isinstance(rec_data, dict) or not rec_data.get("recommendations"):
                needs_generation = True
                
        if needs_generation:
            from crew_main import generate_recommendation_details, run_loan_advisory_pipeline
            from database import save_recommendations
            
            comparison_data = data.get("comparison_data") if data else {}
            eligibility_data = data.get("eligibility_data") if data else {}
            comparisons_list = comparison_data.get("comparisons", []) if isinstance(comparison_data, dict) else []
            
            if not comparisons_list:
                logger.info(f"No comparison data found for customer {customer_id}. Running full pipeline...")
                run_res = run_loan_advisory_pipeline(customer, customer_id=customer_id)
                if run_res.get("status") == "success":
                    data = get_recommendations(customer_id)
                else:
                    return jsonify({"status": "error", "message": f"Failed to generate recommendations dynamically: {run_res.get('message')}"}), 500
            else:
                logger.info(f"Generating recommendations dynamically for customer {customer_id}...")
                recommendation_data = generate_recommendation_details(customer, comparisons_list)
                save_recommendations(
                    customer_id=customer_id,
                    recommendation_data=recommendation_data,
                    comparison_data=comparison_data,
                    eligibility_data=eligibility_data
                )
                data = get_recommendations(customer_id)
                
        # If recommendations list is still empty, fall back to using top 3 from comparison data sorted by affordability score
        rec_data = data.get("recommendation_data") if data else {}
        rec_list = rec_data.get("recommendations", []) if isinstance(rec_data, dict) else []
        
        if not rec_list and data:
            logger.info(f"Recommendations list empty for customer {customer_id} on GET. Falling back to comparison top 3...")
            comp_data = data.get("comparison_data") or {}
            comp_list = comp_data.get("comparisons", []) if isinstance(comp_data, dict) else []
            if comp_list:
                sorted_comps = sorted(comp_list, key=lambda x: x.get("affordability_score", 0), reverse=True)
                fallback_recs = []
                for idx, comp in enumerate(sorted_comps[:3], 1):
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
                        "why_suits": f"Recommended based on highest affordability score of {score} and rate of {rate}%.",
                        "advantages": [
                            f"Competitive interest rate of {rate}%",
                            f"Monthly EMI of INR {emi:,.2f}"
                        ],
                        "risks": [
                            "Prepayment penalties may apply."
                        ],
                        "suggested_tenure": f"{comp.get('tenure_months')} months",
                        "negotiation_tip": f"Request processing fee waiver based on credit score of {customer.get('credit_score')}."
                    })
                data["recommendation_data"] = {"recommendations": fallback_recs}
                # Save it back to DB so it persists
                from database import save_recommendations
                save_recommendations(
                    customer_id=customer_id,
                    recommendation_data=data["recommendation_data"],
                    comparison_data=comp_data,
                    eligibility_data=data.get("eligibility_data") or {}
                )
                
        return jsonify({
            "status": "success", 
            "recommendations": data["recommendation_data"] if data else {"recommendations": []},
            "eligibility": data["eligibility_data"] if data else {}
        }), 200
    except Exception as e:
        logger.error(f"Error fetching recommendations: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@recommendations_bp.route("/comparison/<int:customer_id>", methods=["GET"])
def get_customer_comparison(customer_id):
    """
    Retrieves existing loan comparisons for a customer.
    """
    try:
        data = get_recommendations(customer_id)
        if not data or not data.get("comparison_data") or not data["comparison_data"].get("comparisons"):
            customer = get_customer_profile(customer_id)
            if not customer:
                return jsonify({"status": "error", "message": "Customer profile not found."}), 404
            
            from crew_main import run_loan_advisory_pipeline
            logger.info(f"No comparison data found for customer {customer_id}. Running full pipeline...")
            run_res = run_loan_advisory_pipeline(customer, customer_id=customer_id)
            if run_res.get("status") == "success":
                data = get_recommendations(customer_id)
            else:
                return jsonify({"status": "error", "message": f"Failed to generate comparisons dynamically: {run_res.get('message')}"}), 500
                
        return jsonify({"status": "success", "comparisons": data["comparison_data"]}), 200
    except Exception as e:
        logger.error(f"Error fetching comparisons: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@recommendations_bp.route("/report/<int:customer_id>", methods=["GET"])
def download_report(customer_id):
    """
    Downloads the compiled PDF report for a customer.
    """
    try:
        profile = get_customer_profile(customer_id)
        if not profile:
            return jsonify({"status": "error", "message": "Customer profile not found."}), 404
            
        data = get_recommendations(customer_id)
        needs_generation = False
        if not data:
            needs_generation = True
        else:
            rec_data = data.get("recommendation_data")
            if not rec_data or not isinstance(rec_data, dict) or not rec_data.get("recommendations"):
                needs_generation = True
                
        clean_name = "".join(x for x in profile["name"] if x.isalnum()).lower()
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        pdf_path = None
        if os.path.exists(reports_dir):
            files = [f for f in os.listdir(reports_dir) if f.startswith(f"loan_report_{clean_name}_") and f.endswith(".pdf")]
            if files:
                files.sort(reverse=True)
                pdf_path = os.path.join(reports_dir, files[0])
                
        if needs_generation or not pdf_path or not os.path.exists(pdf_path):
            logger.info(f"Generating PDF/recommendations on the fly for customer {customer_id}...")
            
            if needs_generation:
                from crew_main import generate_recommendation_details, run_loan_advisory_pipeline
                from backend.database import save_recommendations
                
                comparison_data = data.get("comparison_data") if data else {}
                eligibility_data = data.get("eligibility_data") if data else {}
                comparisons_list = comparison_data.get("comparisons", []) if isinstance(comparison_data, dict) else []
                
                if not comparisons_list:
                    run_res = run_loan_advisory_pipeline(profile, customer_id=customer_id)
                    if run_res.get("status") == "success":
                        data = get_recommendations(customer_id)
                        pdf_path = run_res.get("pdf_path")
                    else:
                        return jsonify({"status": "error", "message": f"Failed to run pipeline for PDF generation: {run_res.get('message')}"}), 500
                else:
                    recommendation_data = generate_recommendation_details(profile, comparisons_list)
                    save_recommendations(
                        customer_id=customer_id,
                        recommendation_data=recommendation_data,
                        comparison_data=comparison_data,
                        eligibility_data=eligibility_data
                    )
                    data = get_recommendations(customer_id)
            
            # Recompile/generate PDF if still missing
            if not pdf_path or not os.path.exists(pdf_path):
                from utils.pdf_report import generate_pdf_report
                from datetime import datetime
                
                if not data:
                    data = get_recommendations(customer_id)
                    
                eligibility = data.get("eligibility_data") or {}
                comparisons = data.get("comparison_data") or {}
                recommendations = data.get("recommendation_data") or {}
                
                tips_list = recommendations.get("tips", [])
                if not tips_list:
                    tips_list = [
                        {"title": "Reduce Debt Obligations", "description": "Prioritize paying off existing high-interest debts to lower your Debt-to-Income (DTI) ratio."},
                        {"title": "Monitor Credit Utilization", "description": "Keep your credit card utilization below 30% to maintain and boost your credit score."},
                        {"title": "Maintain On-Time Payments", "description": "Ensure all EMIs and credit card bills are paid on time to avoid negative credit history entries."},
                        {"title": "Build an Emergency Fund", "description": "Establish a savings buffer of 3-6 months' expenses to avoid taking high-interest loans in emergencies."},
                        {"title": "Check Credit Reports", "description": "Regularly review your credit reports to identify and correct any reporting errors promptly."}
                    ]
                
                date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                pdf_path = os.path.join(reports_dir, f"loan_report_{clean_name}_{date_str}.pdf")
                
                pdf_ok = generate_pdf_report(
                    customer=profile,
                    eligibility=eligibility,
                    comparisons=comparisons,
                    recommendations=recommendations,
                    tips=tips_list,
                    output_path=pdf_path
                )
                if not pdf_ok:
                    return jsonify({"status": "error", "message": "Failed to compile PDF report dynamically."}), 500
                    
        if pdf_path and os.path.exists(pdf_path):
            return send_file(pdf_path, as_attachment=True, download_name=f"Confidential_LoanSense_Report_{clean_name}.pdf")
        else:
            return jsonify({"status": "error", "message": "PDF report file not found or could not be generated."}), 404
    except Exception as e:
        logger.error(f"Error sending report PDF: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@recommendations_bp.route("/recommendations/what-if", methods=["POST"])
def what_if_simulator():
    """
    Feature 2: What-If Scenario Simulator.
    Instantly recalculates DTI, EMIs, and product eligibility.
    """
    try:
        data = request.json
        if not data or "customer_id" not in data:
            return jsonify({"status": "error", "message": "customer_id is required."}), 400
            
        customer_id = int(data["customer_id"])
        profile = get_customer_profile(customer_id)
        if not profile:
            return jsonify({"status": "error", "message": "Customer profile not found."}), 404
            
        # Get simulated inputs from request or default to original
        sim_income = float(data.get("sim_monthly_income", profile["monthly_income"]))
        sim_amount = float(data.get("sim_loan_amount", profile["desired_amount"]))
        sim_tenure_years = int(data.get("sim_tenure_years", profile["preferred_tenure"]))
        
        products = get_all_loan_products()
        rules_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "eligibility_rules.json")
        with open(rules_path, 'r', encoding='utf-8') as f:
            rules = json.load(f)
            
        # Recalculate basic DTI
        sim_dti = (profile["existing_emis"] / sim_income) * 100
        
        sim_eligibility = {}
        sim_comparisons = []
        
        for p in products:
            loan_type = p["loan_type"]
            rule = rules.get(loan_type, {})
            
            # Check basic eligibility (Income, Credit, Age, Employment)
            eligible = True
            reasons = []
            
            if sim_income < p["min_monthly_income"]:
                eligible = False
                reasons.append(f"Income INR {sim_income:,.0f} < required INR {p['min_monthly_income']:,.0f}")
            if profile["credit_score"] < p["min_credit_score"]:
                eligible = False
                reasons.append(f"Credit Score {profile['credit_score']} < required {p['min_credit_score']}")
            if profile["age"] < rule.get("min_age", 18) or profile["age"] > rule.get("max_age", 70):
                eligible = False
                reasons.append("Age out of policy limits")
            if profile["employment_type"] not in p["employment_types_eligible"]:
                eligible = False
                reasons.append(f"Employment '{profile['employment_type']}' not eligible")
            if sim_dti > 50:
                eligible = False
                reasons.append(f"Simulated DTI ({sim_dti:.1f}%) exceeds 50% limit")
                
            status = "Eligible" if eligible else "Not Eligible"
            reason = "Meets all simulated criteria." if eligible else "; ".join(reasons)
            
            # Special conditional handling
            if eligible and (sim_dti > 40 or profile["credit_score"] < 680):
                status = "Conditionally Eligible"
                reason = "Meets basic criteria, but DTI or credit score is close to threshold limits."
                
            sim_eligibility[loan_type] = {
                "status": status,
                "reason": reason
            }
            
            if status in ["Eligible", "Conditionally Eligible"]:
                # Calculate new EMI
                interest_rate = p["interest_rate_min"]
                if profile["credit_score"] < 750:
                    interest_rate = (p["interest_rate_min"] + p["interest_rate_max"]) / 2
                if profile["credit_score"] < 650:
                    interest_rate = p["interest_rate_max"]
                    
                tenure_months = min(sim_tenure_years * 12, p["max_tenure_months"])
                
                new_emi = calculate_emi(sim_amount, interest_rate, tenure_months)
                total_interest = calculate_total_interest(sim_amount, new_emi, tenure_months)
                total_payable = sim_amount + total_interest
                processing_fee = sim_amount * (p["processing_fee_percent"] / 100)
                ear = ((1 + interest_rate / 1200) ** 12 - 1) * 100
                
                # Affordability Score
                new_dti = ((profile["existing_emis"] + new_emi) / sim_income) * 100
                aff_score = max(0, min(100, int(100 - (new_dti * 1.5))))
                
                sim_comparisons.append({
                    "loan_id": p["loan_id"],
                    "bank_name": p["bank_name"],
                    "loan_type": p["loan_type"],
                    "interest_rate_used": round(interest_rate, 2),
                    "tenure_months": tenure_months,
                    "monthly_emi": new_emi,
                    "total_interest": total_interest,
                    "total_amount_payable": total_payable,
                    "processing_fee_amount": processing_fee,
                    "effective_annual_rate": round(ear, 2),
                    "affordability_score": aff_score
                })
                
        # Generate simulator advisory text
        advisory_notes = []
        orig_eligible = [p["loan_type"] for p in products if profile["monthly_income"] >= p["min_monthly_income"]]
        sim_eligible = [k for k, v in sim_eligibility.items() if v["status"] in ["Eligible", "Conditionally Eligible"]]
        
        newly_eligible = list(set(sim_eligible) - set(orig_eligible))
        if newly_eligible:
            advisory_notes.append(f"Success! Increasing your income/parameters makes you eligible for: {', '.join(newly_eligible)}.")
        elif len(sim_eligible) < len(orig_eligible):
            advisory_notes.append("Warning: Lowering your simulated parameters has reduced the number of products you qualify for.")
        else:
            advisory_notes.append("No changes in eligible categories, but EMIs, EAR, and affordability scores have been updated.")

        return jsonify({
            "status": "success",
            "dti_ratio": round(sim_dti, 2),
            "eligibility_summary": sim_eligibility,
            "comparisons": sim_comparisons,
            "advisory_text": " ".join(advisory_notes)
        }), 200
        
    except Exception as e:
        logger.error(f"Error in What-If Simulator: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@recommendations_bp.route("/recommendations/improve/<int:customer_id>", methods=["GET"])
def loan_improvement_advisor(customer_id):
    """
    Feature 3: Loan Improvement Advisor.
    Uses Gemini to generate a personalized 3-month action plan.
    """
    try:
        profile = get_customer_profile(customer_id)
        recs = get_recommendations(customer_id)
        if not profile or not recs:
            return jsonify({"status": "error", "message": "Customer recommendations not found."}), 404
            
        eligibility = recs["eligibility_data"]
        
        # Call Gemini to write a customized 3-month action plan
        model = get_raw_gemini_model()
        prompt = f"""
        You are the Loan Improvement Advisor. Analyze this client's details and eligibility:
        
        Client Details:
        - Monthly Income: INR {profile['monthly_income']:,.0f}
        - Existing EMIs: INR {profile['existing_emis']:,.0f}
        - Credit Score: {profile['credit_score']}
        - Desired Amount: INR {profile['desired_amount']:,.0f}
        
        Eligibility Failures / Rejections:
        {json.dumps(eligibility.get('loan_type_eligibility', {}))}
        
        Write a personalized, highly structured 3-month action plan to improve their creditworthiness and loan eligibility.
        Output ONLY a JSON string with the key 'timeline' containing a list of exactly 3 objects (one for each month):
        - month: "Month 1", "Month 2", "Month 3"
        - title: Short title of the action (e.g. "Reduce Credit Card Outstanding")
        - action: Clear description of what the customer should do (under 30 words)
        - impact: How this action helps their profile (e.g. "Lowers DTI from 32% to 22%")
        
        Return ONLY the raw JSON string. Do not include markdown blocks.
        """
        
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
            
        plan = json.loads(text)
        return jsonify({"status": "success", "timeline": plan.get("timeline", [])}), 200
        
    except Exception as e:
        logger.error(f"Error in Loan Improvement Advisor: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
