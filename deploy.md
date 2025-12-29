# Deployment Guide for Digital Ocean App Platform

## 1. Build & Run Commands

Digital Ocean's Python Buildpack will automatically detect the `Procfile`.

- **Build Command**: (Leave default or use standard pip install)
  ```bash
  pip install -r requirements.txt
  ```
- **Run Command**: (The Procfile handles this)
  ```bash
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
  ```

## 2. Environment Variables

You need to add the following environment variables in the **Environment** tab of your Digital Ocean App.
Copy these values from your local `.env.local` file.

| Key | Value (Example/Description) |
| --- | --- |
| `POSTGRES_DB_URL` | `postgresql+asyncpg://user:pass@host:port/dbname` |
| `PHONEPE_BASE_URL`* | `https://api-preprod.phonepe.com/apis/pg-sandbox` (UAT) or Prod URL |
| `MERCHANT_ID` | Your PhonePe Merchant ID |
| `SALT_KEY` | Your PhonePe Salt Key |
| `SALT_KEY_INDEX` | Salt Key Index (e.g., `1`) |
| `STORE_ID` | Store ID |
| `TERMINAL_ID` | Terminal ID |
| `TRANSACTION_ENDPOINT` | `/pg/v1/pay` |
| `QR_INIT_ENDPOINT` | `/pg/v1/pay` (or specific QR endpoint) |
| `EDC_ENDPOINT` | `/v1/edc/init` (Check your specific endpoint) |
| `X_PROVIDER_ID` | Provider ID |
| `PHONEPE_CALLBACK_URL` | Your deployed app URL + `/payments/webhook/phonepe` |
| `PI_KEY` | Rista API Key |
| `SECRET_KEY` | Rista Secret Key |
| `BRANCH_CODE` | Rista Branch Code |
| `RISTA_BASE_URL` | Rista Base URL |
| `REDIS_HOST` | Hostname of your Redis component in DO (e.g. `redis-component-name`) |

> [!NOTE]
> * `PHONEPE_BASE_URL` replaced `UAT_BASE_URL` in your recent changes. Ensure you use the new key.
> * If you are using a Managed Database in Digital Ocean, `POSTGRES_DB_URL` will be provided by a "bind" variable usually, or you can manually set it.
> * For Redis, if you add a Redis component to your App, use its internal hostname.

## 3. Port Configuration

- Ensure the **HTTP Port** is set to **8080** in the App Spec/Settings, matching the `Procfile` command.
