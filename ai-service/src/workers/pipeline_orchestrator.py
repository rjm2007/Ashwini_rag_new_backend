import json
import logging
import re
from pathlib import Path

from sqlalchemy import text

from ..config import settings
from ..database import SessionLocal
from ..services.s3_service import S3Service
from ..services.ocr_service import OcrService
from ..services.extraction_service import ExtractionService
from ..services.chunking_service import chunk_pages, chunk_text
from ..services.coverage_row_parser import parse_chunk_structured_meta
from ..services.embedding_service import prepare_chunks_for_upsert
from ..services.qdrant_service import QdrantService
from ..services.strategic_chunker import parse_vin_chassis_from_text

logger = logging.getLogger("pipeline")
logger.setLevel(logging.INFO)


async def update_document_status(document_id: str, status: str, repository: str | None = None) -> None:
    """This function updates processing status and optional repository in Postgres."""
    with SessionLocal() as session:
        if repository:
            session.execute(
                text(
                    "UPDATE documents SET processing_status = :status, current_repository = :repository, updated_at = NOW() WHERE id = :id"
                ),
                {"status": status, "repository": repository, "id": document_id},
            )
        else:
            session.execute(
                text("UPDATE documents SET processing_status = :status, updated_at = NOW() WHERE id = :id"),
                {"status": status, "id": document_id},
            )
        session.commit()


