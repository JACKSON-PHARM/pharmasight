# PharmaSight Setup Guide

## Prerequisites

- Python 3.10+
- Supabase account (free tier)
- PostgreSQL client (optional, for direct DB access)

## Step 1: Supabase Setup

1. Create a new Supabase project at https://supabase.com
2. Go to **Settings** → **Database**
3. Copy your connection details:
   - Host
   - Database name
   - Port
   - User
   - Password

## Step 2: Database Schema

1. Open Supabase SQL Editor
2. Copy contents of `database/schema.sql`
3. Paste and run in SQL Editor
4. Verify tables are created (check Tables in Supabase dashboard)

## Step 3: Environment Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your Supabase credentials:
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-key
   SUPABASE_DB_HOST=db.your-project.supabase.co
   SUPABASE_DB_PORT=5432
   SUPABASE_DB_NAME=postgres
   SUPABASE_DB_USER=postgres
   SUPABASE_DB_PASSWORD=your-password
   ```

## Step 4: Backend Setup

1. Navigate to backend directory:
   ```bash
   cd backend
   ```

2. Create virtual environment:
   ```bash
   python -m venv venv
   ```

3. Activate virtual environment:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Step 5: Run the Application

1. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```

2. Access the API:
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs
   - Health: http://localhost:8000/health

## Step 6: Initial Data Setup

After running the schema, you'll need to:

1. Create a company (via API or direct SQL)
2. Create a branch
3. Set up admin user (via Supabase Auth)
4. Link user to branch with admin role

## Next Steps

- Implement authentication
- Build item management APIs
- Build inventory ledger APIs
- Build sales invoice APIs
- Build purchase/GRN APIs

## Troubleshooting

### Database Connection Issues
- Verify Supabase connection string
- Check firewall settings
- Ensure database is accessible

### Import Errors
- Ensure virtual environment is activated
- Verify all dependencies are installed
- Check Python version (3.10+)

### Schema Errors
- Run schema.sql in order
- Check for existing tables
- Verify UUID extension is enabled

