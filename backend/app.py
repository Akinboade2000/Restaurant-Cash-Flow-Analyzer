import csv
import io
import math
import os
import secrets
import threading
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    unset_jwt_cookies,
)
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import insert, inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from model import Restaurant, Transaction, User, db


load_dotenv()


def create_database_settings(environment):
    database_url = environment.get("TURSO_DATABASE_URL")
    auth_token = environment.get("TURSO_AUTH_TOKEN")

    if bool(database_url) != bool(auth_token):
        raise RuntimeError(
            "Set both TURSO_DATABASE_URL and TURSO_AUTH_TOKEN to use the hosted database."
        )
    if environment.get("VERCEL") and not database_url:
        raise RuntimeError(
            "TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required in Vercel project settings."
        )

    if database_url:
        if database_url.startswith("libsql://"):
            host = database_url.removeprefix("libsql://").rstrip("/")
        elif database_url.startswith("https://"):
            host = database_url.removeprefix("https://").rstrip("/")
        else:
            raise RuntimeError(
                "TURSO_DATABASE_URL must start with libsql:// or https://."
            )
        return (
            f"sqlite+libsql://{host}?secure=true",
            {
                "connect_args": {"auth_token": auth_token},
                "pool_pre_ping": True,
                "pool_recycle": 300,
            },
        )

    database_path = Path(
        environment.get(
            "DATABASE_PATH",
            str(Path(__file__).resolve().parent / "instance" / "restaurant_cashflow.db"),
        )
    ).expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return (
        f"sqlite:///{database_path.as_posix()}",
        {"connect_args": {"check_same_thread": False, "timeout": 30}},
    )


if os.getenv("VERCEL") and not os.getenv("JWT_SECRET_KEY"):
    raise RuntimeError("JWT_SECRET_KEY must be configured in Vercel project settings.")

app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static",
)
database_uri, engine_options = create_database_settings(os.environ)
app.config.update(
    SQLALCHEMY_DATABASE_URI=database_uri,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS=engine_options,
    JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(32),
    JWT_TOKEN_LOCATION=["cookies"],
    JWT_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "true" if os.getenv("VERCEL") else "false").lower()
    == "true",
    JWT_COOKIE_SAMESITE="Lax",
    JWT_COOKIE_CSRF_PROTECT=True,
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
)
db.init_app(app)
jwt = JWTManager(app)
_database_initialized = False
_database_initialization_lock = threading.Lock()


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_database_schema():
    global _database_initialized
    if _database_initialized:
        return
    with _database_initialization_lock:
        if _database_initialized:
            return
        db.create_all()
        inspector = inspect(db.engine)
        if "transaction" not in inspector.get_table_names():
            _database_initialized = True
            return

        columns = {column["name"] for column in inspector.get_columns("transaction")}
        with db.engine.begin() as connection:
            if "exchange_rate_to_ngn" not in columns:
                connection.execute(
                    text(
                        'ALTER TABLE "transaction" ADD COLUMN '
                        "exchange_rate_to_ngn FLOAT NOT NULL DEFAULT 1.0"
                    )
                )
                tables = set(inspect(db.engine).get_table_names())
                if "exchange_rate" in tables:
                    connection.execute(
                        text(
                            'UPDATE "transaction" SET exchange_rate_to_ngn = COALESCE('
                            "(SELECT rate FROM exchange_rate "
                            'WHERE from_currency = "transaction".currency '
                            "AND to_currency = 'NGN' ORDER BY last_updated DESC LIMIT 1), 1.0) "
                            'WHERE currency != "NGN"'
                        )
                    )

            if "amount_ngn" not in columns:
                connection.execute(
                    text(
                        'ALTER TABLE "transaction" ADD COLUMN '
                        "amount_ngn FLOAT NOT NULL DEFAULT 0.0"
                    )
                )
                connection.execute(
                    text(
                        'UPDATE "transaction" SET amount_ngn = '
                        "amount * exchange_rate_to_ngn WHERE amount_ngn = 0.0"
                    )
                )
        _database_initialized = True


@app.before_request
def initialize_database():
    ensure_database_schema()


@app.errorhandler(SQLAlchemyError)
def handle_database_error(error):
    db.session.rollback()
    app.logger.exception("SQLite request failed")
    return jsonify({"message": "A database operation failed. Please try again."}), 500


