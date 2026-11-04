import base64
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from reportlab.lib import colors


sys.path.insert(0, str(Path(__file__).resolve().parent))

test_database_directory = tempfile.TemporaryDirectory(prefix="rcf-sqlite-tests-")
os.environ["DATABASE_PATH"] = str(Path(test_database_directory.name) / "test.sqlite")
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-restaurant-analysis"


def extract_pdf_streams(pdf_bytes):
    content = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.DOTALL):
        try:
            encoded = stream.strip()
            if encoded.endswith(b"~>"):
                encoded = base64.a85decode(encoded[:-2])
            content.append(zlib.decompress(encoded))
        except (ValueError, zlib.error):
            continue
    return b"\n".join(content)


from app import (
    analyze_transactions,
    app,
    build_category_charts,
    build_report_pdf,
    create_database_settings,
    parse_transaction,
)
from flask_jwt_extended import create_access_token
from model import PasswordResetToken, db
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
            login = (output_path / "login.html").read_text(encoding="utf-8")
            self.assertIn('href="/"', login)
            self.assertIn("Back to home page", login)
            self.assertTrue((output_path / "forgot_password.html").exists())
            self.assertTrue((output_path / "reset_password.html").exists())
            self.assertIn("/forgot-password /forgot_password.html 200", redirects)
            self.assertIn("/reset-password /reset_password.html 200", redirects)
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
        report_content = extract_pdf_streams(report.getvalue())
        for section in (
            b"Monthly cash flow",
            b"Revenue by source",
            b"Expenses by category",
            b"Operating indicators",
            b"Transactions to check",
            b"Why it was flagged",
            b"Unusual revenue amount",
        ):
            self.assertIn(section, report_content)

        category_charts = build_category_charts(
            {f"Source {index}": 1000 - index for index in range(25)},
            colors.HexColor("#21865b"),
            "No revenue transactions.",
        )
        self.assertEqual(len(category_charts), 2)

        all_anomalies = [
            {**result["anomalies"][0], "reason": f"Review evidence {index:03d}"}
            for index in range(1, 102)
        ]
        complete_analysis = {
            **result,
            "anomalies": all_anomalies,
            "statistical_summary": {
                **result["statistical_summary"],
                "anomaly_count": len(all_anomalies),
            },
        }
        complete_report = build_report_pdf(
            {"name": "Test Restaurant"}, transactions, complete_analysis
        ).getvalue()
        self.assertIn(b"Review evidence 101", extract_pdf_streams(complete_report))

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

    def test_password_reset_email_flow_uses_expiring_single_use_tokens(self):
        client = app.test_client()
        reset_page = client.get("/reset-password?token=example")
        self.assertEqual(reset_page.status_code, 200)
        self.assertEqual(reset_page.headers["Cache-Control"], "no-store")
        self.assertEqual(reset_page.headers["Referrer-Policy"], "no-referrer")

        registration = client.post(
            "/api/register",
            json={
                "username": "password-reset-owner",
                "email": "password-reset@example.com",
                "password": "old-strong-password",
            },
        )
        self.assertEqual(registration.status_code, 201)

        with mock.patch.dict(
            os.environ, {"PUBLIC_APP_URL": "https://restaurant.example"}
        ), mock.patch("app.send_password_reset_email") as send_email:
            unknown_email = client.post(
                "/api/password-reset/request",
                json={"email": "unknown@example.com"},
            )
            self.assertEqual(unknown_email.status_code, 200)
            self.assertEqual(
                unknown_email.json["message"],
                "If an account exists for that email, a reset link has been sent.",
            )
            send_email.assert_not_called()

            request_reset = client.post(
                "/api/password-reset/request",
                json={"email": "PASSWORD-RESET@example.com"},
            )

        self.assertEqual(request_reset.status_code, 200)
        send_email.assert_called_once()
        recipient, reset_url = send_email.call_args.args
        self.assertEqual(recipient, "password-reset@example.com")
        self.assertTrue(reset_url.startswith("https://restaurant.example/reset-password?"))
        token = parse_qs(urlsplit(reset_url).query)["token"][0]

        with app.app_context():
            reset_record = PasswordResetToken.query.one()
            self.assertEqual(
                reset_record.token_hash,
                hashlib.sha256(token.encode("utf-8")).hexdigest(),
            )
            reset_record.expires_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            ) - timedelta(seconds=1)
            db.session.commit()

        expired = client.post(
            "/api/password-reset/confirm",
            json={"token": token, "password": "new-strong-password"},
        )
        self.assertEqual(expired.status_code, 400)

        with app.app_context():
            reset_record = PasswordResetToken.query.one()
            reset_record.expires_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            ) + timedelta(hours=1)
            db.session.commit()

        updated = client.post(
            "/api/password-reset/confirm",
            json={"token": token, "password": "new-strong-password"},
        )
        self.assertEqual(updated.status_code, 200)
        reused = client.post(
            "/api/password-reset/confirm",
            json={"token": token, "password": "another-strong-password"},
        )
        self.assertEqual(reused.status_code, 400)
        old_login = client.post(
            "/api/login",
            json={
                "username": "password-reset-owner",
                "password": "old-strong-password",
            },
        )
        new_login = client.post(
            "/api/login",
            json={
                "username": "password-reset-owner",
                "password": "new-strong-password",
            },
        )
        self.assertEqual(old_login.status_code, 401)
        self.assertEqual(new_login.status_code, 200)

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
        self.assertIn("Replaced the dataset", uploaded.json["message"])
        self.assertEqual(uploaded.json["success_count"], 5000)

        initial_analysis = client.get(
            f"/api/visualizations?restaurant_id={created.json['id']}"
        )
        self.assertEqual(initial_analysis.status_code, 200)
        self.assertEqual(
            initial_analysis.json["statistical_summary"]["transaction_count"],
            5000,
        )
        self.assertEqual(initial_analysis.json["waterfall"]["revenue"], 4_000_000)
        self.assertEqual(initial_analysis.json["waterfall"]["expenses"], 2_000_000)

        replacement = client.post(
            "/api/upload",
            data={
                "restaurant_id": str(created.json["id"]),
                "file": (
                    io.BytesIO(
                        b"date,amount,category,type\n"
                        b"2025-02-01,750,Meat Pie,Income\n"
                    ),
                    "replacement.csv",
                ),
            },
            headers=headers,
        )
        self.assertEqual(
            replacement.status_code,
            201,
            replacement.get_data(as_text=True),
        )

        invalid_upload = client.post(
            "/api/upload",
            data={
                "restaurant_id": str(created.json["id"]),
                "file": (
                    io.BytesIO(
                        b"date,amount,category,type\n"
                        b"not-a-date,invalid,Rent,Expense\n"
                    ),
                    "invalid.csv",
                ),
            },
            headers=headers,
        )
        self.assertEqual(invalid_upload.status_code, 422)

        analysis = client.get(
            f"/api/visualizations?restaurant_id={created.json['id']}"
        )
        self.assertEqual(analysis.status_code, 200)
        self.assertEqual(
            analysis.json["statistical_summary"]["transaction_count"],
            1,
        )
        self.assertEqual(analysis.json["waterfall"]["revenue"], 750)
        self.assertEqual(analysis.json["waterfall"]["expenses"], 0)
        self.assertIn("Meat Pie", analysis.json["revenue_breakdown"])
        self.assertNotIn("Chicken and Chips", analysis.json["revenue_breakdown"])
        self.assertNotIn("Rent", analysis.json["expense_breakdown"])


if __name__ == "__main__":
    unittest.main()
