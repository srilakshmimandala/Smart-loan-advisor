import requests
import json
import time

BASE_URL = "http://127.0.0.1:5000"

def test_real_banks_flow():
    print("=== STARTING REAL BANKS AND RATE SORTING VALIDATION ===")
    
    # 1. Profile 1: Home Loan
    print("\n--- Testing Profile 1: Home Loan ---")
    intake_payload_1 = {
        "name": "Arjun Sharma",
        "age": 35,
        "city": "Mumbai",
        "employment_type": "Salaried",
        "monthly_income": 120000.0,
        "existing_emis": 15000.0,
        "credit_score": 780,
        "loan_purpose": "Home Loan",
        "desired_amount": 5000000.0,
        "preferred_tenure": 15,
        "has_collateral": True
    }
    
    r = requests.post(f"{BASE_URL}/api/customer/intake", json=intake_payload_1)
    print("Intake Status Code:", r.status_code)
    cust_id_1 = r.json()["customer_id"]
    print("Created Customer ID:", cust_id_1)
    
    print("Running advisory pipeline (Home Loan)...")
    start = time.time()
    r = requests.post(f"{BASE_URL}/api/run-pipeline", json={"customer_id": cust_id_1})
    print("Pipeline Status Code:", r.status_code)
    print(f"Duration: {time.time() - start:.2f} seconds")
    
    # Fetch and check recommendations
    r = requests.get(f"{BASE_URL}/api/recommendations/{cust_id_1}")
    print("Recommendations Status Code:", r.status_code)
    recs_1 = r.json().get("recommendations", {}).get("recommendations", [])
    print(f"Found {len(recs_1)} recommendations:")
    
    rates_1 = []
    for rec in recs_1:
        # Find matching rate from comparison
        comp_res = requests.get(f"{BASE_URL}/api/comparison/{cust_id_1}")
        comps = comp_res.json().get("comparisons", {}).get("comparisons", [])
        matching_comp = next((c for c in comps if c["loan_id"] == rec["loan_id"]), {})
        rate = matching_comp.get("interest_rate_used", 99)
        rates_1.append(rate)
        print(f" - Rank {rec['rank']}: {rec['bank_name']} ({rec['loan_type']}) - Rate: {rate}% | Explain: {rec['why_suits'][:100]}...")
        
    # Check that rates are sorted ascending (lowest first)
    is_sorted_1 = all(rates_1[i] <= rates_1[i+1] for i in range(len(rates_1)-1))
    print(f"Rates list: {rates_1} | Sorted ascending? {is_sorted_1}")
    assert is_sorted_1, "Home Loan recommendations are not sorted by lowest interest rate first!"
    
    # 2. Profile 2: Car Loan
    print("\n--- Testing Profile 2: Car Loan ---")
    intake_payload_2 = {
        "name": "Karan Malhotra",
        "age": 29,
        "city": "Delhi",
        "employment_type": "Salaried",
        "monthly_income": 60000.0,
        "existing_emis": 5000.0,
        "credit_score": 720,
        "loan_purpose": "Car Loan",
        "desired_amount": 800000.0,
        "preferred_tenure": 5,
        "has_collateral": False
    }
    
    r = requests.post(f"{BASE_URL}/api/customer/intake", json=intake_payload_2)
    print("Intake Status Code:", r.status_code)
    cust_id_2 = r.json()["customer_id"]
    print("Created Customer ID:", cust_id_2)
    
    print("Running advisory pipeline (Car Loan)...")
    start = time.time()
    r = requests.post(f"{BASE_URL}/api/run-pipeline", json={"customer_id": cust_id_2})
    print("Pipeline Status Code:", r.status_code)
    print(f"Duration: {time.time() - start:.2f} seconds")
    
    # Fetch and check recommendations
    r = requests.get(f"{BASE_URL}/api/recommendations/{cust_id_2}")
    print("Recommendations Status Code:", r.status_code)
    recs_2 = r.json().get("recommendations", {}).get("recommendations", [])
    print(f"Found {len(recs_2)} recommendations:")
    
    rates_2 = []
    for rec in recs_2:
        comp_res = requests.get(f"{BASE_URL}/api/comparison/{cust_id_2}")
        comps = comp_res.json().get("comparisons", {}).get("comparisons", [])
        matching_comp = next((c for c in comps if c["loan_id"] == rec["loan_id"]), {})
        rate = matching_comp.get("interest_rate_used", 99)
        rates_2.append(rate)
        print(f" - Rank {rec['rank']}: {rec['bank_name']} ({rec['loan_type']}) - Rate: {rate}% | Explain: {rec['why_suits'][:100]}...")
        
    is_sorted_2 = all(rates_2[i] <= rates_2[i+1] for i in range(len(rates_2)-1))
    print(f"Rates list: {rates_2} | Sorted ascending? {is_sorted_2}")
    assert is_sorted_2, "Car Loan recommendations are not sorted by lowest interest rate first!"
    
    print("\n=== VALIDATION COMPLETED SUCCESSFULLY! ===")

if __name__ == "__main__":
    test_real_banks_flow()
