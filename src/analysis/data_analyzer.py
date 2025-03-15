"""
Data analysis module for the E-commerce Data Pipeline.
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from src.utils import logger

class DataAnalyzer:
    """Class for analyzing e-commerce data and generating insights."""
    
    def __init__(self):
        """Initialize the DataAnalyzer."""
        self.logger = logging.getLogger(__name__)
    
    def calculate_sales_metrics(self, sales_df, time_period='daily'):
        """
        Calculate sales metrics over a specified time period.
        
        Args:
            sales_df (pandas.DataFrame): Sales data with 'order_date' and 'order_total' columns
            time_period (str): Time period for aggregation ('daily', 'weekly', 'monthly')
            
        Returns:
            pandas.DataFrame: Aggregated sales metrics
        """
        self.logger.info(f"Calculating {time_period} sales metrics")
        
        # Make a copy to avoid modifying the original
        df = sales_df.copy()
        
        # Ensure order_date is datetime
        df['order_date'] = pd.to_datetime(df['order_date'])
        
        # Group by time period
        if time_period == 'daily':
            grouped = df.groupby(df['order_date'].dt.date)
        elif time_period == 'weekly':
            grouped = df.groupby(pd.Grouper(key='order_date', freq='W-MON'))
        elif time_period == 'monthly':
            grouped = df.groupby(pd.Grouper(key='order_date', freq='M'))
        else:
            raise ValueError(f"Unsupported time period: {time_period}")
        
        # Calculate metrics
        metrics = grouped.agg({
            'order_id': 'nunique',
            'order_total': 'sum',
            'customer_id': 'nunique'
        }).reset_index()
        
        # Rename columns
        metrics.columns = ['period', 'total_orders', 'total_revenue', 'unique_customers']
        
        # Calculate average order value
        metrics['average_order_value'] = metrics['total_revenue'] / metrics['total_orders']
        
        # Calculate revenue per customer
        metrics['revenue_per_customer'] = metrics['total_revenue'] / metrics['unique_customers']
        
        self.logger.info(f"Successfully calculated {time_period} sales metrics with {len(metrics)} periods")
        return metrics
    
    def analyze_product_performance(self, order_items_df, products_df=None):
        """
        Analyze product performance based on sales data.
        
        Args:
            order_items_df (pandas.DataFrame): Order items data
            products_df (pandas.DataFrame, optional): Products data
            
        Returns:
            pandas.DataFrame: Product performance metrics
        """
        self.logger.info("Analyzing product performance")
        
        # Make a copy to avoid modifying the original
        df = order_items_df.copy()
        
        # Group by product_id
        product_metrics = df.groupby('product_id').agg({
            'order_id': 'nunique',
            'quantity': 'sum',
            'item_total': 'sum'
        }).reset_index()
        
        # Rename columns
        product_metrics.columns = ['product_id', 'order_count', 'units_sold', 'total_revenue']
        
        # Calculate average price per unit
        product_metrics['average_price'] = product_metrics['total_revenue'] / product_metrics['units_sold']
        
        # Calculate average units per order
        product_metrics['average_units_per_order'] = product_metrics['units_sold'] / product_metrics['order_count']
        
        # Join with product information if available
        if products_df is not None:
            product_cols = ['product_id', 'product_name', 'category', 'brand']
            product_cols = [col for col in product_cols if col in products_df.columns]
            products_subset = products_df[product_cols]
            
            product_metrics = pd.merge(
                product_metrics,
                products_subset,
                on='product_id',
                how='left'
            )
        
        # Sort by total revenue in descending order
        product_metrics = product_metrics.sort_values('total_revenue', ascending=False)
        
        self.logger.info(f"Successfully analyzed performance for {len(product_metrics)} products")
        return product_metrics
    
    def analyze_category_performance(self, order_items_df, products_df):
        """
        Analyze category performance based on sales data.
        
        Args:
            order_items_df (pandas.DataFrame): Order items data
            products_df (pandas.DataFrame): Products data with category information
            
        Returns:
            pandas.DataFrame: Category performance metrics
        """
        self.logger.info("Analyzing category performance")
        
        # Join order items with product information
        df = pd.merge(
            order_items_df,
            products_df[['product_id', 'category']],
            on='product_id',
            how='left'
        )
        
        # Group by category
        category_metrics = df.groupby('category').agg({
            'order_id': 'nunique',
            'product_id': 'nunique',
            'quantity': 'sum',
            'item_total': 'sum'
        }).reset_index()
        
        # Rename columns
        category_metrics.columns = [
            'category', 
            'order_count', 
            'unique_products', 
            'units_sold', 
            'total_revenue'
        ]
        
        # Calculate average revenue per product
        category_metrics['revenue_per_product'] = category_metrics['total_revenue'] / category_metrics['unique_products']
        
        # Calculate average units per order
        category_metrics['average_units_per_order'] = category_metrics['units_sold'] / category_metrics['order_count']
        
        # Sort by total revenue in descending order
        category_metrics = category_metrics.sort_values('total_revenue', ascending=False)
        
        self.logger.info(f"Successfully analyzed performance for {len(category_metrics)} categories")
        return category_metrics
    
    def analyze_customer_behavior(self, orders_df, customers_df=None):
        """
        Analyze customer behavior based on order history.
        
        Args:
            orders_df (pandas.DataFrame): Orders data
            customers_df (pandas.DataFrame, optional): Customers data
            
        Returns:
            pandas.DataFrame: Customer behavior metrics
        """
        self.logger.info("Analyzing customer behavior")
        
        # Make a copy to avoid modifying the original
        df = orders_df.copy()
        
        # Ensure order_date is datetime
        df['order_date'] = pd.to_datetime(df['order_date'])
        
        # Group by customer_id
        customer_metrics = df.groupby('customer_id').agg({
            'order_id': 'nunique',
            'order_total': 'sum',
            'order_date': ['min', 'max']
        })
        
        # Flatten multi-level columns
        customer_metrics.columns = [
            'order_count', 
            'total_spend', 
            'first_order_date', 
            'last_order_date'
        ]
        
        # Reset index
        customer_metrics = customer_metrics.reset_index()
        
        # Calculate average order value
        customer_metrics['average_order_value'] = customer_metrics['total_spend'] / customer_metrics['order_count']
        
        # Calculate days since first order
        customer_metrics['days_since_first_order'] = (
            datetime.now() - customer_metrics['first_order_date']
        ).dt.days
        
        # Calculate days since last order
        customer_metrics['days_since_last_order'] = (
            datetime.now() - customer_metrics['last_order_date']
        ).dt.days
        
        # Calculate customer lifetime (days between first and last order)
        customer_metrics['customer_lifetime_days'] = (
            customer_metrics['last_order_date'] - customer_metrics['first_order_date']
        ).dt.days
        
        # Calculate purchase frequency (average days between orders)
        customer_metrics['purchase_frequency_days'] = customer_metrics['customer_lifetime_days'] / (
            customer_metrics['order_count'] - 1
        )
        # Replace infinity with NaN and then with 0
        customer_metrics['purchase_frequency_days'] = customer_metrics['purchase_frequency_days'].replace([np.inf, -np.inf], np.nan).fillna(0)
        
        # Join with customer information if available
        if customers_df is not None:
            customer_cols = ['customer_id', 'full_name', 'email', 'country', 'registration_date']
            customer_cols = [col for col in customer_cols if col in customers_df.columns]
            customers_subset = customers_df[customer_cols]
            
            customer_metrics = pd.merge(
                customer_metrics,
                customers_subset,
                on='customer_id',
                how='left'
            )
        
        self.logger.info(f"Successfully analyzed behavior for {len(customer_metrics)} customers")
        return customer_metrics
    
    def segment_customers(self, customer_metrics, n_segments=3):
        """
        Segment customers using K-means clustering.
        
        Args:
            customer_metrics (pandas.DataFrame): Customer behavior metrics
            n_segments (int): Number of segments to create
            
        Returns:
            pandas.DataFrame: Customer metrics with segment labels
        """
        self.logger.info(f"Segmenting customers into {n_segments} segments")
        
        # Make a copy to avoid modifying the original
        df = customer_metrics.copy()
        
        # Select features for clustering
        features = [
            'order_count',
            'total_spend',
            'average_order_value',
            'days_since_last_order',
            'purchase_frequency_days'
        ]
        
        # Filter out features not in the dataframe
        features = [f for f in features if f in df.columns]
        
        # Prepare data for clustering
        X = df[features].fillna(0)
        
        # Standardize features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Apply K-means clustering
        kmeans = KMeans(n_clusters=n_segments, random_state=42)
        df['segment'] = kmeans.fit_predict(X_scaled)
        
        # Calculate segment profiles
        segment_profiles = df.groupby('segment').agg({
            'customer_id': 'count',
            'order_count': 'mean',
            'total_spend': 'mean',
            'average_order_value': 'mean',
            'days_since_last_order': 'mean',
            'purchase_frequency_days': 'mean'
        }).reset_index()
        
        # Rename columns
        segment_profiles.columns = [
            'segment',
            'customer_count',
            'avg_order_count',
            'avg_total_spend',
            'avg_order_value',
            'avg_days_since_last_order',
            'avg_purchase_frequency_days'
        ]
        
        # Assign segment labels based on spending behavior
        spending_rank = segment_profiles.sort_values('avg_total_spend', ascending=False)
        segment_labels = {
            spending_rank.iloc[0]['segment']: 'High Value',
            spending_rank.iloc[-1]['segment']: 'Low Value'
        }
        
        # Assign the middle segment(s) if there are more than 2 segments
        if n_segments > 2:
            for i in range(1, n_segments - 1):
                segment_labels[spending_rank.iloc[i]['segment']] = f'Medium Value {i}'
        
        # Map segment labels to the original dataframe
        df['segment_label'] = df['segment'].map(segment_labels)
        
        self.logger.info(f"Successfully segmented {len(df)} customers into {n_segments} segments")
        return df, segment_profiles
    
    def analyze_sales_trends(self, sales_df, period='M', periods=12):
        """
        Analyze sales trends over time.
        
        Args:
            sales_df (pandas.DataFrame): Sales data with 'order_date' and 'order_total' columns
            period (str): Time period for resampling ('D' for daily, 'W' for weekly, 'M' for monthly)
            periods (int): Number of periods to analyze
            
        Returns:
            pandas.DataFrame: Sales trend data
        """
        self.logger.info(f"Analyzing sales trends over {periods} {period} periods")
        
        # Make a copy to avoid modifying the original
        df = sales_df.copy()
        
        # Ensure order_date is datetime
        df['order_date'] = pd.to_datetime(df['order_date'])
        
        # Set end date as the last day of the most recent period
        end_date = df['order_date'].max()
        
        # Calculate start date based on the specified number of periods
        if period == 'D':
            start_date = end_date - timedelta(days=periods)
            freq = 'D'
            date_format = '%Y-%m-%d'
        elif period == 'W':
            start_date = end_date - timedelta(weeks=periods)
            freq = 'W-MON'
            date_format = '%Y-%m-%d'
        elif period == 'M':
            start_date = end_date - pd.DateOffset(months=periods)
            freq = 'M'
            date_format = '%Y-%m'
        else:
            raise ValueError(f"Unsupported period: {period}")
        
        # Filter data for the specified time range
        filtered_df = df[(df['order_date'] >= start_date) & (df['order_date'] <= end_date)]
        
        # Resample data by the specified period
        resampled = filtered_df.set_index('order_date').resample(freq).agg({
            'order_id': 'nunique',
            'order_total': 'sum',
            'customer_id': 'nunique'
        }).reset_index()
        
        # Rename columns
        resampled.columns = ['period', 'order_count', 'total_revenue', 'unique_customers']
        
        # Format period for better readability
        resampled['period_formatted'] = resampled['period'].dt.strftime(date_format)
        
        # Calculate growth rates
        resampled['revenue_growth'] = resampled['total_revenue'].pct_change()
        resampled['order_growth'] = resampled['order_count'].pct_change()
        resampled['customer_growth'] = resampled['unique_customers'].pct_change()
        
        # Calculate moving averages
        window = min(3, len(resampled))
        resampled['revenue_ma'] = resampled['total_revenue'].rolling(window=window).mean()
        resampled['order_ma'] = resampled['order_count'].rolling(window=window).mean()
        
        self.logger.info(f"Successfully analyzed sales trends over {len(resampled)} periods")
        return resampled
    
    def analyze_cohort_retention(self, orders_df, cohort_period='M', periods=6):
        """
        Analyze customer cohort retention.
        
        Args:
            orders_df (pandas.DataFrame): Orders data with 'customer_id' and 'order_date' columns
            cohort_period (str): Period for cohort grouping ('M' for monthly, 'Q' for quarterly)
            periods (int): Number of periods to analyze
            
        Returns:
            pandas.DataFrame: Cohort retention matrix
        """
        self.logger.info(f"Analyzing cohort retention over {periods} periods")
        
        # Make a copy to avoid modifying the original
        df = orders_df.copy()
        
        # Ensure order_date is datetime
        df['order_date'] = pd.to_datetime(df['order_date'])
        
        # Get the first purchase date for each customer
        first_purchase = df.groupby('customer_id')['order_date'].min().reset_index()
        first_purchase.columns = ['customer_id', 'first_purchase_date']
        
        # Merge with the original dataframe
        df = pd.merge(df, first_purchase, on='customer_id')
        
        # Create cohort groups based on the first purchase date
        if cohort_period == 'M':
            df['cohort'] = df['first_purchase_date'].dt.to_period('M')
        elif cohort_period == 'Q':
            df['cohort'] = df['first_purchase_date'].dt.to_period('Q')
        else:
            raise ValueError(f"Unsupported cohort period: {cohort_period}")
        
        # Calculate the period index (number of periods since first purchase)
        if cohort_period == 'M':
            df['period_index'] = (
                (df['order_date'].dt.year - df['first_purchase_date'].dt.year) * 12 +
                (df['order_date'].dt.month - df['first_purchase_date'].dt.month)
            )
        elif cohort_period == 'Q':
            df['period_index'] = (
                (df['order_date'].dt.year - df['first_purchase_date'].dt.year) * 4 +
                (df['order_date'].dt.quarter - df['first_purchase_date'].dt.quarter)
            )
        
        # Filter to include only the specified number of periods
        df = df[df['period_index'] < periods]
        
        # Count unique customers for each cohort and period
        cohort_data = df.groupby(['cohort', 'period_index']).agg({
            'customer_id': 'nunique'
        }).reset_index()
        
        # Get the total number of customers in each cohort
        cohort_sizes = cohort_data[cohort_data['period_index'] == 0].set_index('cohort')
        
        # Create the retention matrix
        retention_matrix = cohort_data.pivot_table(
            index='cohort',
            columns='period_index',
            values='customer_id'
        )
        
        # Calculate retention rates
        retention_rates = retention_matrix.divide(retention_matrix[0], axis=0)
        
        # Format as percentages
        retention_pct = retention_rates.round(3) * 100
        
        self.logger.info(f"Successfully analyzed retention for {len(retention_pct)} cohorts")
        return retention_pct, cohort_sizes 