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


@lru_cache
def get_settings() -> Settings:
    return Settings()
