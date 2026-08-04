from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # CNPG app-user DSN; inject via the edka ENVS tab from the rag-pg secret.
    database_url: str = "postgresql://app:app@localhost:5432/app"

    # In-cluster Service DNS of rag-embedder; queries embed with
    # input_type="query" -- the other half of the e5 prefix contract.
    embedder_url: str = "http://rag-embedder.rag.svc.cluster.local"
    embed_timeout_s: float = 30.0

    search_k: int = 8
    search_candidates: int = 50

    # Until auth (part 4), the tenant comes from the x-tenant-slug header,
    # defaulting to the seeded tenant. The RLS machinery is real either way.
    default_tenant_slug: str = "default"

    # Answer synthesis. Provider "openai" covers every OpenAI-compatible
    # server via llm_base_url; empty api key disables /chat with a 503
    # rather than failing startup -- search works without an LLM.
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model: str = "gpt-5-mini"
    llm_base_url: str = ""
    llm_max_tokens: int = 1024
    # Chat retrieval defaults = the measured ERB winners; env-overridable
    # for clusters without pg_textsearch.
    chat_lexical_backend: str = "bm25"
    chat_vector_weight: float = 0.3
    chat_chunks: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
