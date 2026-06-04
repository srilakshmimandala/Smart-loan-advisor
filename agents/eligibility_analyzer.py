import json
import re
from crewai import Agent, Task
from utils.llm_client import get_crewai_llm
from utils.logger import get_logger, log_agent_action

def safe_parse_json(text):
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
from utils.emi_calculator import calculate_affordability_ratio

logger = get_logger("EligibilityAnalyzerAgent")

def get_eligibility_analyzer_agent():
    """
    Creates and returns the Eligibility Analyzer agent.
    """
    try:
        llm = get_crewai_llm()
        return Agent(
            role="Senior Credit Risk Analyst",
            goal="Accurately assess customer eligibility for all available loan products based on rules and financial health.",
            backstory=(
                "You are a Senior Credit Risk Analyst with decades of experience at top-tier commercial banks. "
                "You are highly detail-oriented, mathematically precise, and expert at checking credit policies, "
                "calculating Debt-to-Income (DTI) ratios, identifying credit risk indicators, "
                "and explaining credit decisions with clear justifications."
            ),
            llm=llm,
            verbose=True,
            memory=False
        )
    except Exception as e:
        logger.error(f"Error creating Eligibility Analyzer Agent: {str(e)}")
        raise e

def get_eligibility_analyzer_task(agent, customer_profile_str, loan_catalog_str, eligibility_rules_str):
    """
    Creates and returns the task for eligibility analysis.
    """
    try:
        return Task(
            description=f"""
            Evaluate the loan eligibility for this customer based on the details below:
            
            1. Customer Profile (JSON format):
            ---
            {customer_profile_str}
            ---
            
            2. Available Loan Products (JSON format):
            ---
            {loan_catalog_str}
            ---
            
            3. Credit Policy / Eligibility Rules (JSON format):
            ---
            {eligibility_rules_str}
            ---
            
            Perform the following steps:
            - Calculate the customer's Debt-to-Income (DTI) ratio based on their existing EMIs and monthly income.
            - If DTI > 50%, flag them as "High Risk" and note that they are disqualified from high-obligation loans unless collateralized.
            - Cross-check the customer's Age, Credit Score, Monthly Income, and Employment Type against the rules for EACH loan type.
            - For EACH loan type (Personal, Home, Education, Vehicle, Business, Gold), assign an eligibility status:
              * "Eligible" - Meets all criteria.
              * "Conditionally Eligible" - Fails one minor criterion (e.g. credit score is slightly low, or DTI is between 40% and 50%, or requires a co-applicant / collateral).
              * "Not Eligible" - Fails major criteria (e.g., credit score below minimum threshold, income too low, DTI > 50%, or age out of bounds).
            - For each available product in the catalog, determine if the customer qualifies (its specific minimum income, credit score, and amount limits).
            - Output the results in a clean, JSON-parsable format with the following keys:
              * dti_ratio: float (rounded to 2 decimal places)
              * is_high_risk: boolean (true if DTI > 50% or credit score is Poor)
              * loan_type_eligibility: dict mapping loan types to:
                - status: "Eligible" | "Conditionally Eligible" | "Not Eligible"
                - reason: string explaining why this status was assigned
              * eligible_products: list of strings (loan_id of products the customer is Eligible or Conditionally Eligible for)
            
            DO NOT include any Markdown formatting like ```json or similar in your final response. Return ONLY the raw JSON string.
            """,
            expected_output="A raw JSON string containing the detailed eligibility analysis, status reasons, and list of qualified loan IDs.",
            agent=agent
        )
    except Exception as e:
        logger.error(f"Error creating Eligibility Analyzer Task: {str(e)}")
        raise e

def run_local_eligibility_analyzer(customer_profile, products, rules):
    """
    A standalone helper to run just this agent for local verification.
    """
    from crewai import Crew, Process
    try:
        log_agent_action("EligibilityAnalyzerAgent", "Eligibility Analysis", "STARTED", customer_profile["name"])
        agent = get_eligibility_analyzer_agent()
        task = get_eligibility_analyzer_task(
            agent, 
            json.dumps(customer_profile), 
            json.dumps(products), 
            json.dumps(rules)
        )
        
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential
        )
        
        result = crew.kickoff()
        log_agent_action("EligibilityAnalyzerAgent", "Eligibility Analysis", "SUCCESS", result)
        return result
    except Exception as e:
        log_agent_action("EligibilityAnalyzerAgent", "Eligibility Analysis", "FAILED", str(e))
        return None

if __name__ == "__main__":
    # Local self-test
    from backend.database import get_all_loan_products
    import os
    
    # Mock data if database is not available, but database was seeded in Phase 2
    try:
        products = get_all_loan_products()
    except Exception:
        products = []
        
    rules_path = os.path.join("data", "eligibility_rules.json")
    try:
        with open(rules_path, 'r') as f:
            rules = json.load(f)
    except Exception:
        rules = {}
        
    test_profile = {
        "name": "John Doe",
        "age": 28,
        "city": "Mumbai",
        "employment_type": "Salaried",
        "monthly_income": 45000,
        "existing_emis": 5000,
        "credit_score": 700,
        "loan_purpose": "Personal",
        "desired_amount": 200000,
        "preferred_tenure": 3,
        "has_collateral": False
    }
    
    res = run_local_eligibility_analyzer(test_profile, products, rules)
    print("Agent Result:")
    print(res)
