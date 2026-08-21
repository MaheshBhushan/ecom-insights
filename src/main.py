"""
Main module for the E-commerce Data Pipeline.
"""
import os
import argparse
import logging
import pandas as pd
from datetime import datetime, timedelta
import sys

# Add the project root directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from src.config import PATHS, DATA_ANCHOR_DATE
from src.utils import setup_logging, ensure_dir, save_dataframe
from src.extraction.data_extractor import DataExtractor
from src.transformation.data_transformer import DataTransformer
from src.analysis.data_analyzer import DataAnalyzer
from src.visualization.data_visualizer import DataVisualizer

# Set up logging
logger = setup_logging()

def run_pipeline(data_source='sample', start_date=None, end_date=None):
    """
    Run the complete data pipeline.
    
    Args:
        data_source (str): Source of data ('sample', 'database', 'api')
        start_date (str): Start date for data extraction (format: YYYY-MM-DD)
        end_date (str): End date for data extraction (format: YYYY-MM-DD)
    """
    logger.info(f"Starting E-commerce data pipeline with source: {data_source}")
    
    # Initialize components
    extractor = DataExtractor()
    transformer = DataTransformer()
    analyzer = DataAnalyzer()
    visualizer = DataVisualizer()
    
    # Set default date range if not provided
    if not end_date:
        end_date = DATA_ANCHOR_DATE
    if not start_date:
        start_date = (datetime.strptime(DATA_ANCHOR_DATE, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d')
    
    logger.info(f"Processing data from {start_date} to {end_date}")
    
    try:
        # Step 1: Extract data
        logger.info("Step 1: Extracting data")
        
        if data_source == 'sample':
            # Use sample data files
            orders_file = os.path.join(PATHS['raw_data'], 'orders.csv')
            customers_file = os.path.join(PATHS['raw_data'], 'customers.csv')
            products_file = os.path.join(PATHS['raw_data'], 'products.csv')
            order_items_file = os.path.join(PATHS['raw_data'], 'order_items.csv')
            
            # Check if sample files exist, otherwise create dummy data
            if not all(os.path.exists(f) for f in [orders_file, customers_file, products_file, order_items_file]):
                logger.warning("Sample files not found. Creating dummy data for demonstration.")
                create_dummy_data()
            
            # Extract data from CSV files
            orders_df = extractor.extract_from_csv(orders_file)
            customers_df = extractor.extract_from_csv(customers_file)
            products_df = extractor.extract_from_csv(products_file)
            order_items_df = extractor.extract_from_csv(order_items_file)
            
        elif data_source == 'database':
            # Extract data from database
            orders_query = f"SELECT * FROM orders WHERE order_date BETWEEN '{start_date}' AND '{end_date}'"
            customers_query = "SELECT * FROM customers"
            products_query = "SELECT * FROM products"
            order_items_query = """
                SELECT oi.* FROM order_items oi
                JOIN orders o ON oi.order_id = o.order_id
                WHERE o.order_date BETWEEN '{start_date}' AND '{end_date}'
            """
            
            orders_df = extractor.extract_from_database(orders_query)
            customers_df = extractor.extract_from_database(customers_query)
            products_df = extractor.extract_from_database(products_query)
            order_items_df = extractor.extract_from_database(order_items_query)
            
        elif data_source == 'api':
            # Extract data from API
            orders_df = extractor.extract_from_api('orders', params={'start_date': start_date, 'end_date': end_date})
            customers_df = extractor.extract_from_api('customers')
            products_df = extractor.extract_from_api('products')
            order_items_df = extractor.extract_from_api('order-items', params={'start_date': start_date, 'end_date': end_date})
            
        else:
            raise ValueError(f"Unsupported data source: {data_source}")
        
        # Step 2: Transform data
        logger.info("Step 2: Transforming data")
        
        orders_transformed = transformer.transform_orders_data(orders_df)
        customers_transformed = transformer.transform_customers_data(customers_df)
        products_transformed = transformer.transform_products_data(products_df)
        order_items_transformed = transformer.transform_order_items_data(order_items_df)
        
        # Join data for analysis
        orders_with_customers = transformer.join_orders_with_customers(orders_transformed, customers_transformed)
        order_items_with_products = transformer.join_order_items_with_products(order_items_transformed, products_transformed)
        
        # Create sales summary
        sales_summary = transformer.create_sales_summary(orders_transformed, order_items_transformed, products_transformed)
        
        # Save transformed data
        save_dataframe(orders_transformed, 'orders_transformed')
        save_dataframe(customers_transformed, 'customers_transformed')
        save_dataframe(products_transformed, 'products_transformed')
        save_dataframe(order_items_transformed, 'order_items_transformed')
        save_dataframe(sales_summary, 'sales_summary')
        
        # Step 3: Analyze data
        logger.info("Step 3: Analyzing data")
        
        # Calculate sales metrics
        daily_metrics = analyzer.calculate_sales_metrics(orders_transformed, time_period='daily')
        weekly_metrics = analyzer.calculate_sales_metrics(orders_transformed, time_period='weekly')
        monthly_metrics = analyzer.calculate_sales_metrics(orders_transformed, time_period='monthly')
        
        # Analyze product performance
        product_performance = analyzer.analyze_product_performance(order_items_transformed, products_transformed)
        
        # Analyze category performance
        category_performance = analyzer.analyze_category_performance(order_items_transformed, products_transformed)
        
        # Analyze customer behavior
        customer_behavior = analyzer.analyze_customer_behavior(orders_transformed, customers_transformed)
        
        # Segment customers
        customer_segments, segment_profiles = analyzer.segment_customers(customer_behavior, n_segments=3)
        
        # Analyze sales trends
        sales_trends = analyzer.analyze_sales_trends(orders_transformed, period='M', periods=12)
        
        # Analyze cohort retention
        retention_matrix, cohort_sizes = analyzer.analyze_cohort_retention(orders_transformed, cohort_period='M', periods=6)
        
        # Save analysis results
        save_dataframe(daily_metrics, 'daily_metrics')
        save_dataframe(weekly_metrics, 'weekly_metrics')
        save_dataframe(monthly_metrics, 'monthly_metrics')
        save_dataframe(product_performance, 'product_performance')
        save_dataframe(category_performance, 'category_performance')
        save_dataframe(customer_segments, 'customer_segments')
        save_dataframe(segment_profiles, 'segment_profiles')
        save_dataframe(sales_trends, 'sales_trends')
        save_dataframe(retention_matrix, 'retention_matrix')
        
        # Step 4: Visualize data
        logger.info("Step 4: Creating visualizations")
        
        # Create sales trend visualizations
        visualizer.plot_sales_trend(sales_trends, time_column='period', value_column='total_revenue')
        visualizer.plot_sales_trend(sales_trends, time_column='period', value_column='order_count')
        
        # Create sales comparison visualization
        visualizer.plot_sales_comparison(sales_trends, metrics=['total_revenue', 'order_count', 'unique_customers'])
        
        # Create product performance visualization
        visualizer.plot_product_performance(product_performance, metric='total_revenue', top_n=10)
        
        # Create category performance visualization
        visualizer.plot_category_performance(category_performance, metric='total_revenue')
        
        # Create customer segments visualization
        visualizer.plot_customer_segments(customer_segments, segment_profiles)
        
        # Create cohort retention visualization
        visualizer.plot_cohort_retention(retention_matrix, cohort_sizes)
        
        # Create comprehensive dashboard
        visualizer.create_dashboard(sales_trends, product_performance, category_performance, customer_segments)
        
        logger.info("Data pipeline completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error in data pipeline: {str(e)}")
        raise
    
def create_dummy_data():
    """Create dummy data for demonstration purposes."""
    logger.info("Creating dummy data for demonstration")
    
    # Ensure raw data directory exists
    ensure_dir(PATHS['raw_data'])
    
    # Generate dates
    end_date = datetime.strptime(DATA_ANCHOR_DATE, '%Y-%m-%d')
    start_date = end_date - timedelta(days=365)
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    
    # Create customers data
    customers = []
    for i in range(1, 101):
        registration_date = start_date + timedelta(days=i % 300)
        customers.append({
            'customer_id': f'CUST{i:05d}',
            'first_name': f'FirstName{i}',
            'last_name': f'LastName{i}',
            'email': f'customer{i}@example.com',
            'registration_date': registration_date.strftime('%Y-%m-%d'),
            'country': ['US', 'UK', 'CA', 'AU', 'DE'][i % 5]
        })
    customers_df = pd.DataFrame(customers)
    
    # Create products data
    products = []
    categories = ['Electronics', 'Clothing', 'Home', 'Books', 'Sports']
    for i in range(1, 51):
        category = categories[i % 5]
        price = 10 + (i % 10) * 15
        cost = price * 0.6
        products.append({
            'product_id': f'PROD{i:05d}',
            'product_name': f'Product {i}',
            'description': f'Description for Product {i}',
            'category': category,
            'price': price,
            'cost': cost,
            'brand': f'Brand{(i % 10) + 1}'
        })
    products_df = pd.DataFrame(products)
    
    # Create order headers (financial fields are derived from line items below,
    # so orders reconcile exactly with order_items instead of being invented
    # independently)
    order_headers = []
    order_statuses = ['Completed', 'Shipped', 'Processing', 'Cancelled']
    payment_methods = ['Credit Card', 'PayPal', 'Bank Transfer']
    shipping_methods = ['Standard', 'Express', 'Next Day']
    
    order_id = 1
    for date in date_range:
        # Generate 1-5 orders per day
        num_orders = (date.day % 5) + 1
        for _ in range(num_orders):
            customer_id = f'CUST{(order_id % 100) + 1:05d}'
            shipping_cost = 5 + (order_id % 3) * 5
            
            order_headers.append({
                'order_id': f'ORD{order_id:06d}',
                'customer_id': customer_id,
                'order_date': date.strftime('%Y-%m-%d'),
                'order_status': order_statuses[order_id % 4],
                'shipping_cost': shipping_cost,
                'payment_method': payment_methods[order_id % 3],
                'shipping_method': shipping_methods[order_id % 3]
            })
            order_id += 1
    
    # Create order items data first, since each order's totals are derived from them
    order_items = []
    item_id = 1
    for header in order_headers:
        order_id = header['order_id']
        # Generate 1-3 items per order
        num_items = (int(order_id[-2:]) % 3) + 1
        for i in range(num_items):
            product_id = f'PROD{((item_id + i) % 50) + 1:05d}'
            product_price = products_df.loc[products_df['product_id'] == product_id, 'price'].values[0]
            quantity = (item_id % 3) + 1
            discount_rate = [0, 0.05, 0.1, 0.15][item_id % 4]
            
            order_items.append({
                'item_id': f'ITEM{item_id:07d}',
                'order_id': order_id,
                'product_id': product_id,
                'quantity': quantity,
                'price': product_price,
                'discount_rate': discount_rate
            })
            item_id += 1
    order_items_df = pd.DataFrame(order_items)
    
    # Derive each order's subtotal from its own line items, then compute
    # order_total = subtotal + shipping_cost + tax so orders and order_items
    # reconcile exactly
    subtotal_by_order = {}
    for item in order_items:
        subtotal_by_order[item['order_id']] = subtotal_by_order.get(item['order_id'], 0) + item['quantity'] * item['price']
    
    orders = []
    for header in order_headers:
        order_subtotal = subtotal_by_order[header['order_id']]
        tax = order_subtotal * 0.1
        order_total = order_subtotal + header['shipping_cost'] + tax
        orders.append({
            'order_id': header['order_id'],
            'customer_id': header['customer_id'],
            'order_date': header['order_date'],
            'order_status': header['order_status'],
            'order_total': order_total,
            'shipping_cost': header['shipping_cost'],
            'tax': tax,
            'payment_method': header['payment_method'],
            'shipping_method': header['shipping_method']
        })
    orders_df = pd.DataFrame(orders)
    
    # Save dummy data to CSV files
    customers_df.to_csv(os.path.join(PATHS['raw_data'], 'customers.csv'), index=False)
    products_df.to_csv(os.path.join(PATHS['raw_data'], 'products.csv'), index=False)
    orders_df.to_csv(os.path.join(PATHS['raw_data'], 'orders.csv'), index=False)
    order_items_df.to_csv(os.path.join(PATHS['raw_data'], 'order_items.csv'), index=False)
    
    logger.info("Dummy data created successfully")

def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(description='E-commerce Data Pipeline')
    parser.add_argument('--source', choices=['sample', 'database', 'api'], default='sample',
                        help='Source of data (sample, database, api)')
    parser.add_argument('--start-date', help='Start date for data extraction (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date for data extraction (YYYY-MM-DD)')
    parser.add_argument('--load', action='store_true',
                        help='Load the transformed data into the warehouse (star schema). Runs after the pipeline unless --load-only is given')
    parser.add_argument('--load-only', action='store_true',
                        help='Load already-transformed data into the warehouse without re-running the pipeline')

    args = parser.parse_args()

    if not args.load_only:
        run_pipeline(data_source=args.source, start_date=args.start_date, end_date=args.end_date)

    if args.load or args.load_only:
        from src.load.warehouse_loader import run_warehouse_load, ValidationError
        try:
            run_warehouse_load()
        except ValidationError as exc:
            logger.error(f"Warehouse load validation failed: {exc}")
            print(f"Warehouse load validation failed: {exc}", file=sys.stderr)
            sys.exit(1)

if __name__ == '__main__':
    main() 