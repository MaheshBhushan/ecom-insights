"""
Configuration settings for the E-commerce Data Pipeline.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database configurations
DATABASE = {
    'postgres': {
        'host': os.getenv('PG_HOST', 'localhost'),
        'port': os.getenv('PG_PORT', '5432'),
        'database': os.getenv('PG_DATABASE', 'ecommerce'),
        'user': os.getenv('PG_USER', 'postgres'),
        'password': os.getenv('PG_PASSWORD', ''),
    },
    'mysql': {
        'host': os.getenv('MYSQL_HOST', 'localhost'),
        'port': os.getenv('MYSQL_PORT', '3306'),
        'database': os.getenv('MYSQL_DATABASE', 'ecommerce'),
        'user': os.getenv('MYSQL_USER', 'root'),
        'password': os.getenv('MYSQL_PASSWORD', ''),
    }
}

# API configurations
API = {
    'ecommerce_api': {
        'base_url': os.getenv('API_BASE_URL', 'https://api.example.com'),
        'api_key': os.getenv('API_KEY', ''),
        'timeout': 30,
    }
}

# File paths
PATHS = {
    'raw_data': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'raw'),
    'processed_data': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'processed'),
    'reports': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports'),
}

# Data processing settings
PROCESSING = {
    'batch_size': 10000,
    'date_format': '%Y-%m-%d',
    'datetime_format': '%Y-%m-%d %H:%M:%S',
}

# Reporting settings
REPORTING = {
    'daily_report_time': '08:00',
    'weekly_report_day': 'Monday',
    'monthly_report_day': 1,
}

# Logging configuration
LOGGING = {
    'level': os.getenv('LOG_LEVEL', 'INFO'),
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'log_file': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'pipeline.log'),
} 