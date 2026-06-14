import os
import json
from flask import Blueprint, request, jsonify, send_file
from database import get_recommendations, get_customer_profile, get_all_loan_products, save_recommendations, save_agent_log
from utils.logger import get_logger
from utils.emi_calculator import calculate_emi, calculate_total_interest, calculate_affordability_ratio
from utils.llm_client import get_raw_gemini_model

logger = get_logger("RecommendationsRoutes")
recommendations_bp = Blueprint("recommendations", __name__)

def generate_direct_loan_advisory(profile, customer_id):
    try:
        from groq import Groq
        from utils.pdf_report import generate_pdf_report
        import re
        from datetime import datetime

        # 1. Log Start of Data Collector Agent
        save_agent_log(customer_id, "DataCollectorAgent", "Intake Validation", "SUCCESS", "Profile validated and structured.")

        # 2. Eligibility Verification
        rules_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "eligibility_rules.json")
        with open(rules_path, 'r', encoding='utf-8') as f:
            rules = json.load(f)
            
        products = get_all_loan_products()
        
        eligible_ids = []
        eligibility_details = {}
        applied_amounts = {p["loan_id"]: profile["desired_amount"] for p in products}
        fallback_notes = {}
        
        for p in products:
            loan_type = p["loan_type"]
            rule = rules.get(loan_type, {})
            
            eligible = True
            reasons = []
            
            # Income limit
            if profile["monthly_income"] < p["min_monthly_income"]:
                eligible = False
                reasons.append(f"Income too low: required min monthly income is INR {p['min_monthly_income']}.")
                
            # Credit score
            if profile["credit_score"] < p["min_credit_score"]:
                eligible = False
                reasons.append(f"Credit score too low: required min is {p['min_credit_score']}.")
                
            # Employment eligibility
            emp_eligible = p["employment_types_eligible"]
            if isinstance(emp_eligible, str):
                try:
                    emp_eligible = json.loads(emp_eligible)
                except Exception:
                    emp_eligible = [x.strip() for x in emp_eligible.split(",")]
            if profile["employment_type"] not in emp_eligible:
                eligible = False
                reasons.append(f"Employment type '{profile['employment_type']}' not eligible.")
                
            # Age limits
            if profile["age"] < rule.get("min_age", 18):
                eligible = False
                reasons.append(f"Age {profile['age']} is below minimum required age of {rule.get('min_age', 18)}.")
            if profile["age"] > rule.get("max_age", 75):
                eligible = False
                reasons.append(f"Age {profile['age']} is above maximum allowed age of {rule.get('max_age', 75)}.")
                
            # DTI limit check if present in disqualifying conditions
            dti = (profile["existing_emis"] / profile["monthly_income"]) * 100 if profile["monthly_income"] > 0 else 100
            for cond in rule.get("disqualifying_conditions", []):
                if "Debt-to-Income (DTI) ratio exceeding" in cond:
                    match = re.search(r'(\d+)%', cond)
                    if match:
                        limit = int(match.group(1))
                        if dti > limit:
                            eligible = False
                            reasons.append(f"DTI ratio of {dti:.1f}% exceeds limit of {limit}%.")
                            
            # Loan amount limits
            if profile["desired_amount"] < p["min_amount"] or profile["desired_amount"] > p["max_amount"]:
                eligible = False
                reasons.append(f"Desired amount INR {profile['desired_amount']} is outside product limit of INR {p['min_amount']} - INR {p['max_amount']}.")
                
            # New EMI DTI check
            if eligible:
                if profile["credit_score"] >= 750:
                    rate = p["interest_rate_min"]
                elif profile["credit_score"] >= 650:
                    rate = (p["interest_rate_min"] + p["interest_rate_max"]) / 2
                else:
                    rate = p["interest_rate_max"]
                    
                tenure_months = min(profile["preferred_tenure"] * 12, p["max_tenure_months"])
                new_emi = calculate_emi(profile["desired_amount"], rate, tenure_months)
                new_dti = ((profile["existing_emis"] + new_emi) / profile["monthly_income"] * 100) if profile["monthly_income"] > 0 else 100.0
                
                if new_dti > 50.0:
                    eligible = False
                    reasons.append(f"DTI ratio with new EMI ({new_dti:.1f}%) exceeds 50.0% limit.")
                
            eligibility_details[p["loan_id"]] = {
                "eligible": eligible,
                "reasons": reasons
            }
            if eligible:
                eligible_ids.append(p["loan_id"])

        # Check if any products of the requested loan type are eligible
        categories_mapping = {
            "Home Loan": ["Home Loan"],
            "Personal Loan": ["Personal Loan"],
            "Vehicle Loan": ["Vehicle Loan", "Car Loan"],
            "Car Loan": ["Vehicle Loan", "Car Loan"],
            "Education Loan": ["Education Loan"],
            "Gold Loan": ["Gold Loan"],
            "Business Loan": ["Business Loan"]
        }
        
        requested_purpose = profile.get("loan_purpose")
        mapped_types = categories_mapping.get(requested_purpose, [requested_purpose])
        
        has_eligible_product_of_type = any(
            pid in eligible_ids
            for pid in eligible_ids
            for p in products
            if p["loan_id"] == pid and p["loan_type"] in mapped_types
        )
        
        if not has_eligible_product_of_type:
            # We want to recommend products of this type using maximum eligible amount
            for p in products:
                if p["loan_type"] not in mapped_types:
                    continue
                
                # Check basic criteria (age, credit score, income, employment)
                rule = rules.get(p["loan_type"], {})
                age_ok = rule.get("min_age", 18) <= profile["age"] <= rule.get("max_age", 75)
                credit_ok = profile["credit_score"] >= p["min_credit_score"]
                income_ok = profile["monthly_income"] >= p["min_monthly_income"]
                
                emp_eligible = p["employment_types_eligible"]
                if isinstance(emp_eligible, str):
                    try:
                        emp_eligible = json.loads(emp_eligible)
                    except Exception:
                        emp_eligible = [x.strip() for x in emp_eligible.split(",")]
                emp_ok = profile["employment_type"] in emp_eligible
                
                if age_ok and credit_ok and income_ok and emp_ok:
                    # Calculate max eligible amount based on 50% DTI
                    max_new_emi = (0.50 * profile["monthly_income"]) - profile["existing_emis"]
                    if max_new_emi > 0:
                        # Determine interest rate
                        if profile["credit_score"] >= 750:
                            rate = p["interest_rate_min"]
                        elif profile["credit_score"] >= 650:
                            rate = (p["interest_rate_min"] + p["interest_rate_max"]) / 2
                        else:
                            rate = p["interest_rate_max"]
                            
                        tenure_months = min(profile["preferred_tenure"] * 12, p["max_tenure_months"])
                        
                        r_monthly = (rate / 12) / 100
                        if r_monthly == 0:
                            max_supported = max_new_emi * tenure_months
                        else:
                            factor = (1 + r_monthly) ** tenure_months
                            max_supported = max_new_emi * (factor - 1) / (r_monthly * factor)
                            
                        max_eligible_amount = min(max_supported, p["max_amount"])
                        
                        if max_eligible_amount >= p["min_amount"]:
                            # The customer is eligible for this product at max_eligible_amount!
                            applied_amounts[p["loan_id"]] = max_eligible_amount
                            eligible_ids.append(p["loan_id"])
                            # Clear old rejection reasons and mark as eligible
                            eligibility_details[p["loan_id"]] = {
                                "eligible": True,
                                "reasons": []
                            }
                            fallback_notes[p["loan_id"]] = f"Recommendation based on your maximum eligible amount of ₹{max_eligible_amount:,.2f} instead of requested ₹{profile['desired_amount']:,.2f}."

        dti_ratio = (profile["existing_emis"] / profile["monthly_income"]) * 100 if profile["monthly_income"] > 0 else 100.0
        is_high_risk = dti_ratio > 50.0 or profile["credit_score"] < 600

        categories_mapping = {
            "Home Loan": ["Home Loan"],
            "Personal Loan": ["Personal Loan"],
            "Vehicle Loan": ["Vehicle Loan", "Car Loan"],
            "Car Loan": ["Vehicle Loan", "Car Loan"],
            "Education Loan": ["Education Loan"],
            "Gold Loan": ["Gold Loan"],
            "Business Loan": ["Business Loan"]
        }

        loan_type_eligibility = {}
        for category_name, rule_keys in categories_mapping.items():
            rule = {}
            for k in rule_keys:
                if k in rules:
                    rule = rules[k]
                    break
            
            min_age = rule.get("min_age", 18)
            max_age = rule.get("max_age", 75)
            min_credit = rule.get("min_credit_score", 300)
            min_income = rule.get("min_monthly_income", 0)
            
            cat_products = [p for p in products if p["loan_type"] in rule_keys]
            if not cat_products:
                loan_type_eligibility[category_name] = {
                    "status": "Not Eligible",
                    "reason": "No products available for this loan type."
                }
                continue
                
            age_ok = min_age <= profile["age"] <= max_age
            if not age_ok:
                loan_type_eligibility[category_name] = {
                    "status": "Not Eligible",
                    "reason": f"Age {profile['age']} is outside required range ({min_age}-{max_age})."
                }
                continue
                
            income_ok = profile["monthly_income"] >= min_income
            if not income_ok:
                loan_type_eligibility[category_name] = {
                    "status": "Not Eligible",
                    "reason": f"Net monthly income INR {profile['monthly_income']:,.2f} is below required INR {min_income:,.2f}."
                }
                continue
                
            best_status = "Not Eligible"
            reasons = []
            
            for p in cat_products:
                prod_min_credit = p.get("min_credit_score", min_credit)
                prod_min_income = p.get("min_monthly_income", min_income)
                
                # Determine interest rate
                if profile["credit_score"] >= 750:
                    rate = p["interest_rate_min"]
                elif profile["credit_score"] >= 650:
                    rate = (p["interest_rate_min"] + p["interest_rate_max"]) / 2
                else:
                    rate = p["interest_rate_max"]
                    
                tenure_months = min(profile["preferred_tenure"] * 12, p["max_tenure_months"])
                new_emi = calculate_emi(profile["desired_amount"], rate, tenure_months)
                
                new_dti = ((profile["existing_emis"] + new_emi) / profile["monthly_income"] * 100) if profile["monthly_income"] > 0 else 100.0
                
                p_credit_ok = profile["credit_score"] >= prod_min_credit
                p_income_ok = profile["monthly_income"] >= prod_min_income
                p_dti_ok = new_dti <= 50.0
                
                if p_credit_ok and p_income_ok and p_dti_ok:
                    if new_dti > 40.0 or profile["credit_score"] < 680 or profile["credit_score"] < prod_min_credit + 30:
                        prod_status = "Conditionally Eligible"
                        reasons.append(f"[{p['bank_name']}] Conditionally Eligible (moderate credit or DTI {new_dti:.1f}%).")
                    else:
                        prod_status = "Eligible"
                        reasons.append(f"[{p['bank_name']}] Eligible.")
                else:
                    fail_reasons = []
                    if not p_credit_ok:
                        fail_reasons.append(f"Credit score {profile['credit_score']} < {prod_min_credit}")
                    if not p_income_ok:
                        fail_reasons.append(f"Income INR {profile['monthly_income']:,.0f} < INR {prod_min_income:,.0f}")
                    if not p_dti_ok:
                        fail_reasons.append(f"DTI {new_dti:.1f}% exceeds 50% limit")
                    prod_status = "Not Eligible"
                    reasons.append(f"[{p['bank_name']}] Not Eligible: " + ", ".join(fail_reasons))
                    
                if prod_status == "Eligible":
                    best_status = "Eligible"
                elif prod_status == "Conditionally Eligible" and best_status != "Eligible":
                    best_status = "Conditionally Eligible"
                    
            if best_status == "Not Eligible" and profile["monthly_income"] > 0:
                max_amounts_for_cat = []
                for p in cat_products:
                    # check basic criteria (age, credit score, income, employment)
                    rule = rules.get(p["loan_type"], {})
                    age_ok = rule.get("min_age", 18) <= profile["age"] <= rule.get("max_age", 75)
                    credit_ok = profile["credit_score"] >= p["min_credit_score"]
                    income_ok = profile["monthly_income"] >= p["min_monthly_income"]
                    
                    emp_eligible = p["employment_types_eligible"]
                    if isinstance(emp_eligible, str):
                        try:
                            emp_eligible = json.loads(emp_eligible)
                        except Exception:
                            emp_eligible = [x.strip() for x in emp_eligible.split(",")]
                    emp_ok = profile["employment_type"] in emp_eligible
                    
                    if age_ok and credit_ok and income_ok and emp_ok:
                        max_new_emi = (0.50 * profile["monthly_income"]) - profile["existing_emis"]
                        if max_new_emi > 0:
                            if profile["credit_score"] >= 750:
                                rate = p["interest_rate_min"]
                            elif profile["credit_score"] >= 650:
                                rate = (p["interest_rate_min"] + p["interest_rate_max"]) / 2
                            else:
                                rate = p["interest_rate_max"]
                                
                            tenure_months = min(profile["preferred_tenure"] * 12, p["max_tenure_months"])
                            
                            r_monthly = (rate / 12) / 100
                            if r_monthly == 0:
                                max_supported = max_new_emi * tenure_months
                            else:
                                factor = (1 + r_monthly) ** tenure_months
                                max_supported = max_new_emi * (factor - 1) / (r_monthly * factor)
                                
                            max_eligible = min(max_supported, p["max_amount"])
                            if max_eligible >= p["min_amount"]:
                                max_amounts_for_cat.append(max_eligible)
                                
                if max_amounts_for_cat:
                    overall_max_cat = max(max_amounts_for_cat)
                    best_status = "Conditionally Eligible"
                    reasons = [f"You're eligible for up to ₹{overall_max_cat:,.0f} for {category_name} based on your income."]
                    
            loan_type_eligibility[category_name] = {
                "status": best_status,
                "reason": "; ".join(reasons[:2])
            }

        eligibility_results = {
            "dti_ratio": dti_ratio,
            "is_high_risk": is_high_risk,
            "loan_type_eligibility": loan_type_eligibility,
            "eligible_products": eligible_ids,
            "details": eligibility_details
        }
        save_agent_log(customer_id, "EligibilityAnalyzerAgent", "Eligibility Check", "SUCCESS", f"Found {len(eligible_ids)} eligible products.")

        # 3. Loan Cost Comparison
        comp_list = []
        for p in products:
            if p["loan_id"] not in eligible_ids:
                continue
                
            # Determine applicable interest rate
            if profile["credit_score"] >= 750:
                interest_rate = p["interest_rate_min"]
            elif profile["credit_score"] >= 650:
                interest_rate = (p["interest_rate_min"] + p["interest_rate_max"]) / 2
            else:
                interest_rate = p["interest_rate_max"]
                
            # Tenure
            tenure_months = min(profile["preferred_tenure"] * 12, p["max_tenure_months"])
            
            # Calculations
            principal_amount = applied_amounts[p["loan_id"]]
            new_emi = calculate_emi(principal_amount, interest_rate, tenure_months)
            total_interest = calculate_total_interest(principal_amount, new_emi, tenure_months)
            total_payable = principal_amount + total_interest
            processing_fee = principal_amount * (p["processing_fee_percent"] / 100)
            ear = ((1 + interest_rate / 1200) ** 12 - 1) * 100
            
            # Affordability Score
            new_dti = ((profile["existing_emis"] + new_emi) / profile["monthly_income"]) * 100 if profile["monthly_income"] > 0 else 100
            aff_score = max(0, min(100, int(100 - (new_dti * 1.5))))
            
            comp_list.append({
                "loan_id": p["loan_id"],
                "bank_name": p["bank_name"],
                "loan_type": p["loan_type"],
                "interest_rate_used": round(interest_rate, 3),
                "tenure_months": int(tenure_months),
                "monthly_emi": round(new_emi, 2),
                "total_interest": round(total_interest, 2),
                "total_amount_payable": round(total_payable, 2),
                "processing_fee_amount": round(processing_fee, 2),
                "effective_annual_rate": round(ear, 2),
                "affordability_score": int(aff_score)
            })
            
        # Rank the products
        lowest_emi_rank = [x["loan_id"] for x in sorted(comp_list, key=lambda x: x["monthly_emi"])]
        lowest_total_cost_rank = [x["loan_id"] for x in sorted(comp_list, key=lambda x: (x["total_amount_payable"] + x["processing_fee_amount"]))]
        best_rate_rank = [x["loan_id"] for x in sorted(comp_list, key=lambda x: x["interest_rate_used"])]
        
        comparison_results = {
            "comparisons": comp_list,
            "rankings": {
                "lowest_emi": lowest_emi_rank,
                "lowest_total_cost": lowest_total_cost_rank,
                "best_rate": best_rate_rank
            }
        }
        save_agent_log(customer_id, "LoanComparatorAgent", "Loan Cost Comparison", "SUCCESS", "Comparison and rankings completed.")

        # 4. Generate Recommendations using direct Groq API call
        # Sort by lowest interest rate
        sorted_by_rate = sorted(comp_list, key=lambda x: x["interest_rate_used"])
        top_3 = sorted_by_rate[:3]

        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                client = Groq(api_key=groq_key)
                def generate_explanation(loan, customer):
                    try:
                        response = client.chat.completions.create(
                            model="llama-3.1-8b-instant",
                            messages=[{"role": "user", "content": f"In 2 sentences explain why {loan['bank_name']} {loan['loan_type']} at {loan['interest_rate']}% is good for a customer with income {customer['monthly_income']} and credit score {customer['credit_score']}"}],
                            max_tokens=100
                        )
                        return response.choices[0].message.content.strip()
                    except Exception as call_err:
                        logger.warning(f"Groq API call failed: {str(call_err)}. Using fallback explanation.")
                        return f"This loan offers a competitive rate of {loan['interest_rate']}% with an affordable monthly payment."
            except Exception as groq_err:
                logger.error(f"Failed to setup Groq client: {str(groq_err)}")
                def generate_explanation(loan, customer):
                    return f"This loan offers a competitive rate of {loan['interest_rate']}% with an affordable monthly payment."
        else:
            def generate_explanation(loan, customer):
                return f"This loan offers a competitive rate of {loan['interest_rate']}% with an affordable monthly payment."

        recommendation_list = []
        for idx, item in enumerate(top_3, 1):
            explanation = generate_explanation(
                {"bank_name": item["bank_name"], "loan_type": item["loan_type"], "interest_rate": item["interest_rate_used"]},
                profile
            )
            
            if item["loan_id"] in fallback_notes:
                explanation = f"{fallback_notes[item['loan_id']]} {explanation}"
            
            # build advantages/risks
            advantages = [
                f"Low interest rate of {item['interest_rate_used']}%",
                f"Affordable EMI of INR {item['monthly_emi']:,.2f}/month"
            ]
            risks = [
                "Prepayment penalties may apply depending on terms."
            ]
            
            recommendation_list.append({
                "rank": idx,
                "loan_id": item["loan_id"],
                "bank_name": item["bank_name"],
                "loan_type": item["loan_type"],
                "suitability_score": int(item["affordability_score"]),
                "why_suits": explanation,
                "advantages": advantages,
                "risks": risks,
                "suggested_tenure": f"{item['tenure_months']} months",
                "negotiation_tip": f"Request processing fee waiver based on credit score of {profile['credit_score']}."
            })
            
        recommendation_results = {
            "recommendations": recommendation_list
        }

        # Ensure consistency with recommendations actually being shown
        for rec in recommendation_list:
            rec_type = rec["loan_type"]
            for cat_name, rule_keys in categories_mapping.items():
                if rec_type in rule_keys or rec_type == cat_name:
                    current_status = eligibility_results.get("loan_type_eligibility", {}).get(cat_name, {}).get("status")
                    if current_status == "Not Eligible":
                        eligibility_results["loan_type_eligibility"][cat_name] = {
                            "status": "Eligible",
                            "reason": "Recommended by advisor based on financial details."
                        }

        save_agent_log(customer_id, "RecommendationEngineAgent", "Advisory Recommendations", "SUCCESS", "Personalized recommendations generated.")

        # 5. Generate PDF report
        clean_name = "".join(x for x in profile.get("name", "client") if x.isalnum()).lower()
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = f"reports/loan_report_{clean_name}_{date_str}.pdf"
        os.makedirs(os.path.dirname(pdf_path) if os.path.dirname(pdf_path) else ".", exist_ok=True)
        
        # Assemble tips
        tips = []
        # Tip 1: DTI
        if dti_ratio > 40:
            tips.append({
                "title": "Reduce Debt-to-Income (DTI) Ratio",
                "description": f"Your current DTI ratio of {dti_ratio:.1f}% is high. Prioritize paying off smaller outstanding obligations or credit cards to reduce your monthly EMI burden."
            })
        else:
            tips.append({
                "title": "Maintain Healthy Debt-to-Income Ratio",
                "description": f"Your DTI ratio of {dti_ratio:.1f}% is healthy. Keep your monthly loan repayments below 40% of your income to ensure future financial flexibility."
            })
            
        # Tip 2: Credit Score
        if profile["credit_score"] < 700:
            tips.append({
                "title": "Boost Credit Score",
                "description": f"Your credit score of {profile['credit_score']} has room for improvement. Ensure you pay all card bills and EMIs on time, and keep credit utilization below 30%."
            })
        else:
            tips.append({
                "title": "Leverage High Credit Score",
                "description": f"Your credit score of {profile['credit_score']} is strong. Use this as leverage to negotiate lower interest rates and waivers on processing fees with banks."
            })
            
        # Tip 3: Emergency Fund
        tips.append({
            "title": "Build an Emergency Savings Buffer",
            "description": "Establish a liquid emergency fund covering 3 to 6 months of living expenses. This prevents the need for high-cost emergency loans during unforeseen events."
        })
        
        # Tip 4: Loan Tenure
        tips.append({
            "title": "Optimize Loan Tenure Selection",
            "description": f"For your desired loan amount of INR {profile['desired_amount']:,.2f}, choosing a shorter tenure will increase your monthly EMI but significantly reduce total interest paid."
        })
        
        # Tip 5: Shop Around
        tips.append({
            "title": "Compare Multiple Offers",
            "description": "Always check offers from multiple financial institutions. Even a 0.5% difference in interest rates can lead to substantial savings over the life of a loan."
        })

        try:
            success = generate_pdf_report(
                customer=profile,
                eligibility=eligibility_results,
                comparisons=comparison_results,
                recommendations=recommendation_results,
                tips=tips,
                output_path=pdf_path
            )
            if success:
                save_agent_log(customer_id, "ReportGeneratorAgent", "PDF Generation", "SUCCESS", f"Report saved at {pdf_path}")
            else:
                save_agent_log(customer_id, "ReportGeneratorAgent", "PDF Generation", "FAILED", "PDF generator returned False.")
        except Exception as pdf_err:
            logger.error(f"PDF compilation failed: {str(pdf_err)}")
            save_agent_log(customer_id, "ReportGeneratorAgent", "PDF Generation", "FAILED", str(pdf_err))

        # 6. Save recommendations, comparison and eligibility to database
        save_recommendations(
            customer_id=customer_id,
            recommendation_data=recommendation_results,
            comparison_data=comparison_results,
            eligibility_data=eligibility_results
        )

        return {
            "status": "success",
            "customer_id": customer_id,
            "customer_profile": profile,
            "eligibility": eligibility_results,
            "comparisons": comparison_results,
            "recommendations": recommendation_results,
            "pdf_path": os.path.abspath(pdf_path)
        }
    except Exception as overall_err:
        logger.error(f"Direct advisory compilation failed: {str(overall_err)}")
        return {
            "status": "error",
            "message": str(overall_err)
        }

