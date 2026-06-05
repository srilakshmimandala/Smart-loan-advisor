import json
from flask import Blueprint, request, jsonify
from database import save_customer_profile, get_customer_profile, get_past_sessions
from utils.logger import get_logger
from utils.llm_client import get_raw_gemini_model

logger = get_logger("CustomerRoutes")
customer_bp = Blueprint("customer", __name__)

@customer_bp.route("/intake", methods=["POST"])
def customer_intake():
    """
    Submits a customer financial profile.
    Supports optional credit score estimation if the score is not known.
    """
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "Missing request payload."}), 400
            
        # Validate mandatory intake fields
        required_fields = ["name", "age", "city", "employment_type", "monthly_income", 
                           "existing_emis", "loan_purpose", "desired_amount", "preferred_tenure"]
        for f in required_fields:
            if f not in data:
                return jsonify({"status": "error", "message": f"Field '{f}' is required."}), 400
        
        profile = {
            "name": data["name"],
            "age": int(data["age"]),
            "city": data["city"],
            "employment_type": data["employment_type"],
            "monthly_income": float(data["monthly_income"]),
            "existing_emis": float(data["existing_emis"]),
            "credit_score": data.get("credit_score", 650),  # default if not estimated
            "loan_purpose": data["loan_purpose"],
            "desired_amount": float(data["desired_amount"]),
            "preferred_tenure": int(data["preferred_tenure"]),
            "has_collateral": bool(data.get("has_collateral", False)),
            "credit_estimator_answers": data.get("credit_estimator_answers", {})
        }
        
        # Feature 1: Estimate Credit Score if unknown and answers are provided
        estimator_answers = data.get("credit_estimator_answers")
        if (data.get("credit_score") == "Unknown" or not data.get("credit_score")) and estimator_answers:
            estimated_score = estimate_credit_score(estimator_answers)
            profile["credit_score"] = estimated_score
            logger.info(f"Estimated credit score for {profile['name']}: {estimated_score}")
        elif isinstance(profile["credit_score"], str):
            # Map string range categories if passed directly
            mapping = {"Excellent": 780, "Good": 700, "Fair": 620, "Poor": 500, "Unknown": 600}
            profile["credit_score"] = mapping.get(profile["credit_score"], 600)
            
        # Save to SQLite database
        customer_id = save_customer_profile(profile)
        
        return jsonify({
            "status": "success",
            "message": "Customer profile submitted successfully.",
            "customer_id": customer_id,
            "credit_score": profile["credit_score"]
        }), 201
        
    except ValueError as ve:
        logger.error(f"Value validation error in customer intake: {str(ve)}")
        return jsonify({"status": "error", "message": "Invalid data format: please check numeric values."}), 400
    except Exception as e:
        logger.error(f"Error in customer intake: {str(e)}")
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500

@customer_bp.route("/<int:customer_id>", methods=["GET"])
def get_profile(customer_id):
    """
    Retrieves the customer profile for the dashboard.
    """
    try:
        profile = get_customer_profile(customer_id)
        if not profile:
            return jsonify({"status": "error", "message": "Customer profile not found."}), 404
        return jsonify({"status": "success", "profile": profile}), 200
    except Exception as e:
        logger.error(f"Error fetching profile: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@customer_bp.route("/history", methods=["GET"])
def get_history():
    """
    Retrieves past customer sessions.
    """
    try:
        sessions = get_past_sessions()
        return jsonify({"status": "success", "sessions": sessions}), 200
    except Exception as e:
        logger.error(f"Error fetching history: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def estimate_credit_score(answers):
    """
    Uses Gemini to estimate a credit score range based on 6 behavioral questions.
    Questions represent:
    1. Credit card bill payments (Always on time / sometimes late / defaults)
    2. Number of active credit card/loan products
    3. Credit utilization ratio (below 30%, 30-50%, 50%+)
    4. History of loan defaults or write-offs (Yes/No)
    5. Length of employment duration (years)
    6. Existing loan count
    """
    try:
        model = get_raw_gemini_model()
        prompt = f"""
        You are a Credit Risk Scoring Algorithm. Estimate a single credit score between 300 and 850 based on these user answers:
        
        1. Payment History: {answers.get('payment_history', 'Sometimes Late')}
        2. Credit Cards / Loans Count: {answers.get('accounts_count', '1-2')}
        3. Credit Card Limit Utilization: {answers.get('utilization', '30% - 50%')}
        4. Prior Defaults or Write-Offs: {answers.get('defaults', 'No')}
        5. Employment Vintage: {answers.get('employment_years', '1-2 years')}
        6. Credit Inquiries (Recent): {answers.get('inquiries', 'None')}
        
        Respond with ONLY a single integer representing the estimated credit score (e.g. 715). Do not write any explanations or markdown.
        """
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # Extract integer from response
        import re
        match = re.search(r'\d+', text)
        if match:
            score = int(match.group())
            return max(300, min(850, score))
        else:
            return 620  # fallback
    except Exception as e:
        logger.error(f"Failed to estimate credit score via Gemini: {str(e)}")
        return 650  # default safe fallback
