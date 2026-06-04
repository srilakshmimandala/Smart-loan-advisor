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

logger = get_logger("RecommendationEngineAgent")

def get_recommendation_engine_agent():
    """
    Creates and returns the Recommendation Engine agent.
    """
    try:
        llm = get_crewai_llm()
        return Agent(
            role="Personal Financial Advisor",
            goal="Recommend the top 3 most suitable loan options tailored to the customer's unique situation, goals, and risk profile.",
            backstory=(
                "You are an empathetic, expert Personal Financial Advisor with credentials in wealth management and credit advisory. "
                "You understand consumer credit, loan structures, and consumer financial behavior. "
                "You analyze comparison data alongside customer profiles to deliver balanced, honest recommendations, "
                "complete with pros, cons, risk flags, and negotiation strategies."
            ),
            llm=llm,
            verbose=True,
            memory=False
        )
    except Exception as e:
        logger.error(f"Error creating Recommendation Engine Agent: {str(e)}")
        raise e

def get_recommendation_engine_task(agent, customer_profile_str, comparison_table_str):
    """
    Creates and returns the task for loan recommendations.
    """
    try:
        return Task(
            description=f"""
            Analyze the customer profile and eligible loan comparison data below to make the top 3 recommendations:
            
            1. Customer Profile (JSON format):
            ---
            {customer_profile_str}
            ---
            
            2. Loan Comparison Data (JSON format):
            ---
            {comparison_table_str}
            ---
            
            Based on these details:
            - Select the Top 3 Loan Products (or all available if there are fewer than 3) that are most suitable for this customer.
            - Take into account their desired loan amount, purpose, monthly income, existing debt commitments, and credit score.
            - Assign a suitability_score (0 to 100) for each recommendation reflecting how well it fits.
            - For each recommended product, provide:
              1. why_suits: Why this loan matches this customer specifically (e.g. alignment with their goal, DTI comfort, or approval speed).
              2. advantages: Key advantages or special features of this product for their situation.
              3. risks: Potential risks, prepayment penalties, rate hike risks, or things to watch out for.
              4. suggested_tenure: Recommended tenure to balance monthly payment size against overall interest cost.
              5. negotiation_tip: A clear, actionable tip they can use to negotiate better terms based on their profile (e.g. interest rate discount based on credit score, fee waiver, etc.).
            
            Output a JSON-parsable structure with the key:
            - recommendations: a list of objects, sorted by rank (1, 2, 3), containing:
              * rank: integer (1, 2, 3)
              * loan_id: string
              * bank_name: string
              * loan_type: string
              * suitability_score: integer (0-100)
              * why_suits: string
              * advantages: list of strings (at least 2 advantages)
              * risks: list of strings (at least 1 risk or caution note)
              * suggested_tenure: string
              * negotiation_tip: string
            
            DO NOT include any Markdown formatting like ```json or similar in your final response. Return ONLY the raw JSON string.
            """,
            expected_output="A raw JSON string containing the ranked recommendations and detailed advisor notes.",
            agent=agent
        )
    except Exception as e:
        logger.error(f"Error creating Recommendation Engine Task: {str(e)}")
        raise e

def run_local_recommendation_engine(customer_profile, comparison_data):
    """
    A standalone helper to run just this agent for local verification.
    """
    from crewai import Crew, Process
    try:
        log_agent_action("RecommendationEngineAgent", "Recommendation Engine", "STARTED", customer_profile["name"])
        agent = get_recommendation_engine_agent()
        task = get_recommendation_engine_task(
            agent,
            json.dumps(customer_profile),
            json.dumps(comparison_data)
        )
        
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential
        )
        
        result = crew.kickoff()
        log_agent_action("RecommendationEngineAgent", "Recommendation Engine", "SUCCESS", result)
        return result
    except Exception as e:
        log_agent_action("RecommendationEngineAgent", "Recommendation Engine", "FAILED", str(e))
        return None

if __name__ == "__main__":
    # Local self-test
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
    
    test_comparisons = {
        "comparisons": [
            {
                "loan_id": "VL_AUTO",
                "bank_name": "Velocity Finance",
                "interest_rate_used": 9.625,
                "tenure_months": 36,
                "monthly_emi": 6419.76,
                "total_interest": 31111.36,
                "total_amount_payable": 231111.36,
                "processing_fee_amount": 2000.0,
                "effective_annual_rate": 10.06,
                "affordability_score": 85
            },
            {
                "loan_id": "PL_FAST_APP",
                "bank_name": "SwiftFinance",
                "interest_rate_used": 15.495,
                "tenure_months": 36,
                "monthly_emi": 6984.87,
                "total_interest": 51455.32,
                "total_amount_payable": 251455.32,
                "processing_fee_amount": 5000.0,
                "effective_annual_rate": 16.64,
                "affordability_score": 80
            },
            {
                "loan_id": "GL_LIQUID",
                "bank_name": "Aurum Gold Trust",
                "interest_rate_used": 8.25,
                "tenure_months": 24,
                "monthly_emi": 9071.60,
                "total_interest": 17718.40,
                "total_amount_payable": 217718.40,
                "processing_fee_amount": 1000.0,
                "effective_annual_rate": 8.57,
                "affordability_score": 75
            }
        ],
        "rankings": {
            "lowest_emi": ["VL_AUTO", "PL_FAST_APP", "GL_LIQUID"],
            "lowest_total_cost": ["GL_LIQUID", "VL_AUTO", "PL_FAST_APP"],
            "best_rate": ["GL_LIQUID", "VL_AUTO", "PL_FAST_APP"]
        }
    }
    
    res = run_local_recommendation_engine(test_profile, test_comparisons)
    print("Agent Recommendation Result:")
    if res:
        try:
            print(res)
        except UnicodeEncodeError:
            # Fallback to ascii replacement for consoles that do not support unicode
            print(res.encode('ascii', errors='replace').decode('ascii'))