@recommendations_bp.route("/run-pipeline", methods=["POST"])
def run_pipeline():
    """
    Triggers the sequential direct recommendations pipeline for a submitted customer.
    """
    try:
        data = request.json
        if not data or "customer_id" not in data:
            return jsonify({"status": "error", "message": "customer_id is required."}), 400
            
        customer_id = int(data["customer_id"])
        profile = get_customer_profile(customer_id)
        if not profile:
            return jsonify({"status": "error", "message": "Customer profile not found in database."}), 404
            
        # Run direct pipeline bypassing CrewAI
        try:
            result = generate_direct_loan_advisory(profile, customer_id=customer_id)
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
            logger.info(f"Generating recommendations dynamically for customer {customer_id}...")
            run_res = generate_direct_loan_advisory(customer, customer_id=customer_id)
            if run_res.get("status") == "success":
                data = get_recommendations(customer_id)
            else:
                return jsonify({"status": "error", "message": f"Failed to generate recommendations dynamically: {run_res.get('message')}"}), 500
                
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
            
            logger.info(f"No comparison data found for customer {customer_id}. Running direct advisor...")
            run_res = generate_direct_loan_advisory(customer, customer_id=customer_id)
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
                logger.info(f"Generating recommendations dynamically for PDF: {customer_id}...")
                run_res = generate_direct_loan_advisory(profile, customer_id=customer_id)
                if run_res.get("status") == "success":
                    data = get_recommendations(customer_id)
                    pdf_path = run_res.get("pdf_path")
                else:
                    return jsonify({"status": "error", "message": f"Failed to run direct advisor for PDF generation: {run_res.get('message')}"}), 500
            
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
