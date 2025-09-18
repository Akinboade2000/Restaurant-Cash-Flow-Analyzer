from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from model import db, User, Restaurant, Transaction, Report
from datetime import datetime, timedelta
import pandas as pd
from io import BytesIO
import numpy as np
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import matplotlib.pyplot as plt
import seaborn as sns
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Image
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
import base64
import json
import requests


app = Flask(__name__, template_folder='../frontend/templates', static_folder='../frontend/static')
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///restaurant_cashflow.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'your-secret-key'  # Change in production
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_SECURE'] = False  # True in production
app.config['JWT_COOKIE_CSRF_PROTECT'] = False  # Enable CSRF protection in production
jwt = JWTManager(app)
db.init_app(app)

# Helper functions
def detect_anomalies(transactions):
    df = pd.DataFrame([{
        'id': t.id,
        'amount': t.amount,
        'date': t.date,
        'category': t.category,
        'type': t.type,
        'is_anomaly': t.is_anomaly  # Track if already marked as anomaly
    } for t in transactions])
    
    anomalies = []
    for category in df['category'].unique():
        for ttype in df[df['category'] == category]['type'].unique():
            subset = df[(df['category'] == category) & (df['type'] == ttype) & (~df['is_anomaly'])]
            
            # Skip if not enough data points
            if len(subset) < 3:
                continue
                
            q1 = subset['amount'].quantile(0.25)
            q3 = subset['amount'].quantile(0.75)
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr
            
            for _, row in subset.iterrows():
                if row['amount'] < lower_bound or row['amount'] > upper_bound:
                    anomalies.append({
                        'id': row['id'],
                        'amount': row['amount'],
                        'date': row['date'],
                        'category': category,
                        'type': ttype,
                        'reason': 'IQR outlier'
                    })
                    # Mark as anomaly in database
                    transaction = Transaction.query.get(row['id'])
                    if transaction:
                        transaction.is_anomaly = True
                        db.session.commit()
    
    return anomalies

# Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/dashboard')
@jwt_required()
def dashboard():
    current_user_id = get_jwt_identity()  
    return render_template('dashboard.html')