@app.errorhandler(413)
def handle_upload_too_large(_error):
    return jsonify({"message": "The upload exceeds the 10 MB limit."}), 413


@jwt.unauthorized_loader
def handle_unauthorized(_reason):
    return jsonify({"message": "Please sign in to continue."}), 401


def parse_date(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text_value = str(value or "").strip()
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text_value, date_format)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as error:
        raise ValueError("use YYYY-MM-DD or DD/MM/YYYY") from error


def parse_number(value, field_name):
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a number") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number")
    return number


def parse_transaction(row):
    transaction_date = parse_date(row.get("date"))
    amount = parse_number(row.get("amount"), "amount")
    if amount < 0:
        raise ValueError("amount cannot be negative")

    category_aliases = {
        "income": "revenue",
        "revenue": "revenue",
        "sales": "revenue",
        "expense": "expense",
        "expenses": "expense",
        "expenditure": "expense",
    }
    source_category = str(row.get("category") or "").strip()
    source_type = str(row.get("type") or "").strip()
    category = category_aliases.get(source_category.lower())
    transaction_type = source_type
    if category is None:
        category = category_aliases.get(source_type.lower())
        transaction_type = source_category
    if category is None:
        raise ValueError(
            "category must be revenue or expense, or type must identify income or expense"
        )
    if not transaction_type:
        raise ValueError("type is required")

    currency = str(row.get("currency") or "NGN").strip().upper()
    currency = {"₦": "NGN", "NAIRA": "NGN", "NAIRAS": "NGN"}.get(currency, currency)
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a three-letter currency code such as NGN or USD")

    if currency == "NGN":
        exchange_rate = 1.0
    else:
        rate_value = row.get("exchange_rate_to_ngn") or row.get("rate_to_ngn")
        if rate_value in (None, ""):
            raise ValueError(f"exchange_rate_to_ngn is required for {currency} transactions")
        exchange_rate = parse_number(rate_value, "exchange_rate_to_ngn")
        if exchange_rate <= 0:
            raise ValueError("exchange_rate_to_ngn must be greater than zero")

    return {
        "date": transaction_date,
        "amount": amount,
        "currency": currency,
        "exchange_rate_to_ngn": exchange_rate,
        "amount_ngn": round(amount * exchange_rate, 2),
        "category": category,
        "type": transaction_type,
        "description": str(row.get("description") or "").strip()[:200],
    }


def read_uploaded_rows(upload):
    extension = secure_filename(upload.filename or "").rsplit(".", 1)[-1].lower()
    if extension == "csv":
        try:
            contents = upload.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("The CSV must be saved as UTF-8.") from error
        reader = csv.reader(io.StringIO(contents))
        headers = [str(header or "").strip().lower() for header in next(reader, ())]
        if not headers:
            raise ValueError("The file must include a header row.")
        rows = [dict(zip(headers, values)) for values in reader]
    elif extension == "xlsx":
        workbook = load_workbook(upload.stream, data_only=True, read_only=True)
        try:
            values = workbook.active.iter_rows(values_only=True)
            headers = [str(value or "").strip().lower() for value in next(values, ())]
            rows = [
                dict(zip(headers, row))
                for row in values
                if any(value is not None and str(value).strip() for value in row)
            ]
        finally:
            workbook.close()
        if not headers:
            raise ValueError("The file must include a header row.")
    else:
        raise ValueError("Upload a CSV or XLSX file.")

    required = {"date", "amount", "category", "type"}
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    return rows


def percentile(sorted_values, fraction):
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] * (upper - position) + sorted_values[upper] * (
        position - lower
    )


