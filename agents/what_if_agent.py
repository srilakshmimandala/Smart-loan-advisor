import os
import json
import logging
from database import get_all_loan_products, get_customer_profile
from utils.emi_calculator import calculate_emi, calculate_total_interest

logger = logging.getLogger("WhatIfAgent")

# Global thread-local or session context for the currently evaluated customer profile
_current_profile = {}

def set_current_profile(profile):
    """
    Sets the customer profile currently in scope for the agent session.
    """
    global _current_profile
    _current_profile = profile

def get_current_profile():
    """
    Retrieves the customer profile currently in scope.
    """
    global _current_profile
    return _current_profile

# ==========================================
# 1. TOOL FUNCTION DEFINITIONS
# ==========================================

def check_eligibility(income: float, credit_score: int, loan_amount: float, existing_debts: float) -> dict:
    """
    Checks if a customer is eligible for a loan based on income, credit score,
    loan amount, and existing debts. Returns approval status, rejection reasons,
    and maximum eligible loan amount.
    """
    try:
        profile = get_current_profile()
        loan_purpose = profile.get("loan_purpose", "Personal Loan")
        
        # Normalize loan type
        categories_mapping = {
            "Home": "Home Loan",
            "Personal": "Personal Loan",
            "Car": "Car Loan",
            "Vehicle": "Vehicle Loan",
            "Auto": "Vehicle Loan",
            "Education": "Education Loan",
            "Business": "Business Loan",
            "Gold": "Gold Loan"
        }
        mapped_loan_type = categories_mapping.get(loan_purpose, loan_purpose)
        if "Loan" not in mapped_loan_type:
            mapped_loan_type = f"{mapped_loan_type} Loan"
            
        products = get_all_loan_products()
        matching_products = [p for p in products if p["loan_type"].lower() == mapped_loan_type.lower()]
        if not matching_products:
            matching_products = products
            
        rules_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "eligibility_rules.json")
        rules = {}
        if os.path.exists(rules_path):
            with open(rules_path, 'r', encoding='utf-8') as f:
                rules = json.load(f)
                
        rule = rules.get(mapped_loan_type, {})
        
        approved = True
        reasons = []
        
        # Get thresholds
        min_income = min(p["min_monthly_income"] for p in matching_products) if matching_products else rule.get("min_monthly_income", 20000)
        min_credit = min(p["min_credit_score"] for p in matching_products) if matching_products else rule.get("min_credit_score", 600)
        min_age = rule.get("min_age", 18)
        max_age = rule.get("max_age", 75)
        
        # Age check
        age = profile.get("age", 30)
        if age < min_age or age > max_age:
            approved = False
            reasons.append(f"Age {age} is outside policy limits ({min_age}-{max_age})")
            
        # Employment check
        emp_type = profile.get("employment_type", "Salaried")
        eligible_emp = []
        for p in matching_products:
            p_emp = p["employment_types_eligible"]
            if isinstance(p_emp, str):
                p_emp = json.loads(p_emp)
            eligible_emp.extend(p_emp)
        eligible_emp = list(set(eligible_emp))
        
        if eligible_emp and emp_type not in eligible_emp:
            approved = False
            reasons.append(f"Employment type '{emp_type}' is not eligible")
            
        # Income check
        if income < min_income:
            approved = False
            reasons.append(f"Income INR {income:,.0f} < required INR {min_income:,.0f}")
            
        # Credit Score check
        if credit_score < min_credit:
            approved = False
            reasons.append(f"Credit Score {credit_score} < required {min_credit}")
            
        # DTI check
        dti = (existing_debts / income) * 100 if income > 0 else 100.0
        if dti > 50:
            approved = False
            reasons.append(f"DTI ratio ({dti:.1f}%) exceeds 50% limit")
            
        # Check with new EMI
        if approved and matching_products:
            best_p = matching_products[0]
            interest_rate = best_p["interest_rate_min"]
            if credit_score < 750:
                interest_rate = (best_p["interest_rate_min"] + best_p["interest_rate_max"]) / 2
            if credit_score < 650:
                interest_rate = best_p["interest_rate_max"]
                
            tenure_months = min(profile.get("preferred_tenure", 5) * 12, best_p["max_tenure_months"])
            new_emi = calculate_emi(loan_amount, interest_rate, tenure_months)
            new_dti = ((existing_debts + new_emi) / income) * 100 if income > 0 else 100.0
            if new_dti > 50:
                approved = False
                reasons.append(f"Total DTI with new EMI ({new_dti:.1f}%) exceeds 50% limit")
                
        # Calculate max eligible amount
        max_allowed_emi = (income * 0.50) - existing_debts
        if max_allowed_emi <= 0:
            max_eligible_amount = 0.0
        else:
            rate = 9.5
            tenure_yrs = profile.get("preferred_tenure", 5)
            if matching_products:
                p_item = matching_products[0]
                rate = p_item["interest_rate_min"]
                if credit_score < 750:
                    rate = (p_item["interest_rate_min"] + p_item["interest_rate_max"]) / 2
                if credit_score < 650:
                    rate = p_item["interest_rate_max"]
                tenure_yrs = min(profile.get("preferred_tenure", 5), p_item["max_tenure_months"] // 12)
                
            r = (rate / 12) / 100
            n = tenure_yrs * 12
            max_eligible_amount = max_allowed_emi * ((1 + r)**n - 1) / (r * (1 + r)**n)
            max_eligible_amount = round(max(0.0, max_eligible_amount), 2)
            
            if matching_products:
                max_product_limit = max(p["max_amount"] for p in matching_products)
                if max_eligible_amount > max_product_limit:
                    max_eligible_amount = max_product_limit
                    
        reason = "Meets all simulated criteria." if approved else "; ".join(reasons)
        return {
            "approved": approved,
            "reason": reason,
            "max_eligible_amount": max_eligible_amount
        }
    except Exception as e:
        logger.error(f"Error in check_eligibility tool: {str(e)}")
        return {
            "approved": False,
            "reason": f"System error checking eligibility: {str(e)}",
            "max_eligible_amount": 0.0
        }

def calculate_emi_tool(principal: float, interest_rate: float, tenure_months: int) -> dict:
    """
    Calculates the Equated Monthly Installment (EMI), total interest, and total payable amount
    for a given loan principal, interest rate, and tenure in months.
    """
    try:
        emi = calculate_emi(principal, interest_rate, tenure_months)
        total_interest = calculate_total_interest(principal, emi, tenure_months)
        total_payment = round(principal + total_interest, 2)
        return {
            "emi": emi,
            "total_interest": total_interest,
            "total_payment": total_payment
        }
    except Exception as e:
        logger.error(f"Error in calculate_emi_tool: {str(e)}")
        return {
            "emi": 0.0,
            "total_interest": 0.0,
            "total_payment": 0.0
        }

def fetch_loan_products(loan_type: str, eligible_amount: float) -> list:
    """
    Queries the database for available loan products of a given type and filters/matches them
    based on the customer's eligible amount.
    """
    try:
        products = get_all_loan_products()
        matched_products = []
        for p in products:
            p_type = p["loan_type"].lower()
            q_type = loan_type.lower()
            if q_type in p_type or p_type in q_type:
                if p["min_amount"] <= eligible_amount <= p["max_amount"]:
                    matched_products.append({
                        "loan_id": p["loan_id"],
                        "bank_name": p["bank_name"],
                        "loan_type": p["loan_type"],
                        "interest_rate_range": f"{p['interest_rate_min']}% - {p['interest_rate_max']}%",
                        "processing_fee_percent": p["processing_fee_percent"],
                        "special_features": p["special_features"]
                    })
        return matched_products
    except Exception as e:
        logger.error(f"Error in fetch_loan_products tool: {str(e)}")
        return []

def suggest_improvement(current_profile: dict, target_eligibility: dict) -> dict:
    """
    Provides actionable suggestions on how a customer can improve their financial profile
    (e.g., reduce existing debts, increase income, improve credit score) to meet target eligibility criteria.
    """
    try:
        suggestions = []
        income = current_profile.get("income", 0.0)
        credit_score = current_profile.get("credit_score", 0)
        existing_debts = current_profile.get("existing_debts", 0.0)
        desired_amount = current_profile.get("desired_amount", 0.0)
        
        target_min_credit = target_eligibility.get("min_credit_score", 650)
        target_min_income = target_eligibility.get("min_income", 25000.0)
        target_max_dti = target_eligibility.get("max_dti", 50.0)
        
        # Credit Score gap
        if credit_score < target_min_credit:
            diff = target_min_credit - credit_score
            suggestions.append(f"Boost credit score by {diff} points (target: {target_min_credit}) by paying all credit card bills and EMIs on time, and keeping utilization below 30%.")
            
        # Income gap
        if income < target_min_income:
            diff = target_min_income - income
            suggestions.append(f"Increase monthly income by INR {diff:,.0f} (target: {target_min_income:,.0f}) or apply with a co-borrower/co-applicant with stable income.")
            
        # DTI gap (existing debts)
        current_dti = (existing_debts / income) * 100 if income > 0 else 100.0
        if current_dti > target_max_dti:
            max_allowed_debts = income * (target_max_dti / 100.0)
            debt_reduction = existing_debts - max_allowed_debts
            suggestions.append(f"Reduce existing monthly EMI/debt obligations by at least INR {debt_reduction:,.0f} to lower DTI below {target_max_dti}%.")
            
        # DTI gap including proposed new EMI
        profile = get_current_profile()
        pref_tenure = current_profile.get("preferred_tenure") or profile.get("preferred_tenure", 5)
        tenure_months = pref_tenure * 12
        rate = 10.0
        r = (rate / 12) / 100
        new_emi = desired_amount * r * ((1 + r) ** tenure_months) / (((1 + r) ** tenure_months) - 1) if desired_amount > 0 else 0
        total_dti = ((existing_debts + new_emi) / income) * 100 if income > 0 else 100.0
        
        if current_dti <= target_max_dti and total_dti > target_max_dti:
            max_allowed_emi = (income * (target_max_dti / 100.0)) - existing_debts
            if max_allowed_emi <= 0:
                suggestions.append("You have no headroom for new EMIs. Consider paying off existing debts first.")
            else:
                max_loan_est = max_allowed_emi * ((1 + r)**tenure_months - 1) / (r * (1 + r)**tenure_months)
                suggestions.append(
                    f"Reduce your desired loan amount to INR {max_loan_est:,.0f} or below to keep DTI within limits. "
                    f"Alternatively, choose a longer tenure to reduce the monthly EMI size."
                )
            
        if not suggestions:
            suggestions.append("Your financial profile is strong and meets eligibility requirements. Keep up the good credit habits!")
            
        return {
            "actionable_suggestions": suggestions
        }
    except Exception as e:
        logger.error(f"Error in suggest_improvement tool: {str(e)}")
        return {
            "actionable_suggestions": ["System error generating suggestions."]
        }

# ==========================================
# 2. GROQ AGENT LOOP IMPLEMENTATION
# ==========================================

def run_what_if_agent(user_query: str, customer_id: int) -> dict:
    """
    Executes the agent loop using Groq API with LLaMA 3 tool calling.
    Logs each step's inputs/outputs and returns a natural-language response.
    """
    from groq import Groq
    
    # Retrieve profile
    profile = get_customer_profile(customer_id)
    if not profile:
        return {"status": "error", "message": "Customer profile not found."}
        
    # Store profile in thread context/globals for the tools to access
    set_current_profile(profile)
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"status": "error", "message": "GROQ_API_KEY environment variable not configured."}
        
    client = Groq(api_key=api_key)
    trace_log = []
    
    # Construct tools definitions for Groq API
    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_eligibility",
                "description": "Checks if a customer is eligible for a loan based on simulated monthly income, credit score, loan amount, and existing debts. Returns approval status, rejection reasons, and max eligible loan amount.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "income": {"type": "number", "description": "The customer's simulated monthly income in INR."},
                        "credit_score": {"type": "integer", "description": "The customer's simulated credit score (300-850)."},
                        "loan_amount": {"type": "number", "description": "The simulated desired loan amount in INR."},
                        "existing_debts": {"type": "number", "description": "The customer's simulated existing monthly EMIs/debts in INR."}
                    },
                    "required": ["income", "credit_score", "loan_amount", "existing_debts"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "calculate_emi",
                "description": "Calculates the Equated Monthly Installment (EMI), total interest, and total payable amount for a given loan amount (principal), interest rate, and tenure in months.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "principal": {"type": "number", "description": "The simulated loan principal amount in INR."},
                        "interest_rate": {"type": "number", "description": "The annual interest rate (e.g. 9.5 for 9.5%)."},
                        "tenure_months": {"type": "integer", "description": "The loan tenure in months."}
                    },
                    "required": ["principal", "interest_rate", "tenure_months"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_loan_products",
                "description": "Queries the database for available loan products of a given type (e.g., 'Home Loan', 'Personal Loan', 'Vehicle Loan') and filters/matches them based on the customer's eligible amount.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "loan_type": {"type": "string", "description": "The category of loan. Options: 'Home Loan', 'Personal Loan', 'Vehicle Loan', 'Car Loan', 'Education Loan', 'Business Loan', 'Gold Loan'."},
                        "eligible_amount": {"type": "number", "description": "The customer's eligible loan amount in INR."}
                    },
                    "required": ["loan_type", "eligible_amount"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "suggest_improvement",
                "description": "Provides actionable suggestions on how a customer can improve their financial profile (e.g. reduce existing debts, increase income, improve credit score) to meet target eligibility criteria.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "current_profile": {
                            "type": "object",
                            "description": "The current profile details of the customer (income, credit score, existing debts, desired amount, etc.)",
                            "properties": {
                                "income": {"type": "number"},
                                "credit_score": {"type": "integer"},
                                "existing_debts": {"type": "number"},
                                "desired_amount": {"type": "number"}
                            },
                            "required": ["income", "credit_score", "existing_debts", "desired_amount"]
                        },
                        "target_eligibility": {
                            "type": "object",
                            "description": "The minimum requirements of the desired product (min credit score, min income, DTI limits, etc.)",
                            "properties": {
                                "min_credit_score": {"type": "integer"},
                                "min_income": {"type": "number"},
                                "max_dti": {"type": "number"}
                            },
                            "required": ["min_credit_score", "min_income"]
                        }
                    },
                    "required": ["current_profile", "target_eligibility"]
                }
            }
        }
    ]
    
    # Construct System Prompt with current client context
    system_prompt = (
        f"You are the What-If Simulator Agent for Smart Loan Advisor. "
        f"Your goal is to answer the user's scenario-based queries (e.g., 'what if my income was 20% higher?') "
        f"by calling the appropriate financial tools in sequence. "
        f"Here is the context of the customer currently loaded: \n"
        f"- Name: {profile['name']}\n"
        f"- Age: {profile['age']}\n"
        f"- City: {profile['city']}\n"
        f"- Employment Type: {profile['employment_type']}\n"
        f"- Current Monthly Income: INR {profile['monthly_income']:,.2f}\n"
        f"- Current Existing Monthly EMIs/Debts: INR {profile['existing_emis']:,.2f}\n"
        f"- Current Credit Score: {profile['credit_score']}\n"
        f"- Desired Loan Type: {profile['loan_purpose']} Loan\n"
        f"- Desired Loan Amount: INR {profile['desired_amount']:,.2f}\n"
        f"- Preferred Tenure: {profile['preferred_tenure']} years ({profile['preferred_tenure'] * 12} months)\n"
        f"- Has Collateral: {bool(profile['has_collateral'])}\n\n"
        f"When a query specifies a change (e.g., 'what if my income was 20% higher'), compute the simulated value "
        f"and use it when calling tools. Do not just talk. Call the tools to verify approval, get EMI payments, "
        f"and fetch products. If the user's request is not eligible, you should also call suggest_improvement "
        f"to tell them how to become eligible.\n"
        f"IMPORTANT: You MUST base your final recommendation and status updates strictly on the output of "
        f"the tools. For example, if check_eligibility returns approved: False, you must report that the loan "
        f"is NOT approved/eligible, explain the exact reasons returned by the tool, and offer the suggestions "
        f"returned by suggest_improvement. Do NOT claim the customer is eligible if the tools say otherwise."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]
    
    max_iterations = 8
    for iteration in range(max_iterations):
        logger.info(f"Agent Loop iteration {iteration + 1}")
        
        # LLM reasons and decides tools to call
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2
        )
        
        response_message = response.choices[0].message
        messages.append(response_message)
        
        # If no tool calls, LLM gave the final response
        if not response_message.tool_calls:
            break
            
        # Execute tool calls
        for tool_call in response_message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            
            logger.info(f"Executing tool {tool_name} with args: {tool_args}")
            
            try:
                if tool_name == "check_eligibility":
                    result = check_eligibility(
                        income=float(tool_args.get("income")),
                        credit_score=int(tool_args.get("credit_score")),
                        loan_amount=float(tool_args.get("loan_amount")),
                        existing_debts=float(tool_args.get("existing_debts"))
                    )
                elif tool_name == "calculate_emi":
                    result = calculate_emi_tool(
                        principal=float(tool_args.get("principal")),
                        interest_rate=float(tool_args.get("interest_rate")),
                        tenure_months=int(tool_args.get("tenure_months"))
                    )
                elif tool_name == "fetch_loan_products":
                    result = fetch_loan_products(
                        loan_type=str(tool_args.get("loan_type")),
                        eligible_amount=float(tool_args.get("eligible_amount"))
                    )
                elif tool_name == "suggest_improvement":
                    result = suggest_improvement(
                        current_profile=dict(tool_args.get("current_profile")),
                        target_eligibility=dict(tool_args.get("target_eligibility"))
                    )
                else:
                    result = {"error": f"Unknown tool: {tool_name}"}
            except Exception as tool_err:
                logger.error(f"Error executing tool {tool_name}: {str(tool_err)}")
                result = {"error": str(tool_err)}
                
            # Log trace step
            trace_log.append({
                "step": len(trace_log) + 1,
                "tool": tool_name,
                "input": tool_args,
                "output": result
            })
            
            # Feed tool execution result back to LLM
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": json.dumps(result)
            })
            
    final_response = response_message.content if response_message.content else "Simulation processed."
    
    return {
        "status": "success",
        "response": final_response,
        "trace": trace_log
    }