@app.route('/api/verify-auth')
@jwt_required()
def verify_auth():
    return jsonify({'message': 'Authenticated'}), 200

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        
        # Validate required fields
        if not all(k in data for k in ['username', 'email', 'password']):
            return jsonify({'message': 'Missing required fields'}), 400
            
        # Check if user already exists
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'message': 'Username already exists'}), 400
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'message': 'Email already exists'}), 400
            
        # Create new user
        hashed_password = generate_password_hash(data['password'])
        new_user = User(
            username=data['username'],
            email=data['email'],
            password=hashed_password
        )
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({
            'message': 'User created successfully',
            'user': {
                'id': new_user.id,
                'username': new_user.username,
                'email': new_user.email
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    if not request.is_json:
        return jsonify({"message": "Missing JSON in request"}), 400
        
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"message": "Missing username or password"}), 400

    user = User.query.filter_by(username=username).first()
    
    if user and check_password_hash(user.password, password):
        # Create token with string identity
        access_token = create_access_token(identity=str(user.id))  # Convert to string
        response = jsonify({
            "message": "Login successful",
            "user": {
                "id": user.id,
                "username": user.username
            }
        })
        response.set_cookie(
            'access_token_cookie',
            access_token,
            httponly=True,
            secure=False,  # True in production with HTTPS
            samesite='Lax'
        )
        return response, 200
    
    return jsonify({"message": "Invalid credentials"}), 401

@app.route('/api/restaurants', methods=['GET', 'POST'])
@jwt_required()
def restaurants():
    user_id = get_jwt_identity()
    if request.method == 'POST':
        data = request.get_json()
        new_restaurant = Restaurant(name=data['name'], user_id=user_id)
        db.session.add(new_restaurant)
        db.session.commit()
        return jsonify({'message': 'Restaurant created successfully'}), 201
    else:
        restaurants = Restaurant.query.filter_by(user_id=user_id).all()
        return jsonify([{'id': r.id, 'name': r.name} for r in restaurants]), 200

@app.route('/api/transactions', methods=['GET', 'POST'])
@jwt_required()
def transactions():
    restaurant_id = request.args.get('restaurant_id')
    if not restaurant_id:
        return jsonify({'message': 'Restaurant ID is required'}), 400
    
    if request.method == 'POST':
        data = request.get_json()
        new_transaction = Transaction(
            restaurant_id=restaurant_id,
            date=datetime.strptime(data['date'], '%Y-%m-%d'),
            amount=data['amount'],
            currency=data.get('currency', 'USD'),
            category=data['category'],
            type=data['type'],
            description=data.get('description', '')
        )
        db.session.add(new_transaction)
        db.session.commit()
        return jsonify({'message': 'Transaction added successfully'}), 201
    else:
        transactions = Transaction.query.filter_by(restaurant_id=restaurant_id).all()
        return jsonify([{
            'id': t.id,
            'date': t.date.isoformat(),
            'amount': t.amount,
            'currency': t.currency,
            'category': t.category,
            'type': t.type,
            'description': t.description,
            'is_anomaly': t.is_anomaly
        } for t in transactions]), 200

@app.route('/api/upload', methods=['POST'])
@jwt_required()
def upload():
    user_id = get_jwt_identity()
    
    # Get or create restaurant for the user
    restaurant = Restaurant.query.filter_by(user_id=user_id).first()
    if not restaurant:
        # Create a default restaurant if none exists
        restaurant = Restaurant(name="My Restaurant", user_id=user_id)
        db.session.add(restaurant)
        db.session.commit()
    Transaction.query.filter_by(restaurant_id=restaurant.id).delete()
    db.session.commit()
    if 'file' not in request.files:
        return jsonify({'message': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'message': 'No file selected'}), 400
    
    # Check file extension
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.csv')):
        return jsonify({'message': 'Invalid file type. Please upload a CSV or Excel file.'}), 400
    
    try:
        # Read the file based on extension
        if file.filename.endswith('.xlsx'):
            df = pd.read_excel(file)
        else:
            df = pd.read_csv(file)
        
        # Check for required columns
        required_columns = ['date', 'amount', 'category', 'type']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            return jsonify({
                'message': f'Missing required columns: {", ".join(missing_columns)}'
            }), 400
        
        # Process each row
        success_count = 0
        error_count = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                # Parse date (handle different formats)
                date_str = str(row['date']).strip()
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    try:
                        date_obj = datetime.strptime(date_str, '%d/%m/%Y')
                    except ValueError:
                        try:
                            date_obj = datetime.strptime(date_str, '%m/%d/%Y')
                        except ValueError:
                            # If all else fails, use today's date
                            date_obj = datetime.now()
                            errors.append(f"Row {index+1}: Invalid date format '{date_str}', used today's date")
                
                # Create new transaction
                new_transaction = Transaction(
                    restaurant_id=restaurant.id,
                    date=date_obj,
                    amount=float(row['amount']),
                    currency=row.get('currency', 'USD'),
                    category=row['category'].strip().lower(),
                    type=row['type'].strip(),
                    description=row.get('description', '')
                )
                db.session.add(new_transaction)
                success_count += 1
                
            except Exception as e:
                error_count += 1
                errors.append(f"Row {index+1}: {str(e)}")
        
        db.session.commit()
        
        message = f'Successfully processed {success_count} transactions'
        if error_count > 0:
            message += f' with {error_count} errors'
        
        return jsonify({
            'message': message,
            'success_count': success_count,
            'error_count': error_count,
            'errors': errors if errors else None,
            'restaurant_id': restaurant.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Upload error: {str(e)}")
        return jsonify({'message': f'Error processing file: {str(e)}'}), 400

@app.route('/api/visualizations/', methods=['GET'])
@jwt_required()
def visualizations():
    try:
        restaurant_id = request.args.get('restaurant_id')
        
        if not restaurant_id:
            return jsonify({'error': 'restaurant_id is required'}), 400

        # Verify restaurant exists and belongs to user
        restaurant = Restaurant.query.filter_by(
            id=restaurant_id,
            user_id=get_jwt_identity()
        ).first()
        
        if not restaurant:
            return jsonify({'error': 'Restaurant not found'}), 404

        # Get transactions
        transactions = Transaction.query.filter_by(
            restaurant_id=restaurant.id
        ).all()
        
        if not transactions:
            return jsonify({
                'message': 'No transactions found',
                'waterfall': {'revenue': 0, 'expenses': 0, 'net_cash': 0},
                'revenue_breakdown': {},
                'expense_breakdown': {},
                'monthly_trends': {'revenue': {}, 'expense': {}},
                'anomalies': [],
                'company_vs_franchise': {'Company Revenue': 0, 'Franchise Revenue': 0},
                'eps_dividend': {'months': [], 'eps': [], 'dividends': []},
                'statistical_summary': {
                    'avg_monthly_revenue': 0,
                    'revenue_growth_rate': 0,
                    'expense_to_revenue_ratio': 0,
                    'anomaly_percentage': 0
                }
            }), 200
        
        # Prepare data for visualizations
        df_data = []
        for t in transactions:
            df_data.append({
                'id': t.id,
                'date': t.date,
                'amount': t.amount,
                'category': t.category,
                'type': t.type,
                'is_anomaly': t.is_anomaly
            })
        
        # Convert the data to a DataFrame for processing
        import pandas as pd
        df = pd.DataFrame(df_data)
        df['date'] = pd.to_datetime(df['date'])
        
        # Generate visualizations
        visualizations = {}
        
        # 1. Cash Flow Overview (Waterfall)
        revenue = df[df['category'] == 'revenue']['amount'].sum()
        expenses = df[df['category'] == 'expense']['amount'].sum()
        net_cash = revenue - expenses
        visualizations['waterfall'] = {
            'revenue': float(revenue),
            'expenses': float(expenses),
            'net_cash': float(net_cash)
        }
        
        # 2. Revenue Breakdown
        revenue_df = df[df['category'] == 'revenue']
        revenue_by_type = revenue_df.groupby('type')['amount'].sum().to_dict()
        visualizations['revenue_breakdown'] = {k: float(v) for k, v in revenue_by_type.items()}
        
        # 3. Expense Breakdown
        expense_df = df[df['category'] == 'expense']
        expense_by_type = expense_df.groupby('type')['amount'].sum().to_dict()
        visualizations['expense_breakdown'] = {k: float(v) for k, v in expense_by_type.items()}
        
        # 4. Monthly Trends
        df['month'] = df['date'].dt.to_period('M').astype(str)
        monthly_revenue = df[df['category'] == 'revenue'].groupby('month')['amount'].sum().to_dict()
        monthly_expense = df[df['category'] == 'expense'].groupby('month')['amount'].sum().to_dict()
        visualizations['monthly_trends'] = {
            'revenue': {k: float(v) for k, v in monthly_revenue.items()},
            'expense': {k: float(v) for k, v in monthly_expense.items()}
        }
        
        # 5. Anomalies
        anomalies = detect_anomalies(transactions)
        visualizations['anomalies'] = [{
            'id': a['id'],
            'amount': float(a['amount']),
            'date': a['date'].isoformat() if hasattr(a['date'], 'isoformat') else str(a['date']),
            'category': a['category'],
            'type': a['type'],
            'reason': a['reason']
        } for a in anomalies]
        
        # 6. Company vs Franchise Revenue - IMPROVED CALCULATION
        company_revenue = 0
        franchise_revenue = 0
        
        for t in transactions:
            if t.category == 'revenue':
                # Check if transaction type indicates franchise revenue
                if t.type and any(keyword in t.type.lower() for keyword in ['franchise', 'royalty', 'license', 'franchisee']):
                    franchise_revenue += t.amount
                else:
                    company_revenue += t.amount
        
        visualizations['company_vs_franchise'] = {
            'Company Revenue': float(company_revenue),
            'Franchise Revenue': float(franchise_revenue)
        }
        
        # 7. EPS & Dividend Data - NEW CALCULATION
        eps_dividend_data = {
            'months': [],
            'eps': [],
            'dividends': []
        }
        
        # Calculate EPS and dividends from monthly data
        if monthly_revenue:
            months = sorted(monthly_revenue.keys())
            eps_dividend_data['months'] = months
            
            for month in months:
                month_rev = monthly_revenue.get(month, 0)
                month_exp = monthly_expense.get(month, 0)
                net_income = month_rev - month_exp
                
                # Simplified calculations (adjust as needed for your business logic)
                # EPS = Net Income / Number of Shares (assuming 1000 shares for demonstration)
                eps = net_income / 1000 if net_income > 0 else 0
                
                # Dividends = 30% of Net Income (adjust percentage as needed)
                dividends = net_income * 0.3 if net_income > 0 else 0
                
                eps_dividend_data['eps'].append(float(eps))
                eps_dividend_data['dividends'].append(float(dividends))
        
        visualizations['eps_dividend'] = eps_dividend_data
        
        # 8. Statistical Summary Data
        avg_monthly_revenue = sum(monthly_revenue.values()) / len(monthly_revenue) if monthly_revenue else 0
        
        revenue_growth = 0
        if len(monthly_revenue) >= 2:
            months = sorted(monthly_revenue.keys())
            recent_rev = monthly_revenue[months[-1]]
            previous_rev = monthly_revenue[months[-2]]
            revenue_growth = ((recent_rev - previous_rev) / previous_rev * 100) if previous_rev > 0 else 0
        
        expense_ratio = (expenses / revenue * 100) if revenue > 0 else 0
        
        total_transactions = len(transactions)
        anomaly_percentage = (len(anomalies) / total_transactions * 100) if total_transactions > 0 else 0
        
        visualizations['statistical_summary'] = {
            'avg_monthly_revenue': float(avg_monthly_revenue),
            'revenue_growth_rate': float(revenue_growth),
            'expense_to_revenue_ratio': float(expense_ratio),
            'anomaly_percentage': float(anomaly_percentage)
        }
        
        return jsonify(visualizations), 200

    except Exception as e:
        print(f"Error in visualizations endpoint: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500
        
@app.route('/api/generate_report', methods=['POST'])
@jwt_required()
def generate_report():
    user_id = get_jwt_identity()
    
    # Get the user's first restaurant
    restaurant = Restaurant.query.filter_by(user_id=user_id).first()
    if not restaurant:
        return jsonify({'message': 'No restaurant found for user'}), 400
    
    data = request.get_json()
    report_type = data.get('report_type', 'comprehensive')
    
    # Get transactions data
    transactions = Transaction.query.filter_by(restaurant_id=restaurant.id).all()
    
    # Generate PDF report
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Add title
    story.append(Paragraph(f"{restaurant.name} - Comprehensive Financial Report", styles['Title']))
    story.append(Spacer(1, 12))
    
    # Add basic info
    story.append(Paragraph(f"Report Type: {report_type}", styles['Heading2']))
    story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 12))
    
    # Add summary cards image if available
    if data.get('summary_cards_image'):
        try:
            summary_img_data = data['summary_cards_image'].split(',')[1]
            summary_img = Image(BytesIO(base64.b64decode(summary_img_data)))
            summary_img.drawHeight = 100
            summary_img.drawWidth = 400
            story.append(Paragraph("Financial Summary", styles['Heading2']))
            story.append(summary_img)
            story.append(Spacer(1, 12))
        except Exception as e:
            print(f"Error processing summary cards image: {e}")
            # Fallback to text summary
            story.append(Paragraph("Financial Summary", styles['Heading2']))
            summary_data = data.get('summary_data', {})
            story.append(Paragraph(f"Total Revenue: {summary_data.get('totalRevenue', '₦0.00')}", styles['Normal']))
            story.append(Paragraph(f"Total Expenses: {summary_data.get('totalExpenses', '₦0.00')}", styles['Normal']))
            story.append(Paragraph(f"Net Income: {summary_data.get('netIncome', '₦0.00')}", styles['Normal']))
            story.append(Paragraph(f"Profit Margin: {summary_data.get('profitMargin', '0%')}", styles['Normal']))
            story.append(Spacer(1, 12))
    
    # Add chart images if available
    chart_images = data.get('chart_images', {})
    if chart_images:
        story.append(Paragraph("Financial Charts", styles['Heading2']))
        story.append(Spacer(1, 12))
        
        # Define chart order and titles
        chart_config = [
            {'id': 'waterfallChart', 'title': 'Cash Flow Overview'},
            {'id': 'revenueChart', 'title': 'Revenue Breakdown'},
            {'id': 'expenseChart', 'title': 'Expense Breakdown'},
            {'id': 'trendsChart', 'title': 'Monthly Trends'},
            {'id': 'detailedRevenueChart', 'title': 'Detailed Revenue Breakdown'},
            {'id': 'companyFranchiseChart', 'title': 'Company vs Franchise Revenue'},
            {'id': 'profitabilityChart', 'title': 'Profitability Analysis'},
            {'id': 'epsDividendChart', 'title': 'EPS & Dividend Trends'}
        ]
        
        for chart in chart_config:
            if chart['id'] in chart_images:
                try:
                    img_data = chart_images[chart['id']].split(',')[1]
                    img = Image(BytesIO(base64.b64decode(img_data)))
                    img.drawHeight = 150
                    img.drawWidth = 400
                    story.append(Paragraph(chart['title'], styles['Heading3']))
                    story.append(img)
                    story.append(Spacer(1, 12))
                except Exception as e:
                    print(f"Error processing {chart['id']} image: {e}")
                    story.append(Paragraph(f"{chart['title']}: Could not be included", styles['Normal']))
    
    # Add statistical summary image if available
    if data.get('statistical_summary_image'):
        try:
            statistical_img_data = data['statistical_summary_image'].split(',')[1]
            statistical_img = Image(BytesIO(base64.b64decode(statistical_img_data)))
            statistical_img.drawHeight = 120
            statistical_img.drawWidth = 400
            story.append(Paragraph("Statistical Summary", styles['Heading2']))
            story.append(statistical_img)
            story.append(Spacer(1, 12))
        except Exception as e:
            print(f"Error processing statistical summary image: {e}")
            # Fallback to text summary
            story.append(Paragraph("Statistical Summary", styles['Heading2']))
            summary_data = data.get('summary_data', {})
            story.append(Paragraph(f"Average Monthly Revenue: {summary_data.get('avgMonthlyRevenue', '₦0.00')}", styles['Normal']))
            story.append(Paragraph(f"Revenue Growth Rate: {summary_data.get('revenueGrowthRate', '0%')}", styles['Normal']))
            story.append(Paragraph(f"Expense to Revenue Ratio: {summary_data.get('expenseToRevenue', '0%')}", styles['Normal']))
            story.append(Paragraph(f"Anomaly Percentage: {summary_data.get('anomalyPercentage', '0%')}", styles['Normal']))
            story.append(Spacer(1, 12))
    
    # Add visualizations data if available
    if data.get('visualizations'):
        viz = data['visualizations']
        story.append(Paragraph("Financial Data Details", styles['Heading2']))
        story.append(Spacer(1, 12))
        
        # Waterfall chart data
        story.append(Paragraph("Cash Flow Overview", styles['Heading3']))
        story.append(Paragraph(f"Revenue: ₦{float(viz['waterfall']['revenue']):,.2f}", styles['Normal']))
        story.append(Paragraph(f"Expenses: ₦{float(viz['waterfall']['expenses']):,.2f}", styles['Normal']))
        story.append(Paragraph(f"Net Cash: ₦{float(viz['waterfall']['net_cash']):,.2f}", styles['Normal']))
        story.append(Spacer(1, 12))
        
        # Revenue breakdown
        if viz.get('revenue_breakdown'):
            story.append(Paragraph("Revenue Breakdown", styles['Heading3']))
            for category, amount in viz['revenue_breakdown'].items():
                story.append(Paragraph(f"{category}: ₦{float(amount):,.2f}", styles['Normal']))
            story.append(Spacer(1, 12))
        
        # Expense breakdown
        if viz.get('expense_breakdown'):
            story.append(Paragraph("Expense Breakdown", styles['Heading3']))
            for category, amount in viz['expense_breakdown'].items():
                story.append(Paragraph(f"{category}: ₦{float(amount):,.2f}", styles['Normal']))
            story.append(Spacer(1, 12))
        
        # Monthly trends
        if viz.get('monthly_trends'):
            story.append(Paragraph("Monthly Trends", styles['Heading3']))
            months = list(viz['monthly_trends']['revenue'].keys())
            for month in months:
                rev = viz['monthly_trends']['revenue'].get(month, 0)
                exp = viz['monthly_trends']['expense'].get(month, 0)
                story.append(Paragraph(f"{month}: Revenue ₦{float(rev):,.2f}, Expenses ₦{float(exp):,.2f}", styles['Normal']))
            story.append(Spacer(1, 12))
    
    # Add anomalies if available
    anomalies = data.get('anomalies', [])
    if anomalies:
        story.append(Paragraph("Anomaly Detection", styles['Heading2']))
        story.append(Paragraph(f"Total Anomalies Detected: {len(anomalies)}", styles['Heading3']))
        
        # Add anomalies table HTML if available
        anomalies_table_html = data.get('anomalies_table')
        if anomalies_table_html:
            # If HTML table is provided, add a note (actual table will be created below)
            story.append(Paragraph("Anomalies details are included in the table below:", styles['Normal']))
            story.append(Spacer(1, 12))
        
        # Create a table for anomalies
        from reportlab.platypus import Table, TableStyle
        from reportlab.lib import colors
        
        anomaly_data = [['Date', 'Category', 'Type', 'Amount', 'Reason']]
        for anomaly in anomalies:
            # Handle date parsing
            anomaly_date = "Unknown date"
            try:
                if 'date' in anomaly:
                    if isinstance(anomaly['date'], str):
                        try:
                            # Try ISO format
                            date_obj = datetime.fromisoformat(anomaly['date'].replace('Z', '+00:00'))
                            anomaly_date = date_obj.strftime('%Y-%m-%d')
                        except ValueError:
                            try:
                                # Try parsing as RFC 1123 format
                                date_obj = datetime.strptime(anomaly['date'], '%a, %d %b %Y %H:%M:%S %Z')
                                anomaly_date = date_obj.strftime('%Y-%m-%d')
                            except ValueError:
                                anomaly_date = anomaly['date'][:10] if len(anomaly['date']) >= 10 else anomaly['date']
            except:
                anomaly_date = "Invalid date"
            
            anomaly_data.append([
                anomaly_date,
                anomaly['category'],
                anomaly['type'],
                f"₦{float(anomaly['amount']):,.2f}",
                anomaly['reason']
            ])
        
        # Create table with appropriate size
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTSIZE', (0, 1), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ])
        
        # Adjust table width based on number of columns
        col_widths = [60, 60, 60, 60, 120]  # Adjust as needed
        
        anomaly_table = Table(anomaly_data, colWidths=col_widths)
        anomaly_table.setStyle(table_style)
        story.append(anomaly_table)
        story.append(Spacer(1, 12))
    
    doc.build(story)
    buffer.seek(0)
    
    # Save report to database
    new_report = Report(
        restaurant_id=restaurant.id,
        report_type=report_type,
        content=f"Generated {report_type} report"
    )
    db.session.add(new_report)
    db.session.commit()
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'comprehensive_report_{datetime.now().strftime("%Y%m%d")}.pdf',
        mimetype='application/pdf'
    )

@app.route('/api/logout', methods=['POST'])
@jwt_required()
def logout():
    response = jsonify({'message': 'Successfully logged out'})
    # Clear the JWT cookie
    response.set_cookie(
        'access_token_cookie',
        '',
        expires=0,
        httponly=True,
        secure=False,  # True in production with HTTPS
        samesite='Lax'
    )
    return response, 200    

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)