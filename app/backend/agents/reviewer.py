import json
import os

from google import genai
from models.schemas import ReviewResult

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """You are a senior legal contract reviewer. Analyze the following contract and return ONLY valid JSON with this structure:
{
  "clause_flags": [
    { "clause": "string", "issue": "string", "severity": "low" | "medium" | "high" }
  ],
  "risk_level": "low" | "medium" | "high",
  "summary": "string",
  "recommendations": ["string"]
}

Do not include any text outside the JSON object. Analyze thoroughly for:
- Unfavorable terms or one-sided clauses
- Missing standard protections
- Ambiguous language that could be exploited
- Liability and indemnification concerns
- Termination and renewal traps
- IP assignment issues"""


async def review_contract(contract_text: str) -> ReviewResult:
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Review this contract:\n\n{contract_text}",
        config={
            "system_instruction": SYSTEM_PROMPT,
            "temperature": 0.3,
        },
    )

    response_text = response.text or ""
    # Strip markdown code fences if present
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    data = json.loads(cleaned)
    return ReviewResult(**data)
