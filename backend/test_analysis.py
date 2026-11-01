import csv
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parent))

test_database_directory = tempfile.TemporaryDirectory(prefix="rcf-sqlite-tests-")
os.environ["DATABASE_PATH"] = str(Path(test_database_directory.name) / "test.sqlite")
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-restaurant-analysis"

from app import (
    analyze_transactions,
    app,
    build_report_pdf,
    create_database_settings,
    parse_transaction,
)
from flask_jwt_extended import create_access_token
from model import db
import scripts.build_netlify as netlify_build


class AnalysisTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.engine.dispose()
        test_database_directory.cleanup()

    def test_foreign_currency_is_normalized_using_supplied_rate(self):
        transaction = parse_transaction(
            {
                "date": "2026-03-08",
                "amount": "12.5",
                "currency": "USD",
                "exchange_rate_to_ngn": "1500",
                "category": "revenue",
                "type": "delivery",
            }
        )

        self.assertEqual(transaction["amount_ngn"], 18750)
        self.assertEqual(transaction["exchange_rate_to_ngn"], 1500)

    def test_turso_settings_build_libsql_sqlalchemy_url(self):
        database_url, engine_options = create_database_settings(
            {
                "TURSO_DATABASE_URL": "libsql://restaurant-cash-flow-example.turso.io",
                "TURSO_AUTH_TOKEN": "private-token",
            }
        )

        self.assertEqual(
            database_url,
            "sqlite+libsql://restaurant-cash-flow-example.turso.io?secure=true",
        )
        self.assertEqual(
            engine_options["connect_args"]["auth_token"],
            "private-token",
        )
        self.assertNotIn("private-token", database_url)

    def test_vercel_requires_a_persistent_turso_database(self):
        with self.assertRaisesRegex(RuntimeError, "required in Vercel"):
            create_database_settings({"VERCEL": "1"})

    def test_vercel_config_uses_supported_python_function_configuration(self):
        config_path = Path(__file__).resolve().parents[1] / "vercel.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertNotIn("builds", config)
        self.assertEqual(config["routes"][0]["src"], "/api/(.*)")
        self.assertEqual(
            config["functions"]["api/index.py"]["includeFiles"],
            "backend/**",
        )

    def test_netlify_build_generates_static_pages_and_api_proxy(self):
        with tempfile.TemporaryDirectory(prefix="rcf-netlify-tests-") as directory:
            output_path = Path(directory) / "dist"
            with mock.patch.object(netlify_build, "OUTPUT", output_path):
                with mock.patch.dict(
                    os.environ,
                    {"VERCEL_API_URL": "https://restaurant-api.vercel.app"},
                ):
                    netlify_build.main()

            index = (output_path / "index.html").read_text(encoding="utf-8")
            redirects = (output_path / "_redirects").read_text(encoding="utf-8")
            self.assertIn("/static/css/styles.css", index)
            self.assertNotIn("{{ url_for(", index)
            self.assertIn(
                "/api/* https://restaurant-api.vercel.app/api/:splat 200",
                redirects,
            )
            self.assertTrue((output_path / "dashboard.html").exists())
            self.assertTrue((output_path / "static" / "js" / "script.js").exists())

    def test_netlify_build_rejects_missing_api_origin(self):
        with mock.patch.dict(os.environ, {"VERCEL_API_URL": ""}):
            with self.assertRaisesRegex(SystemExit, "Set VERCEL_API_URL"):
                netlify_build.main()

    def test_foreign_currency_without_explicit_rate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exchange_rate_to_ngn is required"):
            parse_transaction(
                {
                    "date": "2026-03-08",
                    "amount": 12.5,
                    "currency": "USD",
                    "category": "revenue",
                    "type": "delivery",
                }
            )

    def test_income_expense_type_maps_source_category_to_transaction_type(self):
        income = parse_transaction(
            {
                "date": "2025-04-04",
                "amount": "750",
                "category": "Meat Pie",
                "type": "Income",
            }
        )
        expense = parse_transaction(
            {
                "date": "2025-01-01",
                "amount": "25000",
                "category": "Rent",
                "type": "Expense",
            }
        )

        self.assertEqual((income["category"], income["type"]), ("revenue", "Meat Pie"))
        self.assertEqual((expense["category"], expense["type"]), ("expense", "Rent"))

    def test_analysis_uses_naira_totals_and_flags_comparable_outlier(self):
        amounts = [95, 100, 105, 110, 9000]
        transactions = [
            SimpleNamespace(
                id=index,
                date=datetime(2026, 1 + index // 3, 10),
                amount=amount,
                currency="NGN",
                exchange_rate_to_ngn=1,
                amount_ngn=amount,
                category="revenue",
                type="dine-in",
            )
            for index, amount in enumerate(amounts)
        ]
        transactions.append(
            SimpleNamespace(
                id=6,
                date=datetime(2026, 3, 12),
                amount=10,
                currency="USD",
                exchange_rate_to_ngn=1500,
                amount_ngn=15000,
                category="expense",
                type="ingredients",
            )
        )

        result = analyze_transactions(transactions)

        self.assertEqual(result["waterfall"]["revenue"], 9410)
        self.assertEqual(result["waterfall"]["expenses"], 15000)
        self.assertEqual([item["id"] for item in result["anomalies"]], [4])
        self.assertEqual(result["statistical_summary"]["transaction_count"], 6)
        self.assertEqual(result["statistical_summary"]["anomaly_count"], 1)
        report = build_report_pdf({"name": "Test Restaurant"}, transactions, result)
        self.assertEqual(report.read(4), b"%PDF")

    def test_anomaly_detection_waits_for_a_comparable_sample(self):
        transactions = [
            SimpleNamespace(
                id=index,
                date=datetime(2026, 1, index + 1),
                amount=amount,
                currency="NGN",
                exchange_rate_to_ngn=1,
                amount_ngn=amount,
                category="expense",
                type="staff",
            )
            for index, amount in enumerate([10, 10, 10000])
        ]

        result = analyze_transactions(transactions)

        self.assertEqual(result["anomalies"], [])
        self.assertEqual(result["statistical_summary"]["anomaly_percentage"], 0)

    def test_cookie_authenticated_mutations_require_a_csrf_token(self):
        client = app.test_client()
        with app.app_context():
            token = create_access_token(identity="test-user")
        client.set_cookie("access_token_cookie", token)

        response = client.post("/api/restaurants", json={"name": "Test"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(app.test_client().get("/dashboard").status_code, 401)

    def test_sqlite_registration_upload_analysis_and_pdf_download(self):
        client = app.test_client()
        registration = client.post(
            "/api/register",
            json={
                "username": "restaurant-owner",
                "email": "owner@example.com",
                "password": "a-strong-password",
            },
        )
        self.assertEqual(registration.status_code, 201)

        login = client.post(
            "/api/login",
            json={"username": "restaurant-owner", "password": "a-strong-password"},
        )
        self.assertEqual(login.status_code, 200)
        csrf = client.get_cookie("csrf_access_token").value
        headers = {"X-CSRF-TOKEN": csrf}

        created = client.post(
            "/api/restaurants",
            json={"name": "Test Kitchen"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201)
        restaurant_id = created.json["id"]

        uploaded = client.post(
            "/api/upload",
            data={
                "restaurant_id": str(restaurant_id),
                "file": (
                    io.BytesIO(
                        b"date,amount,currency,exchange_rate_to_ngn,category,type\n"
                        b"2026-01-03,12,NGN,,revenue,dine-in\n"
                    ),
                    "transactions.csv",
                ),
            },
            headers=headers,
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.get_data(as_text=True))

        analysis = client.get(
            f"/api/visualizations?restaurant_id={restaurant_id}"
        )
        self.assertEqual(analysis.status_code, 200)
        self.assertEqual(analysis.json["waterfall"]["revenue"], 12)

        backup = client.get(
            f"/api/restaurants/{restaurant_id}/transactions.csv"
        )
        self.assertEqual(backup.status_code, 200)
        self.assertIn(b"exchange_rate_to_ngn", backup.data)
        self.assertIn(b"2026-01-03", backup.data)

        report = client.post(
            "/api/generate_report",
            json={"restaurant_id": restaurant_id},
            headers=headers,
        )
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.data[:4], b"%PDF")

    def test_upload_bulk_inserts_5000_transactions(self):
        client = app.test_client()
        registration = client.post(
            "/api/register",
            json={
                "username": "bulk-import-owner",
                "email": "bulk-import@example.com",
                "password": "a-strong-password",
            },
        )
        self.assertEqual(registration.status_code, 201)
        login = client.post(
            "/api/login",
            json={"username": "bulk-import-owner", "password": "a-strong-password"},
        )
        self.assertEqual(login.status_code, 200)
        csrf = client.get_cookie("csrf_access_token").value
        headers = {"X-CSRF-TOKEN": csrf}
        created = client.post(
            "/api/restaurants",
            json={"name": "Bulk Import Test"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["date", "amount", "category", "type"])
        writer.writerows(
            (
                "2025-01-01",
                "1000" if index % 5 else "2000",
                "Chicken and Chips" if index % 5 else "Rent",
                "Income" if index % 5 else "Expense",
            )
            for index in range(5000)
        )
        uploaded = client.post(
            "/api/upload",
            data={
                "restaurant_id": str(created.json["id"]),
                "file": (
                    io.BytesIO(output.getvalue().encode("utf-8")),
                    "transactions.csv",
                ),
            },
            headers=headers,
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.get_data(as_text=True))
        self.assertEqual(uploaded.json["success_count"], 5000)

        analysis = client.get(
            f"/api/visualizations?restaurant_id={created.json['id']}"
        )
        self.assertEqual(analysis.status_code, 200)
        self.assertEqual(
            analysis.json["statistical_summary"]["transaction_count"],
            5000,
        )
        self.assertEqual(analysis.json["waterfall"]["revenue"], 4_000_000)
        self.assertEqual(analysis.json["waterfall"]["expenses"], 2_000_000)
        self.assertIn("Chicken and Chips", analysis.json["revenue_breakdown"])
        self.assertIn("Rent", analysis.json["expense_breakdown"])


if __name__ == "__main__":
    unittest.main()
