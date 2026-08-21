# E-commerce Data Pipeline

![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)

A robust Python-based data pipeline for analyzing e-commerce transactions. This project focuses on data extraction, transformation, and visualization to provide key insights into consumer behavior and sales performance.

## Project Structure

- `data/`: Raw and processed data files
- `src/`: Source code for the data pipeline
  - `extraction/`: Scripts for extracting data from various sources
  - `transformation/`: Scripts for cleaning and transforming data
  - `analysis/`: Scripts for data analysis and generating insights
  - `visualization/`: Scripts for creating visualizations
- `sql/`: SQL scripts for database setup and queries
- `reports/`: Generated reports and visualizations
- `requirements.txt`: Project dependencies

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure database settings in `config.py`

4. Run the pipeline:
```bash
python src/main.py
```

## Features

- Comprehensive data cleaning and transformation
- Advanced analytics for customer segmentation and product performance
- Visualizations for sales trends and customer behavior

## Technologies Used

- Python
- Pandas & NumPy
- SQL
- Matplotlib/Seaborn/Plotly 
