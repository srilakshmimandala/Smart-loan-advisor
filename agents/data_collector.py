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

logger = get_logger("DataCollectorAgent")

def get_data_collector_agent():
    """
    Creates and returns the Customer Data Collector agent.
    """
    try:
        llm = get_crewai_llm()
        return Agent(
            role="Friendly Financial Intake Specialist",
            goal="Analyze, sanitize, and structure customer financial profiles in a warm, professional manner.",
            backstory=(
                "You are an empathetic, warm, and highly detail-oriented financial intake counselor. "
                "You specialize in reviewing customer financial details, verifying that all essential details "
                "are present and realistic (e.g., positive income, realistic age), and structuring them into "
                "a standardized JSON schema for downstream banking systems."
            ),
            llm=llm,
            verbose=True,
            memory=False
        )
    except Exception as e:
        logger.error(f"Error creating Data Collector Agent: {str(e)}")
        raise e

def get_data_collector_task(agent, raw_profile_str):
    """
    Creates and returns the task for data collection and validation.
    """
    try:
        return Task(
            description=f"""
            Analyze the following raw customer financial profile:
            ---
            {raw_profile_str}
            ---
            
            Your tasks are:
            1. Sanitize the fields. Make sure all values are formatted properly:
               - Full Name (Capitalized)
               - Age (Integer, must be realistic, e.g. 18-100. If invalid or missing, flag it)
               - City (Title Case)
               - Employment Type (One of: Salaried, Self-Employed, Business Owner, Student. If the input is Freelancer, map it to Self-Employed.)
               - Monthly Income (Numeric, net take-home, >= 0)
               - Existing EMIs (Numeric, >= 0)
               - Credit Score (Integer, 300 to 850. If the user provided a category like Excellent/Good/Fair/Poor or "Unknown", map it to an estimated score: Excellent->780, Good->700, Fair->620, Poor->500, Unknown->600. If they did the Credit Score Estimator, use that score.)
               - Loan Purpose (One of: Home Loan, Education Loan, Car Loan, Personal Loan, Business Loan, Gold Loan, Other. Map 'Auto' or 'Vehicle' to 'Car Loan', and 'Home' to 'Home Loan'.)
               - Desired Loan Amount (Numeric, > 0)
               - Preferred Tenure (Integer, in years)
               - Collateral (Boolean, true/false)
            
            2. Perform a strict validation. If any mandatory field is missing or completely invalid (e.g. negative income or zero desired loan amount), flag it by setting a 'valid' flag to false and adding a polite error message explaining what is wrong.
            
            3. Output the result in a clean, JSON-parsable format with the following keys:
               - name
               - age
               - city
               - employment_type
               - monthly_income
               - existing_emis
               - credit_score
               - loan_purpose
               - desired_amount
               - preferred_tenure
               - has_collateral
               - valid (boolean)
               - error_message (null if valid, string if invalid)
            
            DO NOT include any Markdown formatting like ```json or similar in your final response. Return ONLY the raw JSON string.
            """,
            expected_output="A raw JSON string representing the validated and structured customer profile.",
            agent=agent
        )
    except Exception as e:
        logger.error(f"Error creating Data Collector Task: {str(e)}")
        raise e

def run_local_data_collector(raw_profile):
    """
    A standalone helper to run just this agent for local verification.
    """
    from crewai import Crew, Process
    try:
        log_agent_action("DataCollectorAgent", "Intake Verification", "STARTED", raw_profile)
        agent = get_data_collector_agent()
        task = get_data_collector_task(agent, json.dumps(raw_profile))
        
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential
        )
        
        result = crew.kickoff()
        log_agent_action("DataCollectorAgent", "Intake Verification", "SUCCESS", result)
        return result
    except Exception as e:
        log_agent_action("DataCollectorAgent", "Intake Verification", "FAILED", str(e))
        return None

if __name__ == "__main__":
    # Test profile
    test_raw = {
        "name": "john doe",
        "age": 28,
        "city": "mumbai",
        "employment_type": "Salaried",
        "monthly_income": 45000,
        "existing_emis": 5000,
        "credit_score": "Good",
        "loan_purpose": "Personal",
        "desired_amount": 200000,
        "preferred_tenure": 3,
        "has_collateral": False
    }
    res = run_local_data_collector(test_raw)
    print("Agent Result:")
    print(res)
