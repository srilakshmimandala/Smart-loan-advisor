import logging
import os
import sys
import io
from datetime import datetime

# Force stdout and stderr to UTF-8 on Windows to prevent UnicodeEncodeError when printing emojis (like the robot emoji 🤖)
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Define log format
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Configure base logging
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join("logs", "application.log"), encoding="utf-8")
    ]
)

def get_logger(name):
    """
    Returns a configured logger instance for the given module name.
    """
    return logging.getLogger(name)

def log_agent_action(agent_name, action, status="STARTED", details=None):
    """
    Specially format and log agent activities.
    """
    logger = get_logger(agent_name)
    msg = f"[{status}] Action: {action}"
    if details:
        msg += f" | Details: {details}"
    
    if status == "FAILED":
        logger.error(msg)
    elif status == "SUCCESS" or status == "COMPLETE":
        logger.info(f"\033[92m{msg}\033[0m")  # Green output in console
    else:
        logger.info(msg)
