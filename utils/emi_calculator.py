from utils.logger import get_logger

logger = get_logger("EMICalculator")

def calculate_emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    """
    Calculates the Equated Monthly Installment (EMI) using the formula:
    EMI = P * r * (1+r)^n / ((1+r)^n - 1)
    
    Where:
    P = principal
    r = monthly interest rate (annual_rate / 12 / 100)
    n = tenure in months
    """
    try:
        if principal <= 0 or annual_rate < 0 or tenure_months <= 0:
            return 0.0
        
        # If rate is 0%, interest is zero, EMI is simple division
        if annual_rate == 0:
            return round(principal / tenure_months, 2)
            
        r = (annual_rate / 12) / 100
        n = tenure_months
        
        # Calculate EMI using the standard formula
        emi = principal * r * ((1 + r) ** n) / (((1 + r) ** n) - 1)
        return round(emi, 2)
    except ZeroDivisionError:
        logger.error("Zero division error during EMI calculation. Check inputs.")
        return 0.0
    except Exception as e:
        logger.error(f"Error calculating EMI: {str(e)}")
        return 0.0

def calculate_total_interest(principal: float, emi: float, tenure_months: int) -> float:
    """
    Calculates the total interest paid over the loan tenure:
    Total Interest = (EMI * Tenure) - Principal
    """
    try:
        if principal <= 0 or emi <= 0 or tenure_months <= 0:
            return 0.0
        total_repayment = emi * tenure_months
        total_interest = total_repayment - principal
        return round(max(0.0, total_interest), 2)
    except Exception as e:
        logger.error(f"Error calculating total interest: {str(e)}")
        return 0.0

def calculate_affordability_ratio(emi: float, monthly_income: float) -> float:
    """
    Calculates the Debt-to-Income (DTI) ratio:
    DTI = (EMI / Monthly Income) * 100
    Returns percentage as float (e.g., 45.0 for 45%).
    """
    try:
        if monthly_income <= 0:
            return 100.0 if emi > 0 else 0.0
        ratio = (emi / monthly_income) * 100
        return round(ratio, 2)
    except Exception as e:
        logger.error(f"Error calculating affordability ratio: {str(e)}")
        return 100.0

if __name__ == "__main__":
    # Self-test
    p = 100000.0
    r = 12.0
    t = 12
    emi = calculate_emi(p, r, t)
    total_int = calculate_total_interest(p, emi, t)
    ratio = calculate_affordability_ratio(emi, 50000.0)
    print(f"Test EMI: {emi} (Expected: ~8884.88)")
    print(f"Test Total Interest: {total_int} (Expected: ~6618.55)")
    print(f"Test DTI: {ratio}% (Expected: ~17.77%)")
