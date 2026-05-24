import json
import logging
from pathlib import Path

from ..services.llm_service import LlmService
from ..services.warranty_code_utils import enrich_metadata_with_codes

logger = logging.getLogger("metadata_filter")

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def extract_metadata_filters(question: str, conversation_history: list[dict] | None = None) -> dict:
    """Extract Qdrant filters, query rewrite, and BM25 keywords (small model)."""
    llm = LlmService()
    prompt = (_PROMPTS_DIR / "query_metadata_extraction.txt").read_text(encoding="utf-8")

    history_block = ""
    if conversation_history:
        lines = [
            f"{item.get('role', 'user')}: {item.get('content', '')}"
            for item in conversation_history[-6:]
        ]
        history_block = "\nCONVERSATION HISTORY:\n" + "\n".join(lines)

    output = llm.small_model_call(
        f"{prompt}{history_block}\n\nUSER QUESTION: {question}",
        "Extract metadata filters. Return JSON only.",
    )
    try:
        payload = json.loads(output)
        if isinstance(payload, dict):
            return enrich_metadata_with_codes(payload, question)
    except json.JSONDecodeError:
        logger.warning("Metadata filter JSON parse failed")

    return enrich_metadata_with_codes(
        {
            "make": None,
            "model": None,
            "year": None,
            "rewritten_query": question,
            "semantic_keywords": [],
            "component_synonyms": [],
            "extraction_confidence": 0.0,
        },
        question,
    )


def qdrant_filters_from_metadata(metadata: dict) -> dict:
    """Map extraction JSON to Qdrant payload filter keys."""
    filters: dict = {}
    if metadata.get("make"):
        filters["make"] = metadata["make"]
    if metadata.get("model"):
        filters["model"] = metadata["model"]
    if metadata.get("year") is not None:
        filters["year"] = metadata["year"]
    if metadata.get("country"):
        filters["country"] = metadata["country"]
    warranty_type = metadata.get("warranty_type") or metadata.get("warrantyType")
    if warranty_type:
        filters["warrantyType"] = warranty_type
    return filters
