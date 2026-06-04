import sqlite3
import os
import json
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("Database")

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "loansense.db")

# Ensure the data directory exists
os.makedirs(DB_DIR, exist_ok=True)

def get_db_connection():
    """
    Returns an active SQLite connection with row factory enabled.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database at {DB_PATH}: {str(e)}")
        raise e

def init_db():
    """
    Initializes the database schemas and seeds the loan products catalog.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Create customers table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            city TEXT NOT NULL,
            employment_type TEXT NOT NULL,
            monthly_income REAL NOT NULL,
            existing_emis REAL NOT NULL,
            credit_score INTEGER NOT NULL,
            loan_purpose TEXT NOT NULL,
            desired_amount REAL NOT NULL,
            preferred_tenure INTEGER NOT NULL,
            has_collateral INTEGER NOT NULL,
            credit_estimator_answers TEXT, -- JSON string
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 2. Create recommendations table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            recommendation_data TEXT, -- JSON string
            comparison_data TEXT, -- JSON string
            eligibility_data TEXT, -- JSON string
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        )
        """)
        
        # 3. Create agent_logs table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            agent_name TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 4. Create loan_products table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS loan_products (
            loan_id TEXT PRIMARY KEY,
            bank_name TEXT NOT NULL,
            loan_type TEXT NOT NULL,
            min_amount REAL NOT NULL,
            max_amount REAL NOT NULL,
            interest_rate_min REAL NOT NULL,
            interest_rate_max REAL NOT NULL,
            max_tenure_months INTEGER NOT NULL,
            processing_fee_percent REAL NOT NULL,
            min_credit_score INTEGER NOT NULL,
            min_monthly_income REAL NOT NULL,
            employment_types_eligible TEXT NOT NULL, -- comma-separated or JSON array
            special_features TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 5. Create application_tracker table for Kanban board (Feature 5)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS application_tracker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            loan_id TEXT NOT NULL,
            bank_name TEXT NOT NULL,
            loan_type TEXT NOT NULL,
            status TEXT DEFAULT 'Applied', -- 'Applied', 'Under Review', 'Approved', 'Rejected'
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        )
        """)
        
        conn.commit()
        logger.info("Database schemas created successfully.")
        
        # Seed loan products from data/loan_products.json
        seed_loan_products(cursor)
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise e

def seed_loan_products(cursor):
    """
    Seeds the loan_products table from the loan_products.json catalog.
    """
    json_path = os.path.join(DB_DIR, "loan_products.json")
    if not os.path.exists(json_path):
        logger.warning(f"Seeding catalog missing: {json_path}. Skipping seed.")
        return
        
    try:
        # Clear out old fictional products first
        cursor.execute("DELETE FROM loan_products")
        logger.info("Cleared old loan products before seeding.")
        with open(json_path, 'r', encoding='utf-8') as f:
            products = json.load(f)
            
        for p in products:
            emp_types = json.dumps(p["employment_types_eligible"]) if isinstance(p["employment_types_eligible"], list) else p["employment_types_eligible"]
            cursor.execute("""
            INSERT INTO loan_products (
                loan_id, bank_name, loan_type, min_amount, max_amount,
                interest_rate_min, interest_rate_max, max_tenure_months,
                processing_fee_percent, min_credit_score, min_monthly_income,
                employment_types_eligible, special_features
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(loan_id) DO UPDATE SET
                bank_name=excluded.bank_name,
                loan_type=excluded.loan_type,
                min_amount=excluded.min_amount,
                max_amount=excluded.max_amount,
                interest_rate_min=excluded.interest_rate_min,
                interest_rate_max=excluded.interest_rate_max,
                max_tenure_months=excluded.max_tenure_months,
                processing_fee_percent=excluded.processing_fee_percent,
                min_credit_score=excluded.min_credit_score,
                min_monthly_income=excluded.min_monthly_income,
                employment_types_eligible=excluded.employment_types_eligible,
                special_features=excluded.special_features
            """, (
                p["loan_id"], p["bank_name"], p["loan_type"], p["min_amount"], p["max_amount"],
                p["interest_rate_min"], p["interest_rate_max"], p["max_tenure_months"],
                p["processing_fee_percent"], p["min_credit_score"], p["min_monthly_income"],
                emp_types, p.get("special_features", "")
            ))
        logger.info(f"Seeded {len(products)} loan products successfully.")
    except Exception as e:
        logger.error(f"Error seeding loan products: {str(e)}")
        raise e

