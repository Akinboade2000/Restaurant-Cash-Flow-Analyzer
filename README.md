# Restaurant Cash Flow Analyzer

A restaurant cash-flow dashboard with NGN-normalized analysis, transaction anomaly review, CSV/XLSX imports, and downloadable PDF reports. The web UI is a static Netlify site, the Flask API runs on Vercel, and persistent hosted data is stored in a Turso **libSQL** database.

The PDF dashboard report includes the financial indicators, monthly cash-flow chart, all revenue and expense category chart entries, complete category breakdowns, and every flagged transaction with its review reason. Long category charts continue across pages.

> **Database driver:** `sqlalchemy-libsql` is currently marked experimental by its maintainers and supports Linux/macOS, not Windows. It is installed only in the Vercel Linux runtime. On Windows, the app continues to use a local SQLite file for development.

## Run locally

1. Install Python 3.11 or newer and install the app dependencies in PowerShell:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and set a private random `JWT_SECRET_KEY`. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_SENDER` with your email provider's SMTP settings to enable password reset emails. `PUBLIC_APP_URL` is the origin used in reset links; it defaults to the current request origin if unset. By default, the local SQLite database is `backend\instance\restaurant_cashflow.db`.
3. Start the Flask app from the repository root:

   ```powershell
   python backend\app.py
   ```

4. Open `http://127.0.0.1:5000`.

The app adds missing NGN exchange-rate columns to an existing SQLite database without deleting its records. If the old database contains an `exchange_rate` table, its latest matching NGN conversion rate is used when migrating existing foreign-currency transactions.

## Deploy the API to Vercel

Vercel uses Python 3.12 as pinned in `.python-version`.

1. Create a Turso **libSQL** database (the existing SQLAlchemy adapter connects to libSQL, not the separate TursoDB engine). The Turso CLI commands are `turso db create restaurant-cash-flow` and `turso db tokens create restaurant-cash-flow`. Keep the returned token private.
2. Import the Git repository into Vercel and deploy it using the root `vercel.json`. The Vercel deployment serves the Flask API function in `api/index.py`.
3. In the Vercel project settings, add these environment variables for the deployment environment:
   - `TURSO_DATABASE_URL` — the database URL beginning with `libsql://`.
   - `TURSO_AUTH_TOKEN` — the private token generated for that database.
   - `JWT_SECRET_KEY` — a long, unique random secret.
   - `COOKIE_SECURE` — `true`.
   - `PUBLIC_APP_URL` — the HTTPS origin of your Netlify website.
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_SENDER` — SMTP delivery settings from your email provider. Use the provider's recommended STARTTLS port (usually `587`) and a sender address authorized for that SMTP account.
4. Redeploy after saving the environment variables. Copy the production Vercel deployment origin, for example `https://your-api.vercel.app`.

The login page's **Forgot your password?** link sends a one-hour, single-use reset link to the registered email address. Configure SMTP before using this feature in production.

The app requires both Turso variables when running on Vercel; it will not silently fall back to a temporary SQLite file there.

## Deploy the website to Netlify

1. Import the same Git repository as a Netlify site. `netlify.toml` runs `scripts/build_netlify.py` and publishes the generated `dist` folder. This creates static pages from the existing templates.
2. In Netlify site settings, set `VERCEL_API_URL` to the HTTPS origin of the production Vercel deployment (no path or trailing slash), for example `https://your-api.vercel.app`.
3. Trigger a new Netlify deploy. The generated `dist/_redirects` proxies `/api/*` to Vercel, so the browser uses same-origin requests and the authentication cookies/CSRF checks work without wildcard CORS.
4. Open the Netlify site URL and create an account.

Deploy Vercel first, then set the Vercel URL in Netlify. Redeploy Netlify whenever the API origin changes. Use your providers' current pricing and usage limits to confirm the free tiers fit your needs; quotas and policies can change.

## Move existing transaction data

The SQLite database files are excluded from Git so private records are not included in deployments. The hosted Turso database starts empty; local users and passwords are not transferred. While signed into the local app, use **Back up transactions CSV** for each restaurant. Then create an account and restaurant on the Netlify site and upload those CSV backups. The exports preserve recorded currency and exchange rates.

## Import format

CSV and XLSX files need these columns:

| Column | Required | Meaning |
|---|---|---|
| `date` | Yes | `YYYY-MM-DD` or `DD/MM/YYYY` |
| `amount` | Yes | A non-negative numeric amount in the transaction's currency |
| `category` | Yes | `revenue` or `expense`; `income`, `sales`, and `expenditure` are also recognized |
| `type` | Yes | A comparable sales source or expense category, such as `dine-in`, `delivery`, `ingredients`, or `staff`. Files with a product/cost in `category` and `Income`/`Expense` in `type` are also recognized; the product/cost becomes the transaction type. |
| `currency` | No | Three-letter code; defaults to `NGN` |
| `exchange_rate_to_ngn` | For non-NGN | Naira per one unit of the transaction currency; NGN is always treated as rate `1` |
| `description` | No | Optional transaction note |

Each import is validated before any existing rows are removed; an invalid row rejects the entire import and leaves the current dataset unchanged. A successful upload replaces all transactions for the selected restaurant, then analyzes only the new dataset. Download a CSV backup first if you need to preserve the previous dataset. Anomaly review compares amounts within groups that share category, transaction type, and currency. Groups need at least four records to be evaluated; an anomaly is a review prompt, not proof of an error.

## Project credits

- **Author:** Akinboade Precious Akinkunmi
- **Institution:** Obafemi Awolowo University, Ile-Ife
- **Department:** Computer Science and Engineering
- **Supervisor:** Prof. (Mrs.) H.A. Soriyan
- **Contributor:** Dr. Gambo
- **Data source:** Kaggle synthetic financial datasets

Project media submitted with the repository remains available as `1.png`–`6.png` and `Final Project works.mp4`.