def find_anomalies(transactions):
    groups = defaultdict(list)
    for transaction in transactions:
        key = (
            transaction.category,
            transaction.type.strip().lower(),
            transaction.currency,
        )
        groups[key].append(transaction)

    anomalies = []
    for (category, transaction_type, currency), group in groups.items():
        if len(group) < 4:
            continue
        values = sorted(transaction.amount for transaction in group)
        q1 = percentile(values, 0.25)
        q3 = percentile(values, 0.75)
        iqr = q3 - q1
        if iqr:
            outliers = [
                transaction
                for transaction in group
                if transaction.amount < q1 - 1.5 * iqr
                or transaction.amount > q3 + 1.5 * iqr
            ]
        else:
            median = percentile(values, 0.5)
            deviations = sorted(abs(value - median) for value in values)
            mad = percentile(deviations, 0.5)
            if mad:
                outliers = [
                    transaction
                    for transaction in group
                    if abs(0.6745 * (transaction.amount - median) / mad) > 3.5
                ]
            else:
                outliers = [
                    transaction for transaction in group if transaction.amount != median
                ]

        for transaction in outliers:
            anomalies.append(
                {
                    "id": transaction.id,
                    "date": transaction.date.isoformat(),
                    "amount": transaction.amount,
                    "currency": currency,
                    "exchange_rate_to_ngn": transaction.exchange_rate_to_ngn,
                    "amount_ngn": transaction.amount_ngn,
                    "category": category,
                    "type": transaction.type,
                    "reason": (
                        f"Unusual {category} amount for {transaction_type} transactions "
                        f"recorded in {currency}."
                    ),
                }
            )
    return sorted(anomalies, key=lambda anomaly: anomaly["date"], reverse=True)


def analyze_transactions(transactions):
    anomalies = find_anomalies(transactions)
    revenue = sum(t.amount_ngn for t in transactions if t.category == "revenue")
    expenses = sum(t.amount_ngn for t in transactions if t.category == "expense")

    month_totals = defaultdict(lambda: {"revenue": 0.0, "expense": 0.0})
    revenue_breakdown = defaultdict(float)
    expense_breakdown = defaultdict(float)
    for transaction in transactions:
        month = transaction.date.strftime("%Y-%m")
        month_totals[month][transaction.category] += transaction.amount_ngn
        breakdown = (
            revenue_breakdown
            if transaction.category == "revenue"
            else expense_breakdown
        )
        breakdown[transaction.type] += transaction.amount_ngn

    months = sorted(month_totals)
    monthly_revenue = [round(month_totals[month]["revenue"], 2) for month in months]
    monthly_expense = [round(month_totals[month]["expense"], 2) for month in months]
    growth_rate = None
    if len(monthly_revenue) > 1 and monthly_revenue[-2] > 0:
        growth_rate = round(
            (monthly_revenue[-1] - monthly_revenue[-2]) / monthly_revenue[-2] * 100,
            2,
        )

    return {
        "waterfall": {
            "revenue": round(revenue, 2),
            "expenses": round(expenses, 2),
            "net_cash": round(revenue - expenses, 2),
        },
        "revenue_breakdown": {
            key: round(value, 2) for key, value in sorted(revenue_breakdown.items())
        },
        "expense_breakdown": {
            key: round(value, 2) for key, value in sorted(expense_breakdown.items())
        },
        "monthly_trends": {
            "months": months,
            "revenue": monthly_revenue,
            "expense": monthly_expense,
            "net_cash": [
                round(month_totals[month]["revenue"] - month_totals[month]["expense"], 2)
                for month in months
            ],
        },
        "anomalies": anomalies,
        "statistical_summary": {
            "avg_monthly_revenue": round(revenue / len(months), 2) if months else 0,
            "revenue_growth_rate": growth_rate,
            "expense_to_revenue_ratio": round(expenses / revenue * 100, 2)
            if revenue
            else 0,
            "anomaly_percentage": round(len(anomalies) / len(transactions) * 100, 2)
            if transactions
            else 0,
            "transaction_count": len(transactions),
            "anomaly_count": len(anomalies),
            "active_months": len(months),
        },
    }


def owned_restaurant(restaurant_id, user_id):
    try:
        restaurant_id = int(restaurant_id)
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    return Restaurant.query.filter_by(id=restaurant_id, user_id=user_id).first()


def serialize_transaction(transaction):
    return {
        "id": transaction.id,
        "date": transaction.date.isoformat(),
        "amount": transaction.amount,
        "currency": transaction.currency,
        "exchange_rate_to_ngn": transaction.exchange_rate_to_ngn,
        "amount_ngn": transaction.amount_ngn,
        "category": transaction.category,
        "type": transaction.type,
        "description": transaction.description or "",
        "is_anomaly": transaction.is_anomaly,
    }


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/login")
def login_page():
    return render_template("login.html")


@app.get("/register")
def register_page():
    return render_template("register.html")


