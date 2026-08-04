from pydantic import BaseModel, Field


class ChunkIn(BaseModel):
    index: int
    text: str
    n_tokens: int
    heading_path: str = ""
    page: int | None = None
    embedding: list[float]


class PersistRequest(BaseModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str = ""
    mime_type: str
    byte_size: int = 0
    chunks: list[ChunkIn]


class PersistResponse(BaseModel):
    document_id: str
    created: bool
    n_chunks: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int | None = None
    mode: str = "hybrid"  # hybrid | vector | lexical
    lexical_stopword_strip: bool = False
    lexical_backend: str = "tsquery"  # tsquery | bm25 (needs pg_textsearch)
    vector_weight: float = 1.0  # scales the vector arm in RRF fusion


class TenantRequest(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    name: str = ""


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int | None = None  # chunks handed to the LLM; default settings.chat_chunks
    stream: bool = True


class SourceOut(BaseModel):
    n: int
    document_id: str
    heading_path: str
    content: str
    score: float


class ChatResponse(BaseModel):
    """Non-streaming shape; the SSE stream sends sources, deltas, done."""

    answer: str
    sources: list[SourceOut]
    timings_ms: dict[str, float]


class HitOut(BaseModel):
    chunk_id: int
    document_id: str
    ordinal: int
    heading_path: str
    page: int | None
    score: float
    vector_rank: int | None
    lexical_rank: int | None
    content: str


class SearchResponse(BaseModel):
    query: str
    mode: str
    timings_ms: dict[str, float]
    hits: list[HitOut]
