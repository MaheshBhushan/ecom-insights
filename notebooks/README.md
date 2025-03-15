# E-commerce Data Analysis Notebooks

This directory contains Jupyter notebooks for exploratory data analysis and visualization of e-commerce data.

## Notebooks

1. `01_data_exploration.ipynb` - Initial exploration of raw data
2. `02_customer_analysis.ipynb` - Analysis of customer behavior and segmentation
3. `03_product_analysis.ipynb` - Analysis of product performance and categories
4. `04_sales_analysis.ipynb` - Analysis of sales trends and patterns
5. `05_cohort_analysis.ipynb` - Customer cohort retention analysis

## Usage

To run these notebooks:

1. Make sure you have installed all the required dependencies:
```bash
pip install -r ../requirements.txt
```

2. Start Jupyter Notebook or Jupyter Lab:
```bash
jupyter notebook
# or
jupyter lab
```

3. Navigate to the notebook you want to run and open it.

## Data Sources

These notebooks expect data to be available in the `../data/` directory, with both raw and processed data subdirectories.

## Exporting Results

Visualizations and analysis results can be exported to the `../reports/` directory using the utility functions provided in the notebooks. 