@app.get("/dashboard")
@jwt_required()
def dashboard_page():
    return render_template("dashboard.html")


@app.get("/api/verify-auth")
@jwt_required()
def verify_auth():
    return jsonify({"message": "Authenticated"}), 200


@app.post("/api/register")
def register():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"message": "A JSON request body is required."}), 400
    username = str(data.get("username") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    if not username or not email or not password:
        return jsonify({"message": "Username, email, and password are required."}), 400
    if len(password) < 8:
        return jsonify({"message": "Password must contain at least 8 characters."}), 400

    user = User(
        username=username,
        email=email,
        password=generate_password_hash(password),
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "That username or email is already registered."}), 409
    return jsonify(
        {
            "message": "Account created successfully.",
            "user": {"id": user.id, "username": user.username, "email": user.email},
        }
    ), 201


@app.post("/api/login")
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"message": "A JSON request body is required."}), 400
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    if not username or not password:
        return jsonify({"message": "Username and password are required."}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({"message": "Invalid username or password."}), 401

    response = jsonify(
        {"message": "Login successful.", "user": {"id": user.id, "username": username}}
    )
    set_access_cookies(response, create_access_token(identity=str(user.id)))
    return response, 200


@app.post("/api/logout")
def logout():
    response = jsonify({"message": "Signed out."})
    unset_jwt_cookies(response)
    return response, 200


@app.route("/api/restaurants", methods=["GET", "POST"])
@jwt_required()
def restaurants():
    user_id = int(get_jwt_identity())
    if request.method == "POST":
        data = request.get_json(silent=True)
        name = str((data or {}).get("name") or "").strip()
        if not name:
            return jsonify({"message": "Restaurant name is required."}), 400
        restaurant = Restaurant(name=name[:120], user_id=user_id)
        db.session.add(restaurant)
        db.session.commit()
        return jsonify(
            {"id": restaurant.id, "name": restaurant.name, "message": "Restaurant created."}
        ), 201

    items = Restaurant.query.filter_by(user_id=user_id).order_by(Restaurant.created_at).all()
    return jsonify([{"id": item.id, "name": item.name} for item in items]), 200


@app.route("/api/transactions", methods=["GET", "POST"])
@jwt_required()
def transactions():
    restaurant = owned_restaurant(request.args.get("restaurant_id"), get_jwt_identity())
    if not restaurant:
        return jsonify({"message": "Restaurant not found."}), 404

    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"message": "A JSON request body is required."}), 400
        try:
            values = parse_transaction(data)
        except (TypeError, ValueError) as error:
            return jsonify({"message": str(error)}), 400
        transaction = Transaction(restaurant_id=restaurant.id, **values)
        db.session.add(transaction)
        db.session.commit()
        return jsonify(serialize_transaction(transaction)), 201

    items = Transaction.query.filter_by(restaurant_id=restaurant.id).order_by(Transaction.date).all()
    return jsonify([serialize_transaction(item) for item in items]), 200


@app.get("/api/restaurants/<int:restaurant_id>/transactions.csv")
@jwt_required()
def export_transactions(restaurant_id):
    restaurant = owned_restaurant(restaurant_id, get_jwt_identity())
    if not restaurant:
        return jsonify({"message": "Restaurant not found."}), 404

    items = Transaction.query.filter_by(restaurant_id=restaurant.id).order_by(Transaction.date).all()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "date",
            "amount",
            "currency",
            "exchange_rate_to_ngn",
            "category",
            "type",
            "description",
        ]
    )
    for item in items:
        writer.writerow(
            [
                item.date.strftime("%Y-%m-%d"),
                item.amount,
                item.currency,
                item.exchange_rate_to_ngn,
                item.category,
                item.type,
                item.description or "",
            ]
        )

    filename = f"{secure_filename(restaurant.name) or 'restaurant'}-transactions.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


