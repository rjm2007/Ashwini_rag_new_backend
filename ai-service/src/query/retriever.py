import logging

from ..config import settings
from ..services.query_decomposer import decompose_question, should_decompose
from ..services.retrieval_pipeline import retrieve_with_pipeline
from ..services.reranker_service import is_list_or_filter_question
from ..services.warranty_code_utils import enrich_metadata_with_codes

logger = logging.getLogger("retriever")


def retrieve_chunks(
    question: str,
    metadata: dict | None = None,
    top_k: int = 10,
    list_mode: bool | None = None,
) -> list[dict]:
    """Hybrid retrieval with optional decomposition, quality gates, and parent expansion."""
    metadata = enrich_metadata_with_codes(metadata or {}, question)
    list_mode = is_list_or_filter_question(question) if list_mode is None else list_mode

    subqueries = None
    if settings.enable_query_decomposition and should_decompose(question):
        subqueries = decompose_question(question, metadata)

    chunks, trace = retrieve_with_pipeline(
        question,
        metadata,
        top_k=top_k,
        list_mode=list_mode,
        subqueries=subqueries,
    )
    logger.info("Retrieval pipeline trace: %s", trace)
    return chunks
