-- Fix missing columns from migration 0005
-- Run this with: psql -U <user> -d veridict -f fix_db_schema.sql

-- Add missing columns to runs table
ALTER TABLE runs ADD COLUMN IF NOT EXISTS contract_edits JSON;

-- Add missing columns to findings table
ALTER TABLE findings ADD COLUMN IF NOT EXISTS recommended_change TEXT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMP;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP;

-- Create document_annotations table if it doesn't exist
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
);

-- Create indexes if they don't exist
CREATE INDEX IF NOT EXISTS ix_document_annotations_run_id ON document_annotations(run_id);
CREATE INDEX IF NOT EXISTS ix_document_annotations_clause_uid ON document_annotations(clause_uid);
CREATE INDEX IF NOT EXISTS ix_document_annotations_finding_id ON document_annotations(finding_id);
CREATE INDEX IF NOT EXISTS ix_document_annotations_author_id ON document_annotations(author_id);
CREATE INDEX IF NOT EXISTS ix_doc_annotation_run_clause ON document_annotations(run_id, clause_uid);

-- Update alembic version to 0005 if needed
-- UPDATE alembic_version SET version_num = '0005' WHERE version_num = '0004';