@app.post("/api/upload")
@jwt_required()
def upload():
    upload_file = request.files.get("file")
    if not upload_file or not upload_file.filename:
        return jsonify({"message": "Choose a CSV or XLSX file to upload."}), 400
    try:
        rows = read_uploaded_rows(upload_file)
    except (ValueError, StopIteration, InvalidFileException, zipfile.BadZipFile) as error:
        return jsonify({"message": str(error)}), 400
    if not rows:
        return jsonify({"message": "The file contains no transaction rows."}), 400
    if len(rows) > 50000:
        return jsonify({"message": "A single import is limited to 50,000 rows."}), 400

    transactions_to_insert = []
    errors = []
    for row_number, row in enumerate(rows, start=2):
        if not any(value is not None and str(value).strip() for value in row.values()):
            continue
        try:
            transactions_to_insert.append(parse_transaction(row))
        except (TypeError, ValueError) as error:
            errors.append(f"Row {row_number}: {error}")
    if errors:
        return jsonify(
            {
                "message": "No rows were imported. Correct the listed data and try again.",
                "errors": errors[:50],
                "error_count": len(errors),
            }
        ), 422
    if not transactions_to_insert:
        return jsonify({"message": "The file contains no transaction rows."}), 400

    user_id = int(get_jwt_identity())
    restaurant_id = request.form.get("restaurant_id", "").strip()
    if restaurant_id:
        restaurant = owned_restaurant(restaurant_id, user_id)
        if not restaurant:
            return jsonify({"message": "Restaurant not found."}), 404
    else:
        restaurant = Restaurant.query.filter_by(user_id=user_id).order_by(
            Restaurant.created_at
        ).first()
        if not restaurant:
            restaurant = Restaurant(name="My Restaurant", user_id=user_id)
            db.session.add(restaurant)
            db.session.flush()

    Transaction.query.filter_by(restaurant_id=restaurant.id).delete(
        synchronize_session=False
    )
    transaction_rows = [
        {"restaurant_id": restaurant.id, **values}
        for values in transactions_to_insert
    ]
    for offset in range(0, len(transaction_rows), 100):
        db.session.execute(
            insert(Transaction).values(transaction_rows[offset : offset + 100])
        )
    db.session.commit()
    transaction_count = len(transactions_to_insert)
    transaction_label = "transaction" if transaction_count == 1 else "transactions"
    return jsonify(
        {
            "message": (
                f"Replaced the dataset for {restaurant.name} with "
                f"{transaction_count} {transaction_label}."
            ),
            "success_count": transaction_count,
            "error_count": 0,
            "restaurant_id": restaurant.id,
        }
    ), 201


@app.get("/api/visualizations")
@app.get("/api/visualizations/")
@jwt_required()
def visualizations():
    restaurant = owned_restaurant(request.args.get("restaurant_id"), get_jwt_identity())
    if not restaurant:
        return jsonify({"message": "Restaurant not found."}), 404
    items = Transaction.query.filter_by(restaurant_id=restaurant.id).order_by(Transaction.date).all()
    result = analyze_transactions(items)
    result["restaurant"] = {"id": restaurant.id, "name": restaurant.name}
    return jsonify(result), 200


def compact_ngn(value):
    value = float(value or 0)
    if abs(value) >= 1_000_000_000:
        return f"NGN {value / 1_000_000_000:.1f}B"
    if abs(value) >= 1_000_000:
        return f"NGN {value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"NGN {value / 1_000:.0f}k"
    return f"NGN {value:,.0f}"


def chart_label(value, max_length=26):
    return str(value).encode("latin-1", "replace").decode("latin-1")[:max_length]


