"""
Data extraction module for the E-commerce Data Pipeline.
"""
import os
import pandas as pd
from sqlalchemy import text
import requests
import json
import logging
from datetime import datetime, timedelta
from src.config import API, PATHS
from src.utils import get_db_connection, ensure_dir, logger

class DataExtractor:
    """Class for extracting data from various sources."""
    
    def __init__(self):
        """Initialize the DataExtractor."""
        self.logger = logging.getLogger(__name__)
        ensure_dir(PATHS['raw_data'])
    
    def extract_from_csv(self, file_path, **kwargs):
        """
        Extract data from a CSV file.
        
        Args:
            file_path (str): Path to the CSV file
            **kwargs: Additional arguments to pass to pd.read_csv()
            
        Returns:
            pandas.DataFrame: Extracted data
        """
        try:
            self.logger.info(f"Extracting data from CSV file: {file_path}")
            df = pd.read_csv(file_path, **kwargs)
            self.logger.info(f"Successfully extracted {len(df)} rows from {file_path}")
            return df
        except Exception as e:
            self.logger.error(f"Error extracting data from CSV file {file_path}: {str(e)}")
            raise
    
    def extract_from_excel(self, file_path, sheet_name=0, **kwargs):
        """
        Extract data from an Excel file.
        
        Args:
            file_path (str): Path to the Excel file
            sheet_name: Sheet to read (default: 0)
            **kwargs: Additional arguments to pass to pd.read_excel()
            
        Returns:
            pandas.DataFrame: Extracted data
        """
        try:
            self.logger.info(f"Extracting data from Excel file: {file_path}, sheet: {sheet_name}")
            df = pd.read_excel(file_path, sheet_name=sheet_name, **kwargs)
            self.logger.info(f"Successfully extracted {len(df)} rows from {file_path}")
            return df
        except Exception as e:
            self.logger.error(f"Error extracting data from Excel file {file_path}: {str(e)}")
            raise
    
    def extract_from_database(self, query, params=None):
        """
        Extract data from a database using a SQL query.

        Args:
            query (str): SQL query to execute; use :name placeholders for values
            params (dict): Bound parameters for the query placeholders

        Returns:
            pandas.DataFrame: Extracted data
        """
        try:
            self.logger.info(f"Extracting data from database with query: {query}")
            engine = get_db_connection()
            df = pd.read_sql(text(query), engine, params=params)
            self.logger.info(f"Successfully extracted {len(df)} rows from database")
            return df
        except Exception as e:
            self.logger.error(f"Error extracting data from database: {str(e)}")
            raise
    
    def extract_from_api(self, endpoint, params=None, method='GET', api_name='ecommerce_api'):
        """
        Extract data from an API.
        
        Args:
            endpoint (str): API endpoint
            params (dict): Query parameters
            method (str): HTTP method ('GET', 'POST')
            api_name (str): Name of the API configuration to use
            
        Returns:
            pandas.DataFrame: Extracted data
        """
        try:
            api_config = API.get(api_name)
            if not api_config:
                raise ValueError(f"API configuration not found for {api_name}")
            
            url = f"{api_config['base_url']}/{endpoint.lstrip('/')}"
            headers = {'Authorization': f"Bearer {api_config['api_key']}"} if api_config['api_key'] else {}
            
            self.logger.info(f"Extracting data from API: {url}")
            
            if method.upper() == 'GET':
                response = requests.get(url, params=params, headers=headers, timeout=api_config['timeout'])
            elif method.upper() == 'POST':
                response = requests.post(url, json=params, headers=headers, timeout=api_config['timeout'])
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            data = response.json()
            
            # Save raw API response
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            raw_file_path = os.path.join(PATHS['raw_data'], f"api_{endpoint.replace('/', '_')}_{timestamp}.json")
            with open(raw_file_path, 'w') as f:
                json.dump(data, f)
            
            # Convert to DataFrame
            if isinstance(data, list):
                df = pd.DataFrame(data)
            elif isinstance(data, dict) and 'results' in data:
                df = pd.DataFrame(data['results'])
            elif isinstance(data, dict) and 'data' in data:
                df = pd.DataFrame(data['data'])
            else:
                df = pd.DataFrame([data])
            
            self.logger.info(f"Successfully extracted {len(df)} rows from API")
            return df
        except Exception as e:
            self.logger.error(f"Error extracting data from API {endpoint}: {str(e)}")
            raise
    
    def extract_incremental_data(self, source_type, source, date_column, start_date=None, end_date=None, **kwargs):
        """
        Extract incremental data based on a date range.
        
        Args:
            source_type (str): Type of source ('csv', 'excel', 'database', 'api')
            source (str): Source identifier (file path, query, endpoint)
            date_column (str): Name of the date column to filter on
            start_date (str): Start date for incremental extraction (default: yesterday)
            end_date (str): End date for incremental extraction (default: today)
            **kwargs: Additional arguments for the specific extraction method
            
        Returns:
            pandas.DataFrame: Extracted incremental data
        """
        # Set default date range if not provided
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        self.logger.info(f"Extracting incremental data from {start_date} to {end_date}")
        
        if source_type == 'csv':
            df = self.extract_from_csv(source, **kwargs)
            df[date_column] = pd.to_datetime(df[date_column])
            mask = (df[date_column] >= start_date) & (df[date_column] <= end_date)
            return df[mask]
        
        elif source_type == 'excel':
            df = self.extract_from_excel(source, **kwargs)
            df[date_column] = pd.to_datetime(df[date_column])
            mask = (df[date_column] >= start_date) & (df[date_column] <= end_date)
            return df[mask]
        
        elif source_type == 'database':
            query = f"{source} WHERE {date_column} BETWEEN :start_date AND :end_date"
            params = {'start_date': start_date, 'end_date': end_date}
            return self.extract_from_database(query, params=params, **kwargs)
        
        elif source_type == 'api':
            params = kwargs.pop('params', {})
            params.update({
                'start_date': start_date,
                'end_date': end_date
            })
            return self.extract_from_api(source, params=params, **kwargs)
        
        else:
            raise ValueError(f"Unsupported source type: {source_type}") 