async def process_document(document_id: str, s3_path: str | None = None) -> None:
    """This function runs OCR, extraction, chunking, embedding, and vector upsert."""
    s3 = S3Service()
    ocr = OcrService()
    extractor = ExtractionService()
    qdrant = QdrantService()

    if not s3_path:
        with SessionLocal() as session:
            row = session.execute(text("SELECT s3_path FROM documents WHERE id = :id"), {"id": document_id}).first()
            if not row:
                return
            s3_path = row[0]

    try:
        logger.info("[%s] STEP 1/6 OCR start (s3=%s)", document_id, s3_path)
        await update_document_status(document_id, "ocr_in_progress")
        ocr_result = ocr.run_ocr(s3_path)
        page_count = len(ocr_result.get("pages", []))
        await s3.upload_json(f"ocr-output/{document_id}/ocr.json", ocr_result)
        logger.info("[%s] STEP 1/6 OCR done (pages=%d)", document_id, page_count)

        logger.info("[%s] STEP 2/6 Metadata extraction start", document_id)
        await update_document_status(document_id, "extraction_in_progress")
        plain_text = "\n".join([item["text"] for item in ocr_result.get("pages", [])])
        metadata = extractor.extract_metadata(plain_text)
        await s3.upload_json(f"extracted-text/{document_id}/text.json", {"text": plain_text})
        await s3.upload_json(f"processing-artifacts/{document_id}/metadata.json", metadata)
        logger.info(
            "[%s] STEP 2/6 Metadata extracted (make=%s model=%s year=%s text_chars=%d)",
            document_id,
            metadata.get("make"),
            metadata.get("model"),
            metadata.get("year"),
            len(plain_text),
        )

        # --- VIN/chassis regex fallback (LLM may miss these) ---
        regex_parsed = parse_vin_chassis_from_text(plain_text)
        if not metadata.get("vin") and regex_parsed.get("vin"):
            metadata["vin"] = regex_parsed["vin"]
            logger.info("[%s] VIN from regex fallback: %s", document_id, metadata["vin"])
        if not metadata.get("chassis_id") and regex_parsed.get("chassis_id"):
            metadata["chassis_id"] = regex_parsed["chassis_id"]
            logger.info("[%s] Chassis from regex fallback: %s", document_id, metadata["chassis_id"])

        # --- Derive year from effective_date if LLM didn't extract year ---
        if not metadata.get("year") and metadata.get("effective_date"):
            try:
                metadata["year"] = int(str(metadata["effective_date"])[:4])
                logger.info("[%s] Year derived from effective_date: %s", document_id, metadata["year"])
            except (ValueError, TypeError):
                pass

        # --- Normalize make/model for consistent Qdrant filtering ---
        raw_make = metadata.get("make") or ""
        if raw_make.lower() in ("volvo", "volvo truck", "volvo trucks"):
            metadata["make"] = "Volvo Truck"
        raw_model = metadata.get("model") or ""
        if raw_model:
            metadata["model"] = re.sub(r"\s+N$", "", raw_model).strip()

        logger.info(
            "[%s] Post-processed metadata: make=%s model=%s year=%s vin=%s chassis=%s",
            document_id,
            metadata.get("make"),
            metadata.get("model"),
            metadata.get("year"),
            metadata.get("vin"),
            metadata.get("chassis_id"),
        )

        with SessionLocal() as session:
            session.execute(
                text(
                    """
                    UPDATE documents
                    SET make = :make, model = :model, year = :year, warranty_type = :warranty_type,
                        country = :country, metadata_json = CAST(:metadata AS jsonb), processing_status = 'extraction_complete',
                        updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {
                    "id": document_id,
                    "make": metadata.get("make"),
                    "model": metadata.get("model"),
                    "year": metadata.get("year"),
                    "warranty_type": metadata.get("warranty_type"),
                    "country": metadata.get("country"),
                    "metadata": json.dumps(metadata),
                },
            )
            session.commit()

        logger.info("[%s] STEP 3/6 DB metadata update done", document_id)

        logger.info("[%s] STEP 4/6 Strategic chunking start", document_id)
        ocr_pages = ocr_result.get("pages", [])
        chunks = chunk_pages(ocr_pages, document_id=document_id) if ocr_pages else chunk_text(plain_text)
        logger.info("[%s] STEP 4/6 Chunked into %d pieces", document_id, len(chunks))

        filename = Path(s3_path).name if s3_path else f"{document_id}.pdf"

        logger.info("[%s] STEP 5/6 Contextual embed + sparse vectors", document_id)
        chunks = prepare_chunks_for_upsert(
            chunks,
            plain_text,
            enable_contextual=settings.enable_contextual_retrieval,
            enable_sparse=qdrant.hybrid,
        )

        enriched = []
        for chunk in chunks:
            item = dict(chunk)
            if not item.get("structuredMeta"):
                item["structuredMeta"] = parse_chunk_structured_meta(item)
            item["repository"] = "pending_review"
            item["documentId"] = document_id
            item["filename"] = filename
            item.update(
                {
                    "make": metadata.get("make"),
                    "model": metadata.get("model"),
                    "year": metadata.get("year"),
                    "country": metadata.get("country"),
                    "warrantyType": metadata.get("warranty_type"),
                    "vin": metadata.get("vin"),
                    "chassisId": metadata.get("chassis_id"),
                    "coverageSummary": metadata.get("coverage_summary"),
                }
            )
            enriched.append(item)

        qdrant.upsert_chunks(document_id, enriched)
        logger.info("[%s] STEP 6/6 Upserted %d chunks into Qdrant", document_id, len(enriched))
        new_s3_path = f"pending-review/{document_id}/original.pdf"
        await s3.move_object(s3_path, new_s3_path)
        logger.info("[%s] S3 moved to %s", document_id, new_s3_path)
        with SessionLocal() as session:
            session.execute(
                text(
                    "UPDATE documents SET s3_path = :s3_path, processing_status = 'ready_for_review', "
                    "current_repository = 'pending_review', updated_at = NOW() WHERE id = :id"
                ),
                {"s3_path": new_s3_path, "id": document_id},
            )
            session.commit()
        logger.info("[%s] DONE pipeline complete -> ready_for_review (s3_path=%s)", document_id, new_s3_path)
    except Exception as error:  # pylint: disable=broad-except
        logger.exception("[%s] FAILED pipeline error: %s", document_id, error)
        with SessionLocal() as session:
            session.execute(
                text(
                    "UPDATE documents SET processing_status = 'failed', error_message = :error, updated_at = NOW() WHERE id = :id"
                ),
                {"id": document_id, "error": str(error)},
            )
            session.commit()
