import os
import sys

# Ensure backend and root are in the sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Database initialization
from database import init_db, get_past_sessions

# Blueprint imports
from routes.customer import customer_bp
from routes.loans import loans_bp
from routes.recommendations import recommendations_bp

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing for the frontend

# Register Blueprints
app.register_blueprint(customer_bp, url_prefix="/api/customer")
app.register_blueprint(loans_bp, url_prefix="/api/loans")
app.register_blueprint(recommendations_bp, url_prefix="/api")

@app.route("/api/history", methods=["GET"])
def get_global_history():
    """
    Direct history endpoint mapping to /api/history.
    """
    try:
        sessions = get_past_sessions()
        return jsonify({"status": "success", "sessions": sessions}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "smart-loan-advisor-api"}), 200

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Resource not found."}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"status": "error", "message": "Internal server error."}), 500

if __name__ == "__main__":
    # Ensure database schemas exist
    init_db()
    
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"
    
    print(f"Starting LoanSense AI Backend on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=debug)
