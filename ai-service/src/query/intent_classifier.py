import json
import logging
from pathlib import Path

from ..services.llm_service import LlmService

logger = logging.getLogger("intent_classifier")

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_DEFAULT = {
    "intent": "warranty_coverage",
    "confidence": 0.5,
    "requires_retrieval": True,
    "needs_clarification": False,
    "clarification_question": None,
    "abuse_signal": False,
    "scope_reason": "",
    "language": "en",
}


def classify_intent(question: str, conversation_history: list[dict] | None = None) -> dict:
    """Classify user intent and routing hints (small model)."""
    llm = LlmService()
    prompt = (_PROMPTS_DIR / "intent_classification.txt").read_text(encoding="utf-8")

    history_block = ""
    if conversation_history:
        lines = [
            f"{item.get('role', 'user')}: {item.get('content', '')}"
            for item in conversation_history[-6:]
        ]
        history_block = "\nCONVERSATION HISTORY:\n" + "\n".join(lines)

    output = llm.small_model_call(
        f"{prompt}{history_block}\n\nUSER QUESTION: {question}",
        "Classify intent. Return JSON only.",
    )
    try:
        payload = json.loads(output)
        if isinstance(payload, dict):
            merged = {**_DEFAULT, **payload}
            return merged
    except json.JSONDecodeError:
        logger.warning("Intent JSON parse failed, defaulting to warranty_coverage")

    lowered = (question or "").strip().lower()
    if lowered in {"hi", "hello", "hey", "hola", "good morning", "good afternoon", "good evening"}:
        return {
            **_DEFAULT,
            "intent": "greeting_or_smalltalk",
            "confidence": 0.95,
            "requires_retrieval": False,
            "scope_reason": "Short greeting detected via fallback.",
        }

    return dict(_DEFAULT)
