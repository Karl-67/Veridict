# Veridict — AI Contract Review

AI-powered legal contract review using a multi-agent LLM pipeline.

## Setup

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root (copy from `.env.example`):

```bash
cp .env.example .env
# Add your Anthropic API key to .env
```

Run the backend:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The app runs at http://localhost:5173 with the API at http://localhost:8000.

## Usage

1. Upload a contract PDF
2. Watch the multi-agent pipeline analyze it
3. Review the verdict with flagged clauses and recommendations
