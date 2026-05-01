# Database Schema Fix - Migration 0005

## Problem Summary

The application is experiencing multiple issues:
1. **Cannot view reports** - Runs fail during processing
2. **Processing not working** - Worker crashes with database errors
3. **Contracts not showing in dashboard** - API calls fail
4. **Cannot load contract details** - Database schema mismatch

## Root Cause

The database schema is missing columns from migration `0005_add_contract_edits.py`. This migration was created but never applied to the database.

### Missing Schema Elements

**findings table:**
- `recommended_change` (TEXT) - Stores suggested text replacements
- `dismissed_at` (TIMESTAMP) - When a finding was dismissed
- `accepted_at` (TIMESTAMP) - When a finding was accepted

**runs table:**
- `contract_edits` (JSON) - Stores contract edit history

**New table:**
- `document_annotations` - Stores user annotations on contract clauses

### Error Messages

```
psycopg2.errors.UndefinedColumn: column "recommended_change" of relation "findings" does not exist
asyncpg.exceptions.UndefinedColumnError: column findings.recommended_change does not exist
```

## Solution

Apply the missing schema changes using one of these methods:

### Method 1: Python Script (Recommended)

```bash
python apply_missing_migration.py
```

This script will:
- Add missing columns to `findings` and `runs` tables
- Create the `document_annotations` table
- Create all necessary indexes
- Show clear success/error messages

### Method 2: SQL Script

```bash
psql -U <username> -d veridict -f fix_db_schema.sql
```

Or connect to your database and run the SQL commands manually.

### Method 3: Alembic (If working)

```bash
cd app/backend
alembic upgrade head
```

## Verification

After applying the fix, verify the schema:

```sql
-- Check findings table columns
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'findings' 
  AND column_name IN ('recommended_change', 'dismissed_at', 'accepted_at');

-- Check runs table columns
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'runs' 
  AND column_name = 'contract_edits';

-- Check document_annotations table exists
SELECT table_name 
FROM information_schema.tables 
WHERE table_name = 'document_annotations';
```

## Post-Fix Steps

1. **Restart the worker process** - The worker needs to be restarted to pick up the schema changes
2. **Restart the backend API** - The API server should be restarted
3. **Test a new contract upload** - Upload a test contract to verify processing works
4. **Check the dashboard** - Verify contracts are now visible

## Files Created

- `fix_db_schema.sql` - SQL script to apply schema changes
- `apply_missing_migration.py` - Python script to apply schema changes
- `FIX_README.md` - This documentation file

## Prevention

To prevent this issue in the future:
1. Always run `alembic upgrade head` after pulling new migrations
2. Check `alembic current` to verify the database is up to date
3. Add migration checks to deployment scripts
4. Consider adding a startup check that validates schema matches models
