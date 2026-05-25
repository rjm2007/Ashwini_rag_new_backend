import hashlib
import logging

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Modifier,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from ..config import settings

logger = logging.getLogger("qdrant")


class QdrantService:
    """Qdrant upsert, hybrid search (dense + BM25 + RRF), and repository updates."""

    SEARCHABLE_KEYS = {"make", "model", "year", "country", "warrantyType", "vin", "chassisId"}

    def __init__(self) -> None:
        api_key = settings.qdrant_api_key or None
        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=api_key,
            check_compatibility=False,
        )
        self.collection = settings.qdrant_collection
        self.hybrid = self._ensure_collection()

    def _ensure_collection(self) -> bool:
        """Create hybrid collection if missing; detect legacy single-vector collections."""
        existing = [item.name for item in self.client.get_collections().collections]
        if self.collection not in existing:
            logger.info("Creating hybrid collection '%s' (dense + bm25_sparse)", self.collection)
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config={
                    "dense": VectorParams(size=settings.embedding_dims, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    "bm25_sparse": SparseVectorParams(modifier=Modifier.IDF),
                },
            )
            for field_name, schema in [
                ("repository", PayloadSchemaType.KEYWORD),
                ("documentId", PayloadSchemaType.KEYWORD),
                ("make", PayloadSchemaType.KEYWORD),
                ("model", PayloadSchemaType.KEYWORD),
                ("year", PayloadSchemaType.INTEGER),
                ("warrantyType", PayloadSchemaType.KEYWORD),
                ("filename", PayloadSchemaType.KEYWORD),
                ("chunkRole", PayloadSchemaType.KEYWORD),
                ("sectionId", PayloadSchemaType.KEYWORD),
                ("parentChunkId", PayloadSchemaType.KEYWORD),
                ("vin", PayloadSchemaType.KEYWORD),
                ("chassisId", PayloadSchemaType.KEYWORD),
            ]:
                try:
                    self.client.create_payload_index(
                        collection_name=self.collection,
                        field_name=field_name,
                        field_schema=schema,
                    )
                except Exception:
                    pass
            return True

        info = self.client.get_collection(self.collection)
        params = getattr(info.config, "params", None)
        sparse = getattr(params, "sparse_vectors", None) if params else None
        if sparse:
            logger.info("Collection '%s' uses hybrid vectors", self.collection)
            return True

        logger.warning(
            "Collection '%s' uses legacy single-vector schema. "
            "Hybrid search disabled until collection is recreated and documents re-ingested.",
            self.collection,
        )
        return False

    def upsert_chunks(self, document_id: str, chunks_with_metadata: list[dict]) -> None:
        points: list[PointStruct] = []
        for idx, chunk in enumerate(chunks_with_metadata):
            payload = {k: v for k, v in chunk.items() if k not in ("vector", "sparse_vector")}
            dense_vec = chunk.get("vector") or []

            if self.hybrid:
                sparse_vec = chunk.get("sparse_vector")
                if sparse_vec is None:
                    sparse_vec = SparseVector(indices=[0], values=[0.001])
                point_id = int(hashlib.md5(f"{document_id}-{idx}".encode()).hexdigest()[:12], 16)
                points.append(
                    PointStruct(
                        id=point_id,
                        vector={"dense": dense_vec, "bm25_sparse": sparse_vec},
                        payload=payload,
                    )
                )
            else:
                points.append(
                    PointStruct(
                        id=abs(hash(f"{document_id}-{idx}")) % (10**12),
                        vector=dense_vec,
                        payload=payload,
                    )
                )

        if points:
            self.client.upsert(collection_name=self.collection, points=points)
            logger.info("Upserted %d points for doc %s (hybrid=%s)", len(points), document_id, self.hybrid)

    def _build_filter(self, filters: dict | None) -> Filter:
        conditions = [FieldCondition(key="repository", match=MatchValue(value="certified"))]
        filters = filters or {}

        # When VIN or chassisId is present, they're sufficient to identify the document.
        # Skip make/model/year/country/warrantyType to avoid false-zero AND mismatches
        # (e.g. warrantyType "standard engine" is not stored on chunk payloads).
        has_vin = filters.get("vin") is not None
        has_chassis = filters.get("chassisId") is not None

        for key, value in filters.items():
            if key not in self.SEARCHABLE_KEYS or value is None:
                continue
            # When VIN/chassis present, skip redundant filters
            if (has_vin or has_chassis) and key in (
                "make",
                "model",
                "year",
                "country",
                "warrantyType",
            ):
                continue
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            if not isinstance(value, (str, int, bool)):
                continue
            conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
        return Filter(must=conditions)

    def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_vector: SparseVector,
        filters: dict | None = None,
        top_k: int = 10,
        prefetch_limit: int = 50,
    ) -> list:
        query_filter = self._build_filter(filters)
        results = self.client.query_points(
            collection_name=self.collection,
            prefetch=[
                Prefetch(
                    query=dense_vector,
                    using="dense",
                    limit=prefetch_limit,
                    filter=query_filter,
                ),
                Prefetch(
                    query=sparse_vector,
                    using="bm25_sparse",
                    limit=prefetch_limit,
                    filter=query_filter,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
        return results.points

    def legacy_search(self, query_vector: list[float], filters: dict | None, top_k: int) -> list:
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=self._build_filter(filters),
            limit=top_k,
            with_payload=True,
        )
        return response.points

    def update_repository(self, document_id: str, new_repo: str) -> int:
        document_filter = Filter(
            must=[FieldCondition(key="documentId", match=MatchValue(value=document_id))]
        )
        self.client.set_payload(
            collection_name=self.collection,
            payload={"repository": new_repo},
            points=document_filter,
            wait=True,
        )
        counted = self.client.count(
            collection_name=self.collection,
            count_filter=Filter(
                must=[
                    FieldCondition(key="documentId", match=MatchValue(value=document_id)),
                    FieldCondition(key="repository", match=MatchValue(value=new_repo)),
                ]
            ),
            exact=True,
        )
        return counted.count
