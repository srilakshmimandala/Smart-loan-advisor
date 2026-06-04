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
from utils.emi_calculator import calculate_emi, calculate_total_interest, calculate_affordability_ratio

logger = get_logger("LoanComparatorAgent")

def get_loan_comparator_agent():
    """
    Creates and returns the Loan Product Comparator agent.
    """
    try:
        llm = get_crewai_llm()
        return Agent(
            role="Financial Products Comparison Specialist",
            goal="Compare all eligible loan products on cost, flexibility, and suitability to help the customer make an optimized decision.",
            backstory=(
                "You are an expert quantitative financial product analyst. You specialize in calculating "
                "borrowing costs, analyzing processing fees, determining Effective Annual Rates (EAR), "
                "and ranking financial options by affordability and total interest saved."
            ),
            llm=llm,
            verbose=True,
            memory=False
        )
    except Exception as e:
        logger.error(f"Error creating Loan Comparator Agent: {str(e)}")
        raise e

def get_loan_comparator_task(agent, customer_profile_str, eligible_products_list_str, loan_catalog_str):
    """
    Creates and returns the task for loan comparison.
    """
    try:
        return Task(
            description=f"""
            Compare the eligible loan products for the customer details below:
            
            1. Customer Profile (JSON format):
            ---
            {customer_profile_str}
            ---
            
            2. List of Eligible Loan Product IDs (JSON format):
            ---
            {eligible_products_list_str}
            ---
            
            3. Complete Loan Catalog (JSON format):
            ---
            {loan_catalog_str}
            ---
            
            Perform the following calculations for EACH eligible product:
            - Determine the applicable interest rate:
              * If customer credit_score >= 750: use interest_rate_min.
              * If customer credit_score >= 650 and < 750: use average of interest_rate_min and interest_rate_max.
              * If customer credit_score < 650: use interest_rate_max.
            - Determine the tenure in months: use the customer's preferred_tenure (in years) converted to months, capped by the product's max_tenure_months.
              * Formula: tenure_months = min(preferred_tenure * 12, max_tenure_months).
            - Calculate the monthly EMI using the standard formula.
            - Calculate the total interest payable over the tenure.
            - Calculate the total amount payable (Principal + Total Interest).
            - Calculate the Effective Annual Rate (EAR): EAR = ((1 + interest_rate / 1200) ** 12 - 1) * 100 (in percentage).
            - Calculate the processing fee amount: desired_amount * (processing_fee_percent / 100).
            - Calculate the Affordability Score (0 to 100):
              * Compute New DTI = ((existing_emis + calculated_new_emi) / monthly_income) * 100.
              * Score = 100 - New DTI * 1.5. Cap it between 0 and 100.
            
            Based on these calculations:
            - Rank the products by:
              1. Lowest Monthly EMI
              2. Lowest Total Cost (Principal + Interest + Processing Fee)
              3. Lowest Interest Rate
            
            Output a JSON-parsable structure with the keys:
            - comparisons: a list of objects, one per eligible product, containing:
              * loan_id: string
              * bank_name: string
              * interest_rate_used: float (percentage)
              * tenure_months: integer
              * monthly_emi: float
              * total_interest: float
              * total_amount_payable: float
              * processing_fee_amount: float
              * effective_annual_rate: float (percentage)
              * affordability_score: integer (0-100)
            - rankings: an object containing:
              * lowest_emi: list of loan_id strings in ranked order
              * lowest_total_cost: list of loan_id strings in ranked order
              * best_rate: list of loan_id strings in ranked order
            
            DO NOT include any Markdown formatting like ```json or similar in your final response. Return ONLY the raw JSON string.
            """,
            expected_output="A raw JSON string detailing the comparisons, rates, EMIs, total costs, processing fees, and rankings.",
            agent=agent
        )
    except Exception as e:
        logger.error(f"Error creating Loan Comparator Task: {str(e)}")
        raise e

def run_local_loan_comparator(customer_profile, eligible_ids, catalog):
    """
    A standalone helper to run just this agent for local verification.
    """
    from crewai import Crew, Process
    try:
        log_agent_action("LoanComparatorAgent", "Loan Comparison", "STARTED", customer_profile["name"])
        agent = get_loan_comparator_agent()
        task = get_loan_comparator_task(
            agent,
            json.dumps(customer_profile),
            json.dumps(eligible_ids),
            json.dumps(catalog)
        )
        
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential
        )
        
        result = crew.kickoff()
        log_agent_action("LoanComparatorAgent", "Loan Comparison", "SUCCESS", result)
        return result
    except Exception as e:
        log_agent_action("LoanComparatorAgent", "Loan Comparison", "FAILED", str(e))
        return None

if __name__ == "__main__":
    # Local self-test
    from backend.database import get_all_loan_products
    
    try:
        products = get_all_loan_products()
    except Exception:
        products = []
        
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
    
    # Let's say products eligible are PL_FAST_APP, VL_AUTO, GL_LIQUID
    test_eligible = ["PL_FAST_APP", "VL_AUTO", "GL_LIQUID"]
    
    res = run_local_loan_comparator(test_profile, test_eligible, products)
    print("Agent Comparison Result:")
    print(res)
