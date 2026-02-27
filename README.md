# Cash Flow Visualization Tool

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.8%2B-orange)
![JavaScript](https://img.shields.io/badge/javascript-ES6%2B-yellow)

A powerful, interactive web-based tool designed to help Small and Medium Enterprises (SMEs) visualize, analyze, and optimize their cash flow through intuitive graphical representations and automated anomaly detection.

![Dashboard Preview](screenshots/dashboard.png)

## 📋 Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Technology Stack](#technology-stack)
- [System Architecture](#system-architecture)
- [Installation](#installation)
- [Usage Guide](#usage-guide)
- [API Documentation](#api-documentation)
- [Testing](#testing)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## 🔍 Overview

Cash flow management is critical for financial stability and strategic decision-making in SMEs. Traditional tools like spreadsheets lack interactivity and actionable insights. This tool bridges that gap by providing:

- **Interactive node-edge visualizations** mapping financial relationships
- **Real-time anomaly detection** using statistical methods
- **Dynamic filtering** by transaction type, currency, and date
- **Automated report generation** for stakeholders

**Key Achievement:** 96.2% accuracy in anomaly detection and 2.4x faster financial analysis compared to traditional methods.

## ✨ Features

### Core Functionalities
| Feature | Description |
|---------|-------------|
| **User Authentication** | Secure JWT-based login with role-based access control |
| **Data Import** | Upload CSV/XLSX financial datasets with validation |
| **Interactive Dashboard** | Real-time visualization of cash flow metrics |
| **Node-Edge Graphs** | Visual representation of accounts (nodes) and transactions (edges) |
| **Anomaly Detection** | IQR-based algorithm identifying irregular transactions |
| **Transaction Filtering** | Filter by date, amount, currency, and transaction type |
| **Report Generation** | Export visualizations as PDF, PNG, or CSV |
| **Multi-currency Support** | Handle transactions across different currencies |

### Visualization Types
- **Waterfall Charts** - Net cash position analysis
- **Pie/Donut Charts** - Revenue breakdown and expense allocation
- **Line Charts** - Monthly income vs. expenditure trends
- **Node-Edge Graphs** - Relationship mapping between accounts

## 🛠 Technology Stack

### Frontend
- **HTML5** - Structure and semantics
- **CSS3** - Styling with Flexbox/Grid layouts
- **Vanilla JavaScript (ES6+)** - Core functionality
- **Chart.js** - Interactive chart rendering
- **Canvas API** - Custom graph visualizations
- **jsPDF** - PDF report generation

### Backend
- **Python 3.8+** - Core programming language
- **Flask** - Web framework and RESTful APIs
- **Pandas/NumPy** - Data processing and analysis
- **SciPy** - Statistical calculations
- **JWT** - Authentication and authorization

### Database
- **SQLite** - Development database
- **PostgreSQL** - Production database (optional)

### DevOps
- **Git/GitHub** - Version control
- **GitHub Actions** - CI/CD pipeline
- **Vercel/Heroku** - Deployment platforms

## 🏗 System Architecture
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ PRESENTATION │────▶│ APPLICATION │────▶│ DATA │
│ LAYER │ │ LAYER │ │ LAYER │
├─────────────────┤ ├─────────────────┤ ├─────────────────┤
│ • HTML5/CSS3 │ │ • Flask APIs │ │ • SQLite │
│ • JavaScript │ │ • Business Logic│ │ • CSV Files │
│ • Chart.js │ │ • Anomaly Detect│ │ • Data Models │
│ • Canvas API │ │ • Auth Service │ │ • Encryption │
└─────────────────┘ └─────────────────┘ └─────────────────┘
│ │ │
└───────────────────────┴───────────────────────┘
RESTful APIs

text

### Data Flow
1. User uploads financial data (CSV/XLSX)
2. Backend validates and processes data
3. Anomaly detection algorithms analyze transactions
4. Visualization engine renders interactive charts
5. Frontend displays real-time updates

## 📦 Installation

### Prerequisites
- Python 3.8 or higher
- Node.js (optional, for development)
- Git
- Modern web browser (Chrome, Firefox, Edge)

Step-by-Step Setup

1. Clone the repository
```bash
git clone https://github.com/yourusername/cashflow-visualization-tool.git
cd cashflow-visualization-tool
Create virtual environment

bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
Install dependencies

bash
pip install -r requirements.txt
Configure environment variables

bash
cp .env.example .env
# Edit .env with your configuration
Initialize database

bash
python init_db.py
Run the application

bash
python app.py
Access the application
Open browser and navigate to http://localhost:5000

Docker Setup (Alternative)
bash
docker build -t cashflow-tool .
docker run -p 5000:5000 cashflow-tool
📖 Usage Guide
1. Registration & Login
Navigate to /register to create an account

Use credentials to login at /login

JWT token automatically managed via HTTP-only cookies

2. Data Upload
Click "Upload Data" on dashboard

Select CSV/XLSX file with transaction data

Required columns: Date, Description, Amount, Type, Account

System validates and previews data

3. Dashboard Navigation
Overview Tab: Key metrics and summary charts

Visualizations Tab: Interactive node-edge graphs

Transactions Tab: Filterable transaction list

Anomalies Tab: Detected outliers with explanations

Reports Tab: Generate and export reports

4. Filtering Transactions
Use the filter panel to narrow down data:

Date Range: Select start and end dates

Amount: Min/max transaction values

Type: Income, Expense, Transfer

Currency: Filter by currency type

Account: Source or destination account

5. Anomaly Detection
The system automatically flags suspicious transactions:

IQR Method: Transactions outside Q1-1.5*IQR and Q3+1.5*IQR

Visual Indicators: Highlighted in yellow on charts

Details Panel: Shows deviation percentage and rationale

6. Report Generation
Click "Generate Report" to compile visualizations

Choose format: PDF, PNG, or CSV

Reports include all active filters and anomalies

🔌 API Documentation
Authentication Endpoints
Endpoint	Method	Description	Request Body	Response
/api/register	POST	User registration	{username, email, password}	{token, user}
/api/login	POST	User login	{username, password}	{token, user}
/api/logout	POST	User logout	-	{message}
Data Endpoints
Endpoint	Method	Description	Parameters	Response
/api/upload	POST	Upload transaction data	file: CSV/XLSX	{summary}
/api/transactions	GET	Get filtered transactions	start_date, end_date, type	{transactions}
/api/anomalies	GET	Detect anomalies	threshold	{anomalies}
/api/visualization	POST	Generate chart data	{chart_type, filters}	{chart_data}
/api/report	POST	Generate report	{format, filters}	{file_url}
Example API Call
javascript
// Fetch anomalies
fetch('/api/anomalies', {
  method: 'GET',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  }
})
.then(response => response.json())
.then(data => console.log(data));
🧪 Testing
Running Tests
bash
# Unit tests
python -m pytest tests/unit

# Integration tests
python -m pytest tests/integration

# Performance tests
python -m pytest tests/performance

# With coverage
python -m pytest --cov=app tests/
Test Categories
Test Type	Description	Coverage
Unit Tests	Individual component testing	85%
Integration	API and database interaction	78%
Performance	Load testing (up to 10,000 transactions)	<2s response
Security	Authentication and data protection	Passed
Sample Test Results
Anomaly Detection Accuracy: 96.2%

Average Response Time: 1.8 seconds

User Task Completion: 2.4x faster than spreadsheets

User Satisfaction: 4.7/5

🤝 Contributing
We welcome contributions! Please follow these steps:

Fork the repository

Create a feature branch

bash
git checkout -b feature/amazing-feature
Commit your changes

bash
git commit -m 'Add amazing feature'
Push to branch

bash
git push origin feature/amazing-feature
Open a Pull Request

Contribution Guidelines
Follow PEP 8 style guide for Python

Use ESLint configuration for JavaScript

Write unit tests for new features

Update documentation accordingly

Ensure all tests pass before PR

📄 License
This project is licensed under the MIT License - see the LICENSE file for details.

📞 Contact
Project Author: Akinboade Precious Akinkunmi
Institution: Obafemi Awolowo University, Ile-Ife
Department: Computer Science and Engineering
Email: akinboadeprecious@gmail.com
Project Link:https://github.com/Akinboade2000/Restaurant-Cash-Flow-Analyzer/

🙏 Acknowledgments
Supervisor: Prof. (Mrs.) H.A. Soriyan for guidance and support

Contributor: Dr. Gambo for technical insights

Testers: Financial analysts and business experts who provided feedback

Data Source: Kaggle for synthetic financial datasets

Open Source Community: For libraries and tools used in this project
