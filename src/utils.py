"""
Utility functions for the E-commerce Data Pipeline.
"""
import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime
import json
import hashlib
from sqlalchemy import create_engine
from src.config import DATABASE, LOGGING, PATHS

# Set up logging
def setup_logging():
    """Configure logging for the application."""
    log_dir = os.path.dirname(LOGGING['log_file'])
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    logging.basicConfig(
        level=getattr(logging, LOGGING['level']),
        format=LOGGING['format'],
        handlers=[
            logging.FileHandler(LOGGING['log_file']),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# Database connection functions
def get_db_connection(db_type='postgres'):
    """
    Create a database connection using SQLAlchemy.
    
    Args:
        db_type (str): Type of database ('postgres' or 'mysql')
        
    Returns:
        engine: SQLAlchemy engine object
    """
    try:
        if db_type == 'postgres':
            db_config = DATABASE['postgres']
            connection_string = f"postgresql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
        elif db_type == 'mysql':
            db_config = DATABASE['mysql']
            connection_string = f"mysql+pymysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
        else:
            raise ValueError(f"Unsupported database type: {db_type}")
        
        engine = create_engine(connection_string)
        logger.info(f"Successfully connected to {db_type} database")
        return engine
    except Exception as e:
        logger.error(f"Error connecting to {db_type} database: {str(e)}")
        raise

# Data validation functions
def validate_dataframe(df, required_columns=None, data_types=None):
    """
    Validate a pandas DataFrame against required columns and data types.
    
    Args:
        df (pandas.DataFrame): DataFrame to validate
        required_columns (list): List of required column names
        data_types (dict): Dictionary mapping column names to expected data types
        
    Returns:
        bool: True if validation passes, False otherwise
    """
    if required_columns:
        missing_columns = set(required_columns) - set(df.columns)
        if missing_columns:
            logger.error(f"Missing required columns: {missing_columns}")
            return False
    
    if data_types:
        for col, dtype in data_types.items():
            if col in df.columns:
                if not pd.api.types.is_dtype_equal(df[col].dtype, dtype):
                    try:
                        df[col] = df[col].astype(dtype)
                        logger.warning(f"Column {col} converted to {dtype}")
                    except:
                        logger.error(f"Column {col} could not be converted to {dtype}")
                        return False
    
    return True

# Data transformation helpers
def clean_text_data(df, text_columns):
    """
    Clean text data in specified columns.
    
    Args:
        df (pandas.DataFrame): DataFrame to clean
        text_columns (list): List of column names containing text data
        
    Returns:
        pandas.DataFrame: Cleaned DataFrame
    """
    for col in text_columns:
        if col in df.columns:
            # Convert to string type
            df[col] = df[col].astype(str)
            # Remove leading/trailing whitespace
            df[col] = df[col].str.strip()
            # Replace multiple spaces with a single space
            df[col] = df[col].str.replace(r'\s+', ' ', regex=True)
            # Replace NaN values with empty string
            df[col] = df[col].replace('nan', '')
    
    return df

def handle_missing_values(df, strategy='mean'):
    """
    Handle missing values in a DataFrame.
    
    Args:
        df (pandas.DataFrame): DataFrame with missing values
        strategy (str): Strategy to handle missing values ('mean', 'median', 'mode', 'drop', 'zero')
        
    Returns:
        pandas.DataFrame: DataFrame with handled missing values
    """
    numeric_columns = df.select_dtypes(include=['number']).columns
    
    if strategy == 'mean':
        for col in numeric_columns:
            df[col].fillna(df[col].mean(), inplace=True)
    elif strategy == 'median':
        for col in numeric_columns:
            df[col].fillna(df[col].median(), inplace=True)
    elif strategy == 'mode':
        for col in df.columns:
            df[col].fillna(df[col].mode()[0] if not df[col].mode().empty else None, inplace=True)
    elif strategy == 'zero':
        for col in numeric_columns:
            df[col].fillna(0, inplace=True)
    elif strategy == 'drop':
        df.dropna(inplace=True)
    
    return df

# File handling functions
def ensure_dir(directory):
    """Ensure that a directory exists, creating it if necessary."""
    if not os.path.exists(directory):
        os.makedirs(directory)
        logger.info(f"Created directory: {directory}")

def save_dataframe(df, filename, format='csv'):
    """
    Save a DataFrame to a file.
    
    Args:
        df (pandas.DataFrame): DataFrame to save
        filename (str): Name of the file (without extension)
        format (str): File format ('csv', 'parquet', 'excel', 'json')
    """
    ensure_dir(PATHS['processed_data'])
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if format == 'csv':
        file_path = os.path.join(PATHS['processed_data'], f"{filename}_{timestamp}.csv")
        df.to_csv(file_path, index=False)
    elif format == 'parquet':
        file_path = os.path.join(PATHS['processed_data'], f"{filename}_{timestamp}.parquet")
        df.to_parquet(file_path, index=False)
    elif format == 'excel':
        file_path = os.path.join(PATHS['processed_data'], f"{filename}_{timestamp}.xlsx")
        df.to_excel(file_path, index=False)
    elif format == 'json':
        file_path = os.path.join(PATHS['processed_data'], f"{filename}_{timestamp}.json")
        df.to_json(file_path, orient='records')
    else:
        raise ValueError(f"Unsupported file format: {format}")
    
    logger.info(f"Saved DataFrame to {file_path}")
    return file_path

# Data hashing for change detection
def get_dataframe_hash(df):
    """
    Generate a hash of a DataFrame for change detection.
    
    Args:
        df (pandas.DataFrame): DataFrame to hash
        
    Returns:
        str: Hash of the DataFrame
    """
    df_json = df.to_json(orient='records')
    return hashlib.md5(df_json.encode()).hexdigest()

# Date and time utilities
def get_date_features(df, date_column):
    """
    Extract date features from a date column.
    
    Args:
        df (pandas.DataFrame): DataFrame containing the date column
        date_column (str): Name of the date column
        
    Returns:
        pandas.DataFrame: DataFrame with additional date features
    """
    df = df.copy()
    df[date_column] = pd.to_datetime(df[date_column])
    
    df[f'{date_column}_year'] = df[date_column].dt.year
    df[f'{date_column}_month'] = df[date_column].dt.month
    df[f'{date_column}_day'] = df[date_column].dt.day
    df[f'{date_column}_dayofweek'] = df[date_column].dt.dayofweek
    df[f'{date_column}_quarter'] = df[date_column].dt.quarter
    df[f'{date_column}_is_weekend'] = df[date_column].dt.dayofweek >= 5
    
    return df 