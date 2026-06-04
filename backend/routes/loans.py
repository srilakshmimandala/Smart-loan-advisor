from flask import Blueprint, request, jsonify
from backend.database import get_all_loan_products, update_application_status, get_applications
from utils.logger import get_logger

logger = get_logger("LoansRoutes")
loans_bp = Blueprint("loans", __name__)

@loans_bp.route("", methods=["GET"])
def get_loans():
    """
    Exposes the catalog of all available loan products.
    """
    try:
        products = get_all_loan_products()
        return jsonify({"status": "success", "products": products}), 200
    except Exception as e:
        logger.error(f"Error fetching loan products: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@loans_bp.route("/apply", methods=["POST"])
def apply_loan():
    """
    Submits a mock loan application, updating its status in the SQLite tracker.
    Used for the Kanban Board (Feature 5).
    """
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "Missing payload."}), 400
            
        required = ["customer_id", "loan_id", "bank_name", "loan_type"]
        for r in required:
            if r not in data:
                return jsonify({"status": "error", "message": f"Field '{r}' is required."}), 400
                
        customer_id = int(data["customer_id"])
        loan_id = data["loan_id"]
        bank_name = data["bank_name"]
        loan_type = data["loan_type"]
        status = data.get("status", "Applied")  # Default to 'Applied'
        
        success = update_application_status(customer_id, loan_id, bank_name, loan_type, status)
        if success:
            return jsonify({"status": "success", "message": f"Application status updated to '{status}'."}), 200
        else:
            return jsonify({"status": "error", "message": "Failed to update application tracker in database."}), 500
    except Exception as e:
        logger.error(f"Error submitting loan application: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@loans_bp.route("/tracker/<int:customer_id>", methods=["GET"])
def get_loan_tracker(customer_id):
    """
    Fetches the application tracking board details for a specific customer.
    """
    try:
        applications = get_applications(customer_id)
        return jsonify({"status": "success", "applications": applications}), 200
    except Exception as e:
        logger.error(f"Error fetching application tracker: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
