"""
Data transformation module for the E-commerce Data Pipeline.
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from src.utils import (
    clean_text_data, 
    handle_missing_values, 
    get_date_features, 
    validate_dataframe,
    logger
)

class DataTransformer:
    """Class for transforming and cleaning e-commerce data."""
    
    def __init__(self):
        """Initialize the DataTransformer."""
        self.logger = logging.getLogger(__name__)
    
    def transform_orders_data(self, df):
        """
        Transform orders data.
        
        Args:
            df (pandas.DataFrame): Raw orders data
            
        Returns:
            pandas.DataFrame: Transformed orders data
        """
        self.logger.info("Transforming orders data")
        
        # Validate required columns
        required_columns = ['order_id', 'customer_id', 'order_date', 'order_status', 'order_total']
        if not validate_dataframe(df, required_columns):
            raise ValueError("Orders data is missing required columns")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Clean text columns
        text_columns = ['order_status', 'payment_method', 'shipping_method']
        df = clean_text_data(df, text_columns)
        
        # Handle missing values
        df = handle_missing_values(df, strategy='median')
        
        # Convert data types
        df['order_id'] = df['order_id'].astype(str)
        df['customer_id'] = df['customer_id'].astype(str)
        df['order_date'] = pd.to_datetime(df['order_date'])
        df['order_total'] = pd.to_numeric(df['order_total'], errors='coerce')
        
        # Extract date features
        df = get_date_features(df, 'order_date')
        
        # Calculate additional metrics
        if 'shipping_cost' in df.columns and 'tax' in df.columns:
            df['order_subtotal'] = df['order_total'] - df['shipping_cost'] - df['tax']
        
        # Standardize order status
        status_mapping = {
            'completed': 'Completed',
            'complete': 'Completed',
            'shipped': 'Shipped',
            'processing': 'Processing',
            'pending': 'Pending',
            'cancelled': 'Cancelled',
            'canceled': 'Cancelled',
            'refunded': 'Refunded'
        }
        df['order_status'] = df['order_status'].str.lower().map(status_mapping).fillna(df['order_status'])
        
        self.logger.info(f"Successfully transformed orders data with {len(df)} rows")
        return df
    
    def transform_customers_data(self, df):
        """
        Transform customers data.
        
        Args:
            df (pandas.DataFrame): Raw customers data
            
        Returns:
            pandas.DataFrame: Transformed customers data
        """
        self.logger.info("Transforming customers data")
        
        # Validate required columns
        required_columns = ['customer_id', 'email', 'registration_date']
        if not validate_dataframe(df, required_columns):
            raise ValueError("Customers data is missing required columns")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Clean text columns
        text_columns = ['first_name', 'last_name', 'email', 'address', 'city', 'state', 'country']
        df = clean_text_data(df, text_columns)
        
        # Handle missing values
        df = handle_missing_values(df, strategy='mode')
        
        # Convert data types
        df['customer_id'] = df['customer_id'].astype(str)
        df['registration_date'] = pd.to_datetime(df['registration_date'])
        
        # Extract date features
        df = get_date_features(df, 'registration_date')
        
        # Create full name column
        if 'first_name' in df.columns and 'last_name' in df.columns:
            df['full_name'] = df['first_name'] + ' ' + df['last_name']
        
        # Standardize country codes
        if 'country' in df.columns:
            # Convert to uppercase for country codes
            df['country'] = df['country'].str.upper()
            
            # Map common variations
            country_mapping = {
                'UNITED STATES': 'US',
                'USA': 'US',
                'UNITED KINGDOM': 'UK',
                'GREAT BRITAIN': 'UK',
                'ENGLAND': 'UK'
            }
            df['country'] = df['country'].map(lambda x: country_mapping.get(x, x))
        
        self.logger.info(f"Successfully transformed customers data with {len(df)} rows")
        return df
    
    def transform_products_data(self, df):
        """
        Transform products data.
        
        Args:
            df (pandas.DataFrame): Raw products data
            
        Returns:
            pandas.DataFrame: Transformed products data
        """
        self.logger.info("Transforming products data")
        
        # Validate required columns
        required_columns = ['product_id', 'product_name', 'price']
        if not validate_dataframe(df, required_columns):
            raise ValueError("Products data is missing required columns")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Clean text columns
        text_columns = ['product_name', 'description', 'category', 'brand']
        df = clean_text_data(df, text_columns)
        
        # Handle missing values
        df = handle_missing_values(df, strategy='median')
        
        # Convert data types
        df['product_id'] = df['product_id'].astype(str)
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        
        if 'cost' in df.columns:
            df['cost'] = pd.to_numeric(df['cost'], errors='coerce')
            # Calculate profit margin
            df['profit_margin'] = (df['price'] - df['cost']) / df['price']
        
        # Standardize categories
        if 'category' in df.columns:
            df['category'] = df['category'].str.title()
        
        # Create price tiers
        df['price_tier'] = pd.cut(
            df['price'],
            bins=[0, 10, 50, 100, 500, float('inf')],
            labels=['Budget', 'Low', 'Medium', 'High', 'Premium']
        )
        
        self.logger.info(f"Successfully transformed products data with {len(df)} rows")
        return df
    
    def transform_order_items_data(self, df):
        """
        Transform order items data.
        
        Args:
            df (pandas.DataFrame): Raw order items data
            
        Returns:
            pandas.DataFrame: Transformed order items data
        """
        self.logger.info("Transforming order items data")
        
        # Validate required columns
        required_columns = ['order_id', 'product_id', 'quantity', 'price']
        if not validate_dataframe(df, required_columns):
            raise ValueError("Order items data is missing required columns")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Handle missing values
        df = handle_missing_values(df, strategy='median')
        
        # Convert data types
        df['order_id'] = df['order_id'].astype(str)
        df['product_id'] = df['product_id'].astype(str)
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0).astype(int)
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        
        # Calculate item total
        df['item_total'] = df['quantity'] * df['price']
        
        # Calculate discount amount if discount_rate is present
        if 'discount_rate' in df.columns:
            df['discount_rate'] = pd.to_numeric(df['discount_rate'], errors='coerce').fillna(0)
            df['discount_amount'] = df['item_total'] * df['discount_rate']
            df['discounted_total'] = df['item_total'] - df['discount_amount']
        
        self.logger.info(f"Successfully transformed order items data with {len(df)} rows")
        return df
    
    def join_orders_with_customers(self, orders_df, customers_df):
        """
        Join orders data with customers data.
        
        Args:
            orders_df (pandas.DataFrame): Transformed orders data
            customers_df (pandas.DataFrame): Transformed customers data
            
        Returns:
            pandas.DataFrame: Joined data
        """
        self.logger.info("Joining orders with customers data")
        
        # Make copies to avoid modifying the originals
        orders_df = orders_df.copy()
        customers_df = customers_df.copy()
        
        # Select relevant columns from customers
        customer_cols = ['customer_id', 'full_name', 'email', 'country', 'registration_date']
        customer_cols = [col for col in customer_cols if col in customers_df.columns]
        customers_subset = customers_df[customer_cols]
        
        # Merge the dataframes
        merged_df = pd.merge(
            orders_df,
            customers_subset,
            on='customer_id',
            how='left'
        )
        
        self.logger.info(f"Successfully joined orders with customers, resulting in {len(merged_df)} rows")
        return merged_df
    
    def join_order_items_with_products(self, order_items_df, products_df):
        """
        Join order items data with products data.
        
        Args:
            order_items_df (pandas.DataFrame): Transformed order items data
            products_df (pandas.DataFrame): Transformed products data
            
        Returns:
            pandas.DataFrame: Joined data
        """
        self.logger.info("Joining order items with products data")
        
        # Make copies to avoid modifying the originals
        order_items_df = order_items_df.copy()
        products_df = products_df.copy()
        
        # Select relevant columns from products
        product_cols = ['product_id', 'product_name', 'category', 'brand', 'price_tier']
        product_cols = [col for col in product_cols if col in products_df.columns]
        products_subset = products_df[product_cols]
        
        # Merge the dataframes
        merged_df = pd.merge(
            order_items_df,
            products_subset,
            on='product_id',
            how='left'
        )
        
        self.logger.info(f"Successfully joined order items with products, resulting in {len(merged_df)} rows")
        return merged_df
    
    def create_sales_summary(self, orders_df, order_items_df, products_df=None):
        """
        Create a sales summary by joining orders and order items data.
        
        Args:
            orders_df (pandas.DataFrame): Transformed orders data
            order_items_df (pandas.DataFrame): Transformed order items data
            products_df (pandas.DataFrame, optional): Transformed products data
            
        Returns:
            pandas.DataFrame: Sales summary data
        """
        self.logger.info("Creating sales summary")
        
        # Make copies to avoid modifying the originals
        orders_df = orders_df.copy()
        order_items_df = order_items_df.copy()
        
        # Join order items with products if provided
        if products_df is not None:
            order_items_df = self.join_order_items_with_products(order_items_df, products_df)
        
        # Merge orders with order items
        sales_df = pd.merge(
            order_items_df,
            orders_df[['order_id', 'customer_id', 'order_date', 'order_status']],
            on='order_id',
            how='left'
        )

        # Cancelled orders never realized revenue -- exclude them, matching
        # src/insights/kpis.py and fact_sales.
        sales_df = sales_df[sales_df['order_status'] != 'Cancelled']

        # discount_amount may not exist if transform_order_items_data was
        # given items without a discount_rate column.
        has_discount = 'discount_amount' in sales_df.columns
        if has_discount:
            sales_df['net_revenue'] = sales_df['item_total'] - sales_df['discount_amount']

        # Group by date and calculate metrics. gross_revenue is item_total
        # summed (pre-discount line total, same basis as fact_sales.gross_revenue).
        agg_spec = {
            'order_id': 'nunique',
            'item_total': 'sum',
            'quantity': 'sum',
            'product_id': 'nunique',
            'customer_id': 'nunique'
        }
        if has_discount:
            agg_spec['net_revenue'] = 'sum'
        daily_sales = sales_df.groupby(sales_df['order_date'].dt.date).agg(agg_spec).reset_index()

        # Rename columns
        daily_sales.columns = [
            'date',
            'total_orders',
            'gross_revenue',
            'total_items_sold',
            'unique_products_sold',
            'unique_customers'
        ] + (['net_revenue'] if has_discount else [])

        # Calculate average order value (gross basis)
        daily_sales['average_order_value'] = daily_sales['gross_revenue'] / daily_sales['total_orders']
        
        # Calculate average items per order
        daily_sales['average_items_per_order'] = daily_sales['total_items_sold'] / daily_sales['total_orders']
        
        self.logger.info(f"Successfully created sales summary with {len(daily_sales)} rows")
        return daily_sales 