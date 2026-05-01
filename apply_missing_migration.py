#!/usr/bin/env python3
"""
Apply missing database schema changes from migration 0005.
Run this from the project root: python apply_missing_migration.py
"""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "app" / "backend"))

from sqlalchemy import text
from app.backend.db.session import get_sync_engine

def apply_migration():
    engine = get_sync_engine()
    
    with engine.begin() as conn:
        print("Applying missing schema changes from migration 0005...")
        
        # Add columns to runs table
        try:
            conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS contract_edits JSON"))
            print("✓ Added contract_edits to runs table")
        except Exception as e:
            print(f"⚠ runs.contract_edits: {e}")
        
        # Add columns to findings table
        try:
            conn.execute(text("ALTER TABLE findings ADD COLUMN IF NOT EXISTS recommended_change TEXT"))
            print("✓ Added recommended_change to findings table")
        except Exception as e:
            print(f"⚠ findings.recommended_change: {e}")
        
        try:
            conn.execute(text("ALTER TABLE findings ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMP"))
            print("✓ Added dismissed_at to findings table")
        except Exception as e:
            print(f"⚠ findings.dismissed_at: {e}")
        
        try:
            conn.execute(text("ALTER TABLE findings ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP"))
            print("✓ Added accepted_at to findings table")
        except Exception as e:
            print(f"⚠ findings.accepted_at: {e}")
        
        # Create document_annotations table
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS document_annotations (
                    id VARCHAR(36) PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    clause_uid VARCHAR(128) NOT NULL,
                    page_number INTEGER,
                    selected_text TEXT,
                    span_start INTEGER,
                    span_end INTEGER,
                    annotation_type VARCHAR(16) NOT NULL DEFAULT 'comment',
                    body TEXT NOT NULL,
                    suggested_replacement TEXT,
                    status VARCHAR(16) NOT NULL DEFAULT 'open',
                    source VARCHAR(8) NOT NULL DEFAULT 'human',
                    finding_id VARCHAR(36) REFERENCES findings(id) ON DELETE SET NULL,
                    author_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
            print("✓ Created document_annotations table")
        except Exception as e:
            print(f"⚠ document_annotations table: {e}")
        
        # Create indexes
        indexes = [
            ("ix_document_annotations_run_id", "document_annotations", "run_id"),
            ("ix_document_annotations_clause_uid", "document_annotations", "clause_uid"),
            ("ix_document_annotations_finding_id", "document_annotations", "finding_id"),
            ("ix_document_annotations_author_id", "document_annotations", "author_id"),
        ]
        
        for idx_name, table, col in indexes:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({col})"))
                print(f"✓ Created index {idx_name}")
            except Exception as e:
                print(f"⚠ {idx_name}: {e}")
        
        # Create composite index
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_doc_annotation_run_clause ON document_annotations(run_id, clause_uid)"))
            print("✓ Created composite index ix_doc_annotation_run_clause")
        except Exception as e:
            print(f"⚠ ix_doc_annotation_run_clause: {e}")
        
        print("\n✅ Schema migration completed successfully!")
        print("\nNote: You may need to update alembic_version table manually:")
        print("  UPDATE alembic_version SET version_num = '0005' WHERE version_num = '0004';")

if __name__ == "__main__":
    try:
        apply_migration()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)
