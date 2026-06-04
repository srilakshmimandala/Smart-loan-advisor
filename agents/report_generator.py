import os
import json
from datetime import datetime
from typing import Any
from crewai import Agent, Task
from crewai.tools import tool
from utils.llm_client import get_crewai_llm
from utils.logger import get_logger, log_agent_action
from utils.pdf_report import generate_pdf_report

logger = get_logger("ReportGeneratorAgent")

@tool("Generate PDF Report Tool")
def generate_pdf_report_tool(customer_id: int, tips: Any, output_path: str = None) -> str:
    """
    Generates a professional 5-page PDF report based on the customer ID and the generated financial tips.
    
    Args:
        customer_id: The integer ID of the customer in the database.
        tips: The list of 5 financial tips or JSON string.
        output_path: Optional path where the PDF should be saved.
    """
    try:
        from backend.database import get_customer_profile, get_recommendations
        customer = get_customer_profile(customer_id)
        if not customer:
            return f"FAILURE: Customer profile for ID {customer_id} not found."
            
        recs = get_recommendations(customer_id)
        if not recs:
            return f"FAILURE: Recommendations/Eligibility/Comparisons for ID {customer_id} not found."
            
        eligibility = recs.get("eligibility_data") or {}
        comparisons = recs.get("comparison_data") or {}
        recommendations = recs.get("recommendation_data") or {}
        
        # Check if recommendations are missing or empty
        if not recommendations or not isinstance(recommendations, dict) or not recommendations.get("recommendations"):
            logger.info(f"Recommendations empty or missing for customer ID {customer_id} in PDF tool. Generating on-the-fly...")
            from crew_main import generate_recommendation_details
            from backend.database import save_recommendations
            comparisons_list = comparisons.get("comparisons", [])
            recommendations = generate_recommendation_details(customer, comparisons_list)
            # Save it back to SQLite
            save_recommendations(
                customer_id=customer_id,
                recommendation_data=recommendations,
                comparison_data=comparisons,
                eligibility_data=eligibility
            )
        
        import re
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

        def parse_param(param):
            if isinstance(param, str):
                try:
                    return safe_parse_json(param)
                except Exception:
                    return param
            return param

        parsed_tips = parse_param(tips)
        
        if not output_path:
            clean_name = "".join(x for x in customer.get("name", "client") if x.isalnum()).lower()
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"reports/loan_report_{clean_name}_{date_str}.pdf"
            
        success = generate_pdf_report(customer, eligibility, comparisons, recommendations, parsed_tips, output_path)
        if success:
            return f"SUCCESS: PDF report generated successfully at: {os.path.abspath(output_path)}"
        else:
            return "FAILURE: PDF report generation failed. Check application logs."
    except Exception as e:
        logger.error(f"Error in PDF generation tool: {str(e)}")
        return f"FAILURE: Error parsing parameters or generating PDF: {str(e)}"

def get_report_generator_agent():
    """
    Creates and returns the Report Generator agent.
    """
    try:
        llm = get_crewai_llm()
        return Agent(
            role="Financial Report Specialist",
            goal="Compile all customer financial profiles, eligibility checks, comparisons, and advice into a professional multi-page PDF report.",
            backstory=(
                "You are a professional documentation and publication specialist for top fintech firms. "
                "You specialize in compiling complex data points (spreadsheets, advice transcripts, eligibility criteria) "
                "into clean, well-formatted, and visually stunning PDF reports for clients."
            ),
            llm=llm,
            tools=[generate_pdf_report_tool],
            verbose=True,
            memory=False
        )
    except Exception as e:
        logger.error(f"Error creating Report Generator Agent: {str(e)}")
        raise e

def get_report_generator_task(agent, customer_id, profile_summary, eligibility_summary, recommendation_summary, output_path=None):
    """
    Creates and returns the task for report generation.
    """
    try:
        if not output_path:
            output_path = "reports/loan_report_temp.pdf"
            
        return Task(
            description=f"""
            Your task is to compile the final loan advisory report for this customer.
            
            Here is the customer summary data:
            1. Customer Profile Summary:
            {profile_summary}
            
            2. Eligibility Check Summary:
            {eligibility_summary}
            
            3. Recommended Loans Summary:
            {recommendation_summary}
            
            Perform the following steps:
            1. Generate 5 personalized financial tips to help this customer improve their creditworthiness, lower their Debt-to-Income ratio, or save money on interest. Write the tips clearly. Each tip must be represented as a dictionary with 'title' and 'description' keys.
            2. Invoke the 'Generate PDF Report Tool' passing the required parameters:
               - 'customer_id': {customer_id}
               - 'tips': the list of 5 financial tips you generated
               - 'output_path': "{output_path}"
            3. Return the response from the tool (containing the path to the PDF).
            
            DO NOT add any markdown decoration around your tool call.
            """,
            expected_output="A confirmation string containing the path of the successfully generated PDF report.",
            agent=agent
        )
    except Exception as e:
        logger.error(f"Error creating Report Generator Task: {str(e)}")
        raise e
