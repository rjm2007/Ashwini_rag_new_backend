import logging

from .intent_classifier import classify_intent
from .metadata_filter import extract_metadata_filters, qdrant_filters_from_metadata, _is_valid_year
from ..config import settings
from ..services.aggregation_engine import is_aggregation_query, aggregate
from ..services.reranker_service import is_list_or_filter_question
from ..services.structured_query_engine import is_simple_retrieval_query, is_structured_query
from .query_mode import is_hallucination_probe
from .retriever import retrieve_chunks
from .reasoner import reason_over_evidence
logger = logging.getLogger(__name__)

GREETING_REPLY = (
    "Hi! I'm your Fixyee warranty assistant. "
    "Ask me about coverage, exclusions, claim codes, or a specific vehicle "
    "(make, model, year, or VIN) and I'll answer from your certified warranty documents."
)

OUT_OF_SCOPE_REPLY = (
    "I can only help with warranty coverage questions based on your certified warranty documents. "
    "Try asking whether a component is covered, what the warranty period is, or what applies to a specific VIN."
)

INJECTION_REPLY = (
    "I can't change document status or system settings from chat. "
    "Please ask a warranty coverage question, or use the review workflow in the app."
)


def compute_confidence(result: dict) -> float:
    factors = result.get("confidence_factors", {})
    values = [
        float(factors.get("evidence_strength", 0)),
        float(factors.get("clause_clarity", 0)),
        float(factors.get("metadata_match", 0)),
    ]
    return round(sum(values) / len(values), 2) if values else 0.0


def _is_simple_greeting(question: str) -> bool:
    text = (question or "").strip().lower().rstrip("!?.")
    return text in {
        "hi",
        "hello",
        "hey",
        "hola",
        "good morning",
        "good afternoon",
        "good evening",
        "hi there",
        "hello there",
    }


async def answer_question(question: str, conversation_history: list[dict]) -> dict:
    """Intent routing → metadata extraction → hybrid retrieval → large-model reasoning."""
    if _is_simple_greeting(question):
        return {
            "answer": GREETING_REPLY,
            "evidence": [],
            "confidence": 0.95,
            "filters": {},
            "intent": "greeting_or_smalltalk",
        }

    # Count / group-by / "all vehicles" → deterministic full-scan, not retrieval.
    if is_aggregation_query(question):
        logger.info("Aggregation path engaged for question: %.80s", question)
        return aggregate(question)

    classification = classify_intent(question, conversation_history)
    intent = classification.get("intent", "warranty_coverage")

    if intent == "greeting_or_smalltalk":
        return {
            "answer": GREETING_REPLY,
            "evidence": [],
            "confidence": 0.95,
            "filters": {},
            "intent": intent,
        }

    if intent == "prompt_injection_attempt":
        return {
            "answer": INJECTION_REPLY,
            "evidence": [],
            "confidence": 0.1,
            "filters": {},
            "intent": intent,
        }

    if intent == "out_of_scope":
        return {
            "answer": OUT_OF_SCOPE_REPLY,
            "evidence": [],
            "confidence": 0.1,
            "filters": {},
            "intent": intent,
        }

    if intent == "ambiguous":
        clarification = classification.get("clarification_question") or (
            "Which vehicle or component are you asking about? "
            "Please include make, model, year, or VIN if you can."
        )
        return {
            "answer": clarification,
            "evidence": [],
            "confidence": float(classification.get("confidence", 0.3)),
            "filters": {},
            "intent": intent,
        }

    metadata = extract_metadata_filters(question, conversation_history)
    filters = qdrant_filters_from_metadata(metadata)

    logger.info(
        "Query filters applied: %s | Query: %.80s | "
        "Extracted metadata: make=%s, model=%s, year=%s (valid=%s), "
        "mileage=%s, vin=%s, chassisId=%s",
        filters,
        question,
        metadata.get("make"),
        metadata.get("model"),
        metadata.get("year"),
        _is_valid_year(metadata.get("year")),
        metadata.get("mileage"),
        metadata.get("vin"),
        metadata.get("chassis_id") or metadata.get("chassisId"),
    )

    list_mode = is_list_or_filter_question(question)
    table_mode = (
        list_mode
        or is_hallucination_probe(question)
        or (settings.enable_structured_reasoning and is_structured_query(question))
    )
    chunks = retrieve_chunks(question, metadata, list_mode=list_mode)
    reasoned = reason_over_evidence(
        question,
        conversation_history,
        chunks,
        table_mode=table_mode,
    )

    evidence = []
    for index in reasoned.get("evidence_used", []):
        position = index - 1
        if position >= 0 and position < len(chunks):
            evidence.append(chunks[position]["payload"])

    return {
        "answer": reasoned.get("answer", "No answer generated."),
        "evidence": evidence,
        "confidence": compute_confidence(reasoned),
        "filters": filters,
        "metadata": metadata,
        "coverageDecision": reasoned.get("coverage_decision", "insufficient_evidence"),
        "intent": intent,
        "queryMode": {
            "structured": settings.enable_structured_reasoning and is_structured_query(question),
            "simpleRetrieval": is_simple_retrieval_query(question),
            "tableMode": table_mode,
        },
    }
