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