def build_monthly_chart(analysis):
    width, height = 500, 245
    drawing = Drawing(width, height)
    trends = analysis["monthly_trends"]
    months = trends["months"]
    series = [
        ("Revenue", trends["revenue"], colors.HexColor("#21865b"), False),
        ("Expenses", trends["expense"], colors.HexColor("#e28559"), False),
        ("Net cash flow", trends["net_cash"], colors.HexColor("#5076ad"), False),
    ]
    anomaly_by_month = defaultdict(float)
    for anomaly in analysis["anomalies"]:
        month = anomaly["date"][:7]
        anomaly_by_month[month] = max(
            anomaly_by_month[month], float(anomaly["amount_ngn"])
        )
    series.append(
        (
            "Largest flagged transaction",
            [anomaly_by_month.get(month) or None for month in months],
            colors.HexColor("#bd5948"),
            True,
        )
    )

    left, bottom, plot_width, plot_height = 61, 49, 421, 145
    all_values = [
        float(value)
        for _, values, _, _ in series
        for value in values
        if value is not None
    ]
    minimum = min([0, *all_values])
    maximum = max([0, *all_values])
    if maximum == minimum:
        maximum = minimum + 1

    for index in range(5):
        fraction = index / 4
        y = bottom + fraction * plot_height
        value = minimum + fraction * (maximum - minimum)
        drawing.add(
            Line(
                left,
                y,
                left + plot_width,
                y,
                strokeColor=colors.HexColor("#e6ece7"),
                strokeWidth=0.6,
            )
        )
        drawing.add(
            String(
                left - 6,
                y - 2,
                chart_label(compact_ngn(value), 12),
                textAnchor="end",
                fontName="Helvetica",
                fontSize=7,
                fillColor=colors.HexColor("#738078"),
            )
        )

    x_positions = [
        left + (plot_width / 2 if len(months) == 1 else plot_width * index / (len(months) - 1))
        for index in range(len(months))
    ]
    for _, values, color, points_only in series:
        points = []
        for index, value in enumerate(values):
            if value is None:
                points.append(None)
                continue
            y = bottom + (float(value) - minimum) / (maximum - minimum) * plot_height
            points.append((x_positions[index], y))
        previous = None
        for point in points:
            if point is None:
                previous = None
                continue
            if not points_only and previous is not None:
                drawing.add(
                    Line(
                        previous[0],
                        previous[1],
                        point[0],
                        point[1],
                        strokeColor=color,
                        strokeWidth=1.8,
                    )
                )
            drawing.add(
                Circle(
                    point[0],
                    point[1],
                    3 if points_only else 2,
                    fillColor=color,
                    strokeColor=colors.white,
                    strokeWidth=0.5,
                )
            )
            previous = point

    label_step = max(1, math.ceil(len(months) / 12))
    for index, month in enumerate(months):
        if index % label_step:
            continue
        try:
            label = datetime.strptime(month, "%Y-%m").strftime("%b %y")
        except ValueError:
            label = month
        drawing.add(
            String(
                x_positions[index],
                bottom - 17,
                chart_label(label, 10),
                textAnchor="middle",
                fontName="Helvetica",
                fontSize=7,
                fillColor=colors.HexColor("#738078"),
            )
        )

    legend_x = [61, 143, 226, 324]
    for x, (label, _, color, points_only) in zip(legend_x, series):
        if points_only:
            drawing.add(Circle(x + 3, 224, 3, fillColor=color, strokeColor=color))
        else:
            drawing.add(Line(x, 224, x + 8, 224, strokeColor=color, strokeWidth=2))
        drawing.add(
            String(
                x + 12,
                221,
                label,
                fontName="Helvetica",
                fontSize=7,
                fillColor=colors.HexColor("#41574a"),
            )
        )
    if not months:
        drawing.add(
            String(
                width / 2,
                height / 2,
                "Import transactions to see monthly cash flow.",
                textAnchor="middle",
                fontName="Helvetica",
                fontSize=10,
                fillColor=colors.HexColor("#738078"),
            )
        )
    return drawing


def build_category_charts(breakdown, color, empty_label):
    entries = sorted(breakdown.items(), key=lambda item: item[1], reverse=True)
    if not entries:
        drawing = Drawing(500, 82)
        drawing.add(
            String(
                250,
                41,
                empty_label,
                textAnchor="middle",
                fontName="Helvetica",
                fontSize=9,
                fillColor=colors.HexColor("#738078"),
            )
        )
        return [drawing]

    drawings = []
    rows_per_chart = 24
    for offset in range(0, len(entries), rows_per_chart):
        visible_entries = entries[offset : offset + rows_per_chart]
        height = max(82, 43 + 17 * len(visible_entries))
        drawing = Drawing(500, height)
        max_value = max(float(value) for _, value in visible_entries) or 1
        label_width, bar_width = 145, 267
        bar_start = label_width
        row_height = 17
        for index, (label, amount) in enumerate(visible_entries):
            y = height - 23 - index * row_height
            drawing.add(
                String(
                    label_width - 8,
                    y + 2,
                    chart_label(label, 24),
                    textAnchor="end",
                    fontName="Helvetica",
                    fontSize=7,
                    fillColor=colors.HexColor("#41574a"),
                )
            )
            drawing.add(
                Rect(
                    bar_start,
                    y,
                    bar_width,
                    8,
                    fillColor=colors.HexColor("#f0f4f0"),
                    strokeColor=None,
                )
            )
            drawing.add(
                Rect(
                    bar_start,
                    y,
                    bar_width * float(amount) / max_value,
                    8,
                    fillColor=color,
                    strokeColor=None,
                )
            )
            drawing.add(
                String(
                    bar_start + bar_width + 7,
                    y + 1,
                    chart_label(compact_ngn(amount), 13),
                    fontName="Helvetica",
                    fontSize=7,
                    fillColor=colors.HexColor("#41574a"),
                )
            )
        drawings.append(drawing)
    return drawings


