# PharmaSight - Pharmacy Management System

## 🚀 Quick Start (Local Development)

**Windows Users - Easiest Way:**
```batch
# Just double-click or run:
start.bat
```

This single command starts both backend and frontend servers!

**Other Options:**
- PowerShell: `.\start.ps1`
- Python: `python start.py`

See `QUICK_START.md` for more details.

---

## About PharmaSight - Pharmacy Management System

A production-grade pharmacy management system built for retail pharmacies in Kenya, designed with inventory intelligence at its core.

## 🎯 Core Principles

- **Inventory Ledger First**: All stock movements are append-only ledger entries
- **Base Unit Storage**: Inventory stored in smallest sellable unit (tablets, ml, etc.)
- **Breaking Bulk**: Automatic conversion between packs and pieces
- **KRA Compliant**: Full VAT handling, sequential invoices, audit-safe transactions
- **FEFO Logic**: First Expiry First Out for batch management
- **Cost-Based Pricing**: Intelligent pricing with batch-aware margins

## 🛠️ Tech Stack

- **Backend**: Python (FastAPI)
- **Database**: PostgreSQL (Supabase)
- **Auth**: Supabase Auth
- **Hosting**: Render (Free Tier)
- **Development**: Cursor + LLMs

## 📁 Project Structure

```
pharmasight/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── api/
│   │   └── services/
│   └── requirements.txt
├── database/
│   └── schema.sql
├── .env.example
└── README.md
```

## 🚀 Getting Started

1. Set up Supabase project
2. Run `database/schema.sql` in Supabase SQL editor
3. Configure environment variables
4. Install dependencies: `pip install -r backend/requirements.txt`
5. Run backend: `uvicorn app.main:app --reload`

## Deploying on Render

Use the `render.yaml` in this directory (or connect the `pharmasight` folder to Render). In **Render Dashboard → Service → Environment**, set:

| Variable | Required | Description |
|----------|----------|-------------|
| **ADMIN_PASSWORD** | Yes | Password for admin panel. Log in with username **admin** and this password. |
| **APP_PUBLIC_URL** | No* | Your app URL (e.g. `https://pharmasight.onrender.com`). If unset, invite links are built from the request (so they work on Render without setting this). |
| **SMTP_HOST**, **SMTP_USER**, **SMTP_PASSWORD** | To send emails | Required for “Send invite email”. Without these, the invite link is still created and shown in the UI so you can copy and share it; email just won’t be sent. |
| DATABASE_URL, SUPABASE_* | As needed | Same as local development. |

\* Set **APP_PUBLIC_URL** if you use a custom domain or a different URL than the request host.

## 📊 Key Features

- Multi-branch inventory management
- Real-time stock tracking with expiry awareness
- Automated procurement recommendations
- KRA-compliant invoicing (VAT, credit notes)
- Cost-based pricing with margin intelligence
- Breaking bulk (pack to piece conversion)
- FEFO batch allocation
- Comprehensive reporting

## 🔐 Security & Compliance

- No credential storage
- User-authorized sessions only
- Audit trail on all transactions
- KRA-compliant document numbering
- Immutable financial records