# Database CRUD helpers
def save_customer_profile(profile):
    """
    Saves a customer profile dictionary into the database. Returns the customer_id.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO customers (
            name, age, city, employment_type, monthly_income, existing_emis,
            credit_score, loan_purpose, desired_amount, preferred_tenure,
            has_collateral, credit_estimator_answers
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile["name"], profile["age"], profile["city"], profile["employment_type"],
            profile["monthly_income"], profile["existing_emis"], profile["credit_score"],
            profile["loan_purpose"], profile["desired_amount"], profile["preferred_tenure"],
            1 if profile.get("has_collateral") else 0,
            json.dumps(profile.get("credit_estimator_answers", {}))
        ))
        
        customer_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"Saved customer profile for {profile['name']} with ID: {customer_id}")
        return customer_id
    except Exception as e:
        logger.error(f"Error saving customer profile: {str(e)}")
        raise e

def get_customer_profile(customer_id):
    """
    Fetches the customer profile for a given customer_id.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            data = dict(row)
            data["credit_estimator_answers"] = json.loads(data["credit_estimator_answers"]) if data.get("credit_estimator_answers") else {}
            return data
        return None
    except Exception as e:
        logger.error(f"Error fetching customer profile: {str(e)}")
        raise e

def save_recommendations(customer_id, recommendation_data, comparison_data, eligibility_data):
    """
    Saves or updates recommendations, comparisons, and eligibility results for a customer.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if recommendations already exist
        cursor.execute("SELECT id FROM recommendations WHERE customer_id = ?", (customer_id,))
        row = cursor.fetchone()
        
        rec_json = json.dumps(recommendation_data)
        comp_json = json.dumps(comparison_data)
        elig_json = json.dumps(eligibility_data)
        
        if row:
            cursor.execute("""
            UPDATE recommendations 
            SET recommendation_data = ?, comparison_data = ?, eligibility_data = ?, created_at = CURRENT_TIMESTAMP
            WHERE customer_id = ?
            """, (rec_json, comp_json, elig_json, customer_id))
            logger.info(f"Updated recommendations for customer ID: {customer_id}")
        else:
            cursor.execute("""
            INSERT INTO recommendations (customer_id, recommendation_data, comparison_data, eligibility_data)
            VALUES (?, ?, ?, ?)
            """, (customer_id, rec_json, comp_json, elig_json))
            logger.info(f"Inserted new recommendations for customer ID: {customer_id}")
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving recommendations: {str(e)}")
        raise e

def get_recommendations(customer_id):
    """
    Retrieves the recommendation row for a given customer_id.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recommendations WHERE customer_id = ?", (customer_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            data = dict(row)
            data["recommendation_data"] = json.loads(data["recommendation_data"]) if data.get("recommendation_data") else []
            data["comparison_data"] = json.loads(data["comparison_data"]) if data.get("comparison_data") else []
            data["eligibility_data"] = json.loads(data["eligibility_data"]) if data.get("eligibility_data") else {}
            return data
        return None
    except Exception as e:
        logger.error(f"Error fetching recommendations: {str(e)}")
        raise e

def save_agent_log(customer_id, agent_name, action, status, details=None):
    """
    Logs agent activities to the SQLite database.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO agent_logs (customer_id, agent_name, action, status, details)
        VALUES (?, ?, ?, ?, ?)
        """, (customer_id, agent_name, action, status, details))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error logging agent action: {str(e)}")

def get_agent_logs(customer_id):
    """
    Fetches all agent logs for a specific customer run.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM agent_logs WHERE customer_id = ? ORDER BY created_at ASC", (customer_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching agent logs: {str(e)}")
        return []

def get_all_loan_products():
    """
    Fetches the catalog of all loan products.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM loan_products")
        rows = cursor.fetchall()
        conn.close()
        products = []
        for r in rows:
            p = dict(r)
            p["employment_types_eligible"] = json.loads(p["employment_types_eligible"])
            products.append(p)
        return products
    except Exception as e:
        logger.error(f"Error fetching loan products: {str(e)}")
        raise e

def get_past_sessions():
    """
    Gets summary of past customer intake sessions for history view.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT c.id, c.name, c.monthly_income, c.desired_amount, c.loan_purpose, c.created_at,
               (SELECT COUNT(*) FROM recommendations r WHERE r.customer_id = c.id) as has_recommendation
        FROM customers c
        ORDER BY c.created_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching past sessions: {str(e)}")
        return []

def update_application_status(customer_id, loan_id, bank_name, loan_type, status):
    """
    Adds or updates a loan application's status in the tracker.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id FROM application_tracker WHERE customer_id = ? AND loan_id = ?
        """, (customer_id, loan_id))
        row = cursor.fetchone()
        
        if row:
            cursor.execute("""
            UPDATE application_tracker SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (status, row['id']))
        else:
            cursor.execute("""
            INSERT INTO application_tracker (customer_id, loan_id, bank_name, loan_type, status)
            VALUES (?, ?, ?, ?, ?)
            """, (customer_id, loan_id, bank_name, loan_type, status))
            
        conn.commit()
        conn.close()
        logger.info(f"Updated tracker for customer {customer_id}, loan {loan_id} to status: {status}")
        return True
    except Exception as e:
        logger.error(f"Error updating application status: {str(e)}")
        return False

def get_applications(customer_id):
    """
    Gets the Kanban application board details for a customer.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM application_tracker WHERE customer_id = ?
        """, (customer_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching application tracker: {str(e)}")
        return []

if __name__ == "__main__":
    init_db()
    print("Database testing complete.")