def build_report_pdf(restaurant, transactions, analysis):
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{restaurant['name']} cash-flow analysis",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DashboardTitle",
        parent=styles["Title"],
        textColor=colors.HexColor("#143b2b"),
        spaceAfter=5 * mm,
    )
    section_style = ParagraphStyle(
        "DashboardSection",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#143b2b"),
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
    )
    body_style = ParagraphStyle(
        "DashboardBody",
        parent=styles["BodyText"],
        fontSize=8,
        leading=11,
    )
    table_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf3ed")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#143b2b")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce5df")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
        ]
    )
    totals = analysis["waterfall"]
    summary = analysis["statistical_summary"]
    growth = summary["revenue_growth_rate"]
    growth_text = "Not available" if growth is None else f"{growth:.2f}%"
    profit_margin = (
        totals["net_cash"] / totals["revenue"] * 100 if totals["revenue"] else 0
    )
    dates = []
    for transaction in transactions:
        value = (
            transaction.get("date")
            if isinstance(transaction, dict)
            else getattr(transaction, "date", None)
        )
        if value is not None:
            dates.append(value.date() if isinstance(value, datetime) else value)
    date_range = (
        f"{min(dates).strftime('%d %b %Y')} - {max(dates).strftime('%d %b %Y')}"
        if dates
        else "No transaction dates"
    )
    generated_at = datetime.now().strftime("%d %B %Y, %H:%M")

    story = [
        Paragraph(
            f"{escape(restaurant['name'])} — Cash-flow dashboard",
            title_style,
        ),
        Paragraph(
            f"Analysis period: {escape(date_range)} &nbsp; | &nbsp; "
            f"Generated: {generated_at} &nbsp; | &nbsp; "
            f"{len(transactions):,} transactions",
            body_style,
        ),
        Spacer(1, 5 * mm),
    ]

    kpi_rows = [
        ["Total revenue", "Total expenses", "Net cash flow", "Profit margin"],
        [
            f"NGN {totals['revenue']:,.2f}",
            f"NGN {totals['expenses']:,.2f}",
            f"NGN {totals['net_cash']:,.2f}",
            f"{profit_margin:.2f}%",
        ],
    ]
    kpi_table = Table(kpi_rows, colWidths=[44.5 * mm] * 4)
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf3ed")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#143b2b")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("FONTSIZE", (0, 1), (-1, 1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce5df")),
            ]
        )
    )
    story.extend([kpi_table, Spacer(1, 6 * mm)])

    insight_rows = [
        ["Average monthly revenue", "Latest-month revenue change"],
        [f"NGN {summary['avg_monthly_revenue']:,.2f}", growth_text],
        ["Expenses as a share of revenue", "Unusual transactions"],
        [
            f"{summary['expense_to_revenue_ratio']:.2f}%",
            f"{summary['anomaly_count']:,} "
            f"({summary['anomaly_percentage']:.2f}%)",
        ],
    ]
    insights = Table(insight_rows, colWidths=[89 * mm, 89 * mm])
    insights.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f6f3")),
                ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#f3f6f3")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#41574a")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce5df")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend(
        [
            Paragraph("Operating indicators", section_style),
            insights,
            Spacer(1, 4 * mm),
            Paragraph("Monthly cash flow", section_style),
            build_monthly_chart(analysis),
            Spacer(1, 3 * mm),
        ]
    )

    for heading, breakdown, color, empty_label in (
        (
            "Revenue by source",
            analysis["revenue_breakdown"],
            colors.HexColor("#21865b"),
            "No revenue transactions.",
        ),
        (
            "Expenses by category",
            analysis["expense_breakdown"],
            colors.HexColor("#e28559"),
            "No expense transactions.",
        ),
    ):
        charts = build_category_charts(breakdown, color, empty_label)
        for index, chart in enumerate(charts):
            graph_title = heading if index == 0 else f"{heading} (continued)"
            story.extend(
                [
                    Paragraph(graph_title, section_style),
                    chart,
                    Spacer(1, 3 * mm),
                ]
            )

    for heading, breakdown, total in (
        (
            "Revenue breakdown",
            analysis["revenue_breakdown"],
            totals["revenue"],
        ),
        (
            "Expense breakdown",
            analysis["expense_breakdown"],
            totals["expenses"],
        ),
    ):
        story.extend([Paragraph(heading, section_style)])
        rows = [["Source / category", "Amount (NGN)", "Share of total"]]
        rows.extend(
            [
                Paragraph(escape(str(key)), body_style),
                f"NGN {amount:,.2f}",
                f"{(amount / total * 100) if total else 0:.2f}%",
            ]
            for key, amount in sorted(
                breakdown.items(), key=lambda item: item[1], reverse=True
            )
        )
        if len(rows) == 1:
            rows.append(["No transactions", "NGN 0.00", "0.00%"])
        table = LongTable(
            rows,
            colWidths=[92 * mm, 48 * mm, 38 * mm],
            repeatRows=1,
        )
        table.setStyle(table_style)
        table.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        story.extend([table, Spacer(1, 4 * mm)])

    story.append(Paragraph("Transactions to check", section_style))
    story.append(
        Paragraph(
            "Flags are review prompts, not proof of an error. Every flagged "
            "transaction from the current dataset is listed below.",
            body_style,
        )
    )
    anomaly_rows = [
        [
            "Date",
            "Category",
            "Type",
            "Recorded amount",
            "NGN equivalent",
            "Why it was flagged",
        ]
    ]
    for anomaly in analysis["anomalies"]:
        anomaly_rows.append(
            [
                anomaly["date"][:10],
                Paragraph(escape(str(anomaly["category"]).title()), body_style),
                Paragraph(
                    escape(str(anomaly["type"])),
                    body_style,
                ),
                f"{anomaly['currency']} {anomaly['amount']:,.2f}",
                f"NGN {anomaly['amount_ngn']:,.2f}",
                Paragraph(escape(str(anomaly["reason"])), body_style),
            ]
        )
    if len(anomaly_rows) == 1:
        anomaly_rows.append(["No anomalies detected", "", "", "", "", ""])
    anomaly_table = LongTable(
        anomaly_rows,
        colWidths=[21 * mm, 24 * mm, 28 * mm, 31 * mm, 31 * mm, 43 * mm],
        repeatRows=1,
    )
    anomaly_table.setStyle(table_style)
    anomaly_table.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7)]))
    story.append(anomaly_table)

    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#dce5df"))
        canvas.line(16 * mm, 11 * mm, A4[0] - 16 * mm, 11 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#738078"))
        canvas.drawString(
            16 * mm,
            7 * mm,
            "Restaurant Cash Flow Analyzer - NGN",
        )
        canvas.drawRightString(A4[0] - 16 * mm, 7 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer


@app.route("/api/generate_report", methods=["POST"])
@app.route("/api/restaurants/<int:restaurant_id>/report.pdf", methods=["GET"])
@jwt_required()
def generate_report(restaurant_id=None):
    if restaurant_id is None:
        data = request.get_json(silent=True) or {}
        restaurant_id = data.get("restaurant_id") or request.args.get("restaurant_id", "")
    restaurant = owned_restaurant(restaurant_id, get_jwt_identity())
    if not restaurant:
        return jsonify({"message": "Restaurant not found."}), 404

    items = Transaction.query.filter_by(restaurant_id=restaurant.id).order_by(Transaction.date).all()
    analysis = analyze_transactions(items)
    pdf = build_report_pdf(
        {"name": restaurant.name},
        [
            {
                "date": item.date,
                "amount": item.amount,
                "currency": item.currency,
                "exchange_rate_to_ngn": item.exchange_rate_to_ngn,
                "amount_ngn": item.amount_ngn,
                "category": item.category,
                "type": item.type,
            }
            for item in items
        ],
        analysis,
    )
    filename = f"{secure_filename(restaurant.name) or 'restaurant'}-cash-flow-analysis.pdf"
    return send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
