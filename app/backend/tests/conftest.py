import os

# Set minimum env vars before any app module is imported at collection time.
os.environ.setdefault("POSTGRES_DSN", "postgresql://verdict:verdict@localhost:5432/verdict")
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-not-for-production")
os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.setdefault("ALLOWED_FRONTEND_ORIGINS", '["http://localhost:5173"]')
os.environ.setdefault("DOCUMENT_STORAGE_PATH", "/tmp/verdict-docs")
os.environ.setdefault("RAG_STORAGE_PATH", "/tmp/verdict-rag")
