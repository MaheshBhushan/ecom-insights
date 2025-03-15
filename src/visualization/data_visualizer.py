"""
Data visualization module for the E-commerce Data Pipeline.
"""
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging
from datetime import datetime
from src.config import PATHS
from src.utils import ensure_dir, logger

class DataVisualizer:
    """Class for creating visualizations from e-commerce data."""
    
    def __init__(self, save_path=None):
        """
        Initialize the DataVisualizer.
        
        Args:
            save_path (str, optional): Path to save visualizations
        """
        self.logger = logging.getLogger(__name__)
        
        # Set up save path
        if save_path:
            self.save_path = save_path
        else:
            self.save_path = PATHS['reports']
        
        ensure_dir(self.save_path)
        
        # Set up styling for matplotlib
        plt.style.use('seaborn-v0_8-whitegrid')
        sns.set_palette('viridis')
    
    def save_figure(self, fig, filename, format='png', dpi=300):
        """
        Save a matplotlib figure to file.
        
        Args:
            fig: Matplotlib figure object
            filename (str): Name of the file (without extension)
            format (str): File format ('png', 'pdf', 'svg', 'jpg')
            dpi (int): Resolution for raster formats
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = os.path.join(self.save_path, f"{filename}_{timestamp}.{format}")
        
        fig.savefig(file_path, format=format, dpi=dpi, bbox_inches='tight')
        plt.close(fig)
        
        self.logger.info(f"Saved visualization to {file_path}")
        return file_path
    
    def save_plotly_figure(self, fig, filename, format='html'):
        """
        Save a plotly figure to file.
        
        Args:
            fig: Plotly figure object
            filename (str): Name of the file (without extension)
            format (str): File format ('html', 'png', 'jpg', 'pdf', 'svg')
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if format == 'html':
            file_path = os.path.join(self.save_path, f"{filename}_{timestamp}.html")
            fig.write_html(file_path)
        else:
            file_path = os.path.join(self.save_path, f"{filename}_{timestamp}.{format}")
            fig.write_image(file_path)
        
        self.logger.info(f"Saved interactive visualization to {file_path}")
        return file_path
    
    def plot_sales_trend(self, sales_data, time_column='period', value_column='total_revenue', 
                         title='Sales Trend Over Time', interactive=True):
        """
        Plot sales trend over time.
        
        Args:
            sales_data (pandas.DataFrame): Sales data with time and value columns
            time_column (str): Name of the time column
            value_column (str): Name of the value column
            title (str): Plot title
            interactive (bool): Whether to create an interactive plotly plot
            
        Returns:
            Figure object and path to saved figure
        """
        self.logger.info(f"Creating sales trend visualization for {value_column}")
        
        if interactive:
            # Create interactive plotly figure
            fig = px.line(
                sales_data, 
                x=time_column, 
                y=value_column,
                title=title,
                labels={time_column: 'Time Period', value_column: value_column.replace('_', ' ').title()},
                markers=True
            )
            
            # Add moving average if available
            ma_column = f"{value_column}_ma"
            if ma_column in sales_data.columns:
                fig.add_scatter(
                    x=sales_data[time_column],
                    y=sales_data[ma_column],
                    mode='lines',
                    name='Moving Average',
                    line=dict(color='red', width=2, dash='dash')
                )
            
            # Customize layout
            fig.update_layout(
                template='plotly_white',
                xaxis_title='Time Period',
                yaxis_title=value_column.replace('_', ' ').title(),
                legend_title_text='Metric'
            )
            
            # Save figure
            file_path = self.save_plotly_figure(fig, f"sales_trend_{value_column}")
            
        else:
            # Create matplotlib figure
            fig, ax = plt.subplots(figsize=(12, 6))
            
            # Plot the trend
            ax.plot(sales_data[time_column], sales_data[value_column], marker='o', linestyle='-', label=value_column.replace('_', ' ').title())
            
            # Add moving average if available
            ma_column = f"{value_column}_ma"
            if ma_column in sales_data.columns:
                ax.plot(sales_data[time_column], sales_data[ma_column], 'r--', label='Moving Average')
            
            # Customize plot
            ax.set_title(title, fontsize=16)
            ax.set_xlabel('Time Period', fontsize=12)
            ax.set_ylabel(value_column.replace('_', ' ').title(), fontsize=12)
            ax.tick_params(axis='x', rotation=45)
            ax.grid(True, alpha=0.3)
            ax.legend()
            
            # Adjust layout
            plt.tight_layout()
            
            # Save figure
            file_path = self.save_figure(fig, f"sales_trend_{value_column}")
        
        return fig, file_path
    
    def plot_sales_comparison(self, sales_data, metrics=None, time_column='period', 
                              title='Sales Metrics Comparison', interactive=True):
        """
        Plot multiple sales metrics for comparison.
        
        Args:
            sales_data (pandas.DataFrame): Sales data with time and metrics columns
            metrics (list): List of metric columns to plot
            time_column (str): Name of the time column
            title (str): Plot title
            interactive (bool): Whether to create an interactive plotly plot
            
        Returns:
            Figure object and path to saved figure
        """
        self.logger.info("Creating sales metrics comparison visualization")
        
        # Default metrics if not specified
        if metrics is None:
            metrics = ['total_revenue', 'total_orders', 'unique_customers']
        
        if interactive:
            # Create interactive plotly figure with subplots
            fig = make_subplots(
                rows=len(metrics), 
                cols=1,
                shared_xaxes=True,
                vertical_spacing=0.1,
                subplot_titles=[m.replace('_', ' ').title() for m in metrics]
            )
            
            # Add each metric as a separate subplot
            for i, metric in enumerate(metrics):
                fig.add_trace(
                    go.Scatter(
                        x=sales_data[time_column],
                        y=sales_data[metric],
                        mode='lines+markers',
                        name=metric.replace('_', ' ').title()
                    ),
                    row=i+1, 
                    col=1
                )
            
            # Customize layout
            fig.update_layout(
                height=300 * len(metrics),
                title_text=title,
                template='plotly_white',
                showlegend=False
            )
            
            # Save figure
            file_path = self.save_plotly_figure(fig, "sales_metrics_comparison")
            
        else:
            # Create matplotlib figure with subplots
            fig, axes = plt.subplots(len(metrics), 1, figsize=(12, 5 * len(metrics)), sharex=True)
            
            # Handle case with only one metric
            if len(metrics) == 1:
                axes = [axes]
            
            # Plot each metric
            for i, metric in enumerate(metrics):
                axes[i].plot(sales_data[time_column], sales_data[metric], marker='o', linestyle='-')
                axes[i].set_title(metric.replace('_', ' ').title(), fontsize=14)
                axes[i].set_ylabel(metric.replace('_', ' ').title(), fontsize=12)
                axes[i].grid(True, alpha=0.3)
            
            # Set common x-axis label
            axes[-1].set_xlabel('Time Period', fontsize=12)
            axes[-1].tick_params(axis='x', rotation=45)
            
            # Add overall title
            fig.suptitle(title, fontsize=16)
            
            # Adjust layout
            plt.tight_layout()
            plt.subplots_adjust(top=0.95)
            
            # Save figure
            file_path = self.save_figure(fig, "sales_metrics_comparison")
        
        return fig, file_path
    
    def plot_product_performance(self, product_data, metric='total_revenue', top_n=10, 
                                 title=None, interactive=True):
        """
        Plot product performance.
        
        Args:
            product_data (pandas.DataFrame): Product performance data
            metric (str): Metric to plot
            top_n (int): Number of top products to include
            title (str): Plot title
            interactive (bool): Whether to create an interactive plotly plot
            
        Returns:
            Figure object and path to saved figure
        """
        self.logger.info(f"Creating product performance visualization for top {top_n} products by {metric}")
        
        # Sort and filter top products
        df = product_data.sort_values(metric, ascending=False).head(top_n).copy()
        
        # Create title if not provided
        if title is None:
            title = f"Top {top_n} Products by {metric.replace('_', ' ').title()}"
        
        # Get product names if available, otherwise use product IDs
        if 'product_name' in df.columns:
            df['product_label'] = df['product_name']
        else:
            df['product_label'] = df['product_id']
        
        if interactive:
            # Create interactive plotly figure
            fig = px.bar(
                df,
                x='product_label',
                y=metric,
                title=title,
                labels={'product_label': 'Product', metric: metric.replace('_', ' ').title()},
                color=metric,
                color_continuous_scale='viridis'
            )
            
            # Add category information if available
            if 'category' in df.columns:
                fig = px.bar(
                    df,
                    x='product_label',
                    y=metric,
                    title=title,
                    labels={'product_label': 'Product', metric: metric.replace('_', ' ').title()},
                    color='category',
                    hover_data=['units_sold', 'order_count']
                )
            
            # Customize layout
            fig.update_layout(
                template='plotly_white',
                xaxis_title='Product',
                yaxis_title=metric.replace('_', ' ').title()
            )
            
            # Rotate x-axis labels for better readability
            fig.update_xaxes(tickangle=45)
            
            # Save figure
            file_path = self.save_plotly_figure(fig, f"top_products_{metric}")
            
        else:
            # Create matplotlib figure
            fig, ax = plt.subplots(figsize=(12, 8))
            
            # Create color palette if category information is available
            if 'category' in df.columns:
                categories = df['category'].unique()
                colors = sns.color_palette('viridis', len(categories))
                category_colors = dict(zip(categories, colors))
                bar_colors = [category_colors[cat] for cat in df['category']]
                
                # Create the bar plot
                bars = ax.bar(df['product_label'], df[metric], color=bar_colors)
                
                # Add a legend
                from matplotlib.patches import Patch
                legend_elements = [Patch(facecolor=color, label=cat) for cat, color in category_colors.items()]
                ax.legend(handles=legend_elements, title='Category')
            else:
                # Create a simple bar plot
                bars = ax.bar(df['product_label'], df[metric], color=sns.color_palette('viridis', 1))
            
            # Customize plot
            ax.set_title(title, fontsize=16)
            ax.set_xlabel('Product', fontsize=12)
            ax.set_ylabel(metric.replace('_', ' ').title(), fontsize=12)
            ax.tick_params(axis='x', rotation=45)
            ax.grid(True, alpha=0.3, axis='y')
            
            # Add value labels on top of bars
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                        f'{height:.1f}', ha='center', va='bottom', fontsize=9)
            
            # Adjust layout
            plt.tight_layout()
            
            # Save figure
            file_path = self.save_figure(fig, f"top_products_{metric}")
        
        return fig, file_path
    
    def plot_category_performance(self, category_data, metric='total_revenue', 
                                  title=None, interactive=True):
        """
        Plot category performance.
        
        Args:
            category_data (pandas.DataFrame): Category performance data
            metric (str): Metric to plot
            title (str): Plot title
            interactive (bool): Whether to create an interactive plotly plot
            
        Returns:
            Figure object and path to saved figure
        """
        self.logger.info(f"Creating category performance visualization by {metric}")
        
        # Sort categories by the metric
        df = category_data.sort_values(metric, ascending=False).copy()
        
        # Create title if not provided
        if title is None:
            title = f"Category Performance by {metric.replace('_', ' ').title()}"
        
        if interactive:
            # Create interactive plotly figure
            fig = px.bar(
                df,
                x='category',
                y=metric,
                title=title,
                labels={'category': 'Category', metric: metric.replace('_', ' ').title()},
                color=metric,
                color_continuous_scale='viridis',
                hover_data=['unique_products', 'order_count']
            )
            
            # Customize layout
            fig.update_layout(
                template='plotly_white',
                xaxis_title='Category',
                yaxis_title=metric.replace('_', ' ').title()
            )
            
            # Save figure
            file_path = self.save_plotly_figure(fig, f"category_performance_{metric}")
            
        else:
            # Create matplotlib figure
            fig, ax = plt.subplots(figsize=(12, 6))
            
            # Create the bar plot
            bars = ax.bar(df['category'], df[metric], color=sns.color_palette('viridis', len(df)))
            
            # Customize plot
            ax.set_title(title, fontsize=16)
            ax.set_xlabel('Category', fontsize=12)
            ax.set_ylabel(metric.replace('_', ' ').title(), fontsize=12)
            ax.tick_params(axis='x', rotation=45)
            ax.grid(True, alpha=0.3, axis='y')
            
            # Add value labels on top of bars
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                        f'{height:.1f}', ha='center', va='bottom', fontsize=9)
            
            # Adjust layout
            plt.tight_layout()
            
            # Save figure
            file_path = self.save_figure(fig, f"category_performance_{metric}")
        
        return fig, file_path
    
    def plot_customer_segments(self, customer_segments, segment_profiles, 
                               title='Customer Segments Analysis', interactive=True):
        """
        Plot customer segments.
        
        Args:
            customer_segments (pandas.DataFrame): Customer data with segment labels
            segment_profiles (pandas.DataFrame): Segment profile data
            title (str): Plot title
            interactive (bool): Whether to create an interactive plotly plot
            
        Returns:
            Figure object and path to saved figure
        """
        self.logger.info("Creating customer segments visualization")
        
        if interactive:
            # Create interactive plotly figure with multiple subplots
            fig = make_subplots(
                rows=2, 
                cols=2,
                subplot_titles=[
                    'Segment Distribution',
                    'Average Total Spend by Segment',
                    'Average Order Count by Segment',
                    'Average Order Value by Segment'
                ]
            )
            
            # Segment distribution pie chart
            segment_counts = customer_segments['segment_label'].value_counts().reset_index()
            segment_counts.columns = ['segment_label', 'count']
            
            fig.add_trace(
                go.Pie(
                    labels=segment_counts['segment_label'],
                    values=segment_counts['count'],
                    hole=0.4,
                    textinfo='percent+label'
                ),
                row=1, col=1
            )
            
            # Average total spend by segment
            fig.add_trace(
                go.Bar(
                    x=segment_profiles['segment_label'] if 'segment_label' in segment_profiles.columns else segment_profiles['segment'].astype(str),
                    y=segment_profiles['avg_total_spend'],
                    marker_color='royalblue'
                ),
                row=1, col=2
            )
            
            # Average order count by segment
            fig.add_trace(
                go.Bar(
                    x=segment_profiles['segment_label'] if 'segment_label' in segment_profiles.columns else segment_profiles['segment'].astype(str),
                    y=segment_profiles['avg_order_count'],
                    marker_color='green'
                ),
                row=2, col=1
            )
            
            # Average order value by segment
            fig.add_trace(
                go.Bar(
                    x=segment_profiles['segment_label'] if 'segment_label' in segment_profiles.columns else segment_profiles['segment'].astype(str),
                    y=segment_profiles['avg_order_value'],
                    marker_color='purple'
                ),
                row=2, col=2
            )
            
            # Customize layout
            fig.update_layout(
                height=800,
                title_text=title,
                template='plotly_white',
                showlegend=False
            )
            
            # Save figure
            file_path = self.save_plotly_figure(fig, "customer_segments")
            
        else:
            # Create matplotlib figure with subplots
            fig, axes = plt.subplots(2, 2, figsize=(15, 12))
            
            # Segment distribution pie chart
            segment_counts = customer_segments['segment_label'].value_counts()
            axes[0, 0].pie(segment_counts, labels=segment_counts.index, autopct='%1.1f%%', startangle=90)
            axes[0, 0].set_title('Segment Distribution', fontsize=14)
            
            # Average total spend by segment
            segment_label_col = 'segment_label' if 'segment_label' in segment_profiles.columns else 'segment'
            axes[0, 1].bar(segment_profiles[segment_label_col], segment_profiles['avg_total_spend'], color='royalblue')
            axes[0, 1].set_title('Average Total Spend by Segment', fontsize=14)
            axes[0, 1].set_ylabel('Average Total Spend', fontsize=12)
            axes[0, 1].tick_params(axis='x', rotation=45)
            
            # Average order count by segment
            axes[1, 0].bar(segment_profiles[segment_label_col], segment_profiles['avg_order_count'], color='green')
            axes[1, 0].set_title('Average Order Count by Segment', fontsize=14)
            axes[1, 0].set_ylabel('Average Order Count', fontsize=12)
            axes[1, 0].tick_params(axis='x', rotation=45)
            
            # Average order value by segment
            axes[1, 1].bar(segment_profiles[segment_label_col], segment_profiles['avg_order_value'], color='purple')
            axes[1, 1].set_title('Average Order Value by Segment', fontsize=14)
            axes[1, 1].set_ylabel('Average Order Value', fontsize=12)
            axes[1, 1].tick_params(axis='x', rotation=45)
            
            # Add overall title
            fig.suptitle(title, fontsize=16)
            
            # Adjust layout
            plt.tight_layout()
            plt.subplots_adjust(top=0.9)
            
            # Save figure
            file_path = self.save_figure(fig, "customer_segments")
        
        return fig, file_path
    
    def plot_cohort_retention(self, retention_matrix, cohort_sizes=None,
                              title='Customer Cohort Retention Analysis', interactive=True):
        """
        Plot cohort retention heatmap.
        
        Args:
            retention_matrix (pandas.DataFrame): Cohort retention matrix
            cohort_sizes (pandas.DataFrame, optional): Cohort sizes
            title (str): Plot title
            interactive (bool): Whether to create an interactive plotly plot
            
        Returns:
            Figure object and path to saved figure
        """
        self.logger.info("Creating cohort retention visualization")
        
        if interactive:
            # Create interactive plotly figure
            fig = px.imshow(
                retention_matrix,
                labels=dict(x="Period", y="Cohort", color="Retention Rate (%)"),
                x=retention_matrix.columns,
                y=retention_matrix.index.astype(str),
                color_continuous_scale='viridis',
                aspect='auto',
                title=title
            )
            
            # Add text annotations
            for i, cohort in enumerate(retention_matrix.index):
                for j, period in enumerate(retention_matrix.columns):
                    value = retention_matrix.iloc[i, j]
                    if not pd.isna(value):
                        fig.add_annotation(
                            x=period,
                            y=cohort,
                            text=f"{value:.1f}%",
                            showarrow=False,
                            font=dict(color='white' if value > 50 else 'black')
                        )
            
            # Add cohort sizes if provided
            if cohort_sizes is not None:
                cohort_labels = [f"{cohort} (n={size})" for cohort, size in 
                                zip(cohort_sizes.index.astype(str), cohort_sizes['customer_id'])]
                fig.update_layout(yaxis=dict(ticktext=cohort_labels, tickvals=retention_matrix.index))
            
            # Customize layout
            fig.update_layout(
                template='plotly_white',
                xaxis_title='Periods Since First Purchase',
                yaxis_title='Cohort'
            )
            
            # Save figure
            file_path = self.save_plotly_figure(fig, "cohort_retention")
            
        else:
            # Create matplotlib figure
            fig, ax = plt.subplots(figsize=(12, 8))
            
            # Create the heatmap
            sns.heatmap(
                retention_matrix,
                annot=True,
                fmt='.1f',
                cmap='viridis',
                cbar_kws={'label': 'Retention Rate (%)'},
                ax=ax
            )
            
            # Customize plot
            ax.set_title(title, fontsize=16)
            ax.set_xlabel('Periods Since First Purchase', fontsize=12)
            ax.set_ylabel('Cohort', fontsize=12)
            
            # Add cohort sizes if provided
            if cohort_sizes is not None:
                cohort_labels = [f"{cohort} (n={size})" for cohort, size in 
                                zip(cohort_sizes.index.astype(str), cohort_sizes['customer_id'])]
                ax.set_yticklabels(cohort_labels)
            
            # Adjust layout
            plt.tight_layout()
            
            # Save figure
            file_path = self.save_figure(fig, "cohort_retention")
        
        return fig, file_path
    
    def create_dashboard(self, sales_data, product_data, category_data, customer_data):
        """
        Create a comprehensive dashboard with multiple visualizations.
        
        Args:
            sales_data (pandas.DataFrame): Sales trend data
            product_data (pandas.DataFrame): Product performance data
            category_data (pandas.DataFrame): Category performance data
            customer_data (pandas.DataFrame): Customer behavior data
            
        Returns:
            List of paths to saved figures
        """
        self.logger.info("Creating comprehensive dashboard")
        
        # Create a list to store all figure paths
        figure_paths = []
        
        # 1. Sales trend visualization
        fig, path = self.plot_sales_trend(
            sales_data, 
            time_column='period', 
            value_column='total_revenue',
            title='Sales Revenue Trend Over Time',
            interactive=True
        )
        figure_paths.append(path)
        
        # 2. Sales metrics comparison
        fig, path = self.plot_sales_comparison(
            sales_data,
            metrics=['total_revenue', 'total_orders', 'unique_customers'],
            time_column='period',
            title='Sales Metrics Comparison',
            interactive=True
        )
        figure_paths.append(path)
        
        # 3. Top products visualization
        fig, path = self.plot_product_performance(
            product_data,
            metric='total_revenue',
            top_n=10,
            title='Top 10 Products by Revenue',
            interactive=True
        )
        figure_paths.append(path)
        
        # 4. Category performance visualization
        fig, path = self.plot_category_performance(
            category_data,
            metric='total_revenue',
            title='Category Performance by Revenue',
            interactive=True
        )
        figure_paths.append(path)
        
        # 5. Customer segments visualization (if available)
        if 'segment' in customer_data.columns:
            # Calculate segment profiles
            segment_profiles = customer_data.groupby('segment').agg({
                'customer_id': 'count',
                'order_count': 'mean',
                'total_spend': 'mean',
                'average_order_value': 'mean'
            }).reset_index()
            
            segment_profiles.columns = [
                'segment',
                'customer_count',
                'avg_order_count',
                'avg_total_spend',
                'avg_order_value'
            ]
            
            fig, path = self.plot_customer_segments(
                customer_data,
                segment_profiles,
                title='Customer Segments Analysis',
                interactive=True
            )
            figure_paths.append(path)
        
        self.logger.info(f"Successfully created dashboard with {len(figure_paths)} visualizations")
        return figure_paths 