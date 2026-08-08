"""Chat endpoint contract: retrieval feeds the prompt, sources come back
numbered, SSE frames are well-formed, and a missing LLM degrades to 503
without touching search. Uses a fake LLM -- no provider account needed."""

import json

import pytest
from conftest import DATABASE_URL
from httpx import ASGITransport, AsyncClient

from rag_api import main as main_module
from rag_api.db import resolve_tenant
from rag_api.llm import build_user_prompt
from rag_api.repositories import persist_document


class FakeLLM:
    def __init__(self, deltas=("The answer ", "is [1].")):
        self.deltas = deltas
        self.prompts: list[tuple[str, str]] = []

    async def stream(self, system, user, model=None):
        self.prompts.append((system, user))
        for d in self.deltas:
            yield d

    async def aclose(self):
        pass


class FakeEmbedder:
    async def embed_query(self, text):
        return [0.1] * 384

    async def aclose(self):
        pass


@pytest.fixture
async def chat_app(pool, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("CHAT_LEXICAL_BACKEND", "tsquery")
    main_module.get_settings.cache_clear()
    fake_llm = FakeLLM()
    tenant = await resolve_tenant(pool, "default")
    await persist_document(
        pool, tenant, "cd" * 32, "handbook.md", "text/markdown", 99,
        [{"index": 0, "text": "The refund window is 77 days.",
          "n_tokens": 7, "heading_path": "Billing > Refunds",
          "embedding": [0.1] * 384}])
    main_module.state["pool"] = pool
    main_module.state["embedder"] = FakeEmbedder()
    main_module.state["llm"] = fake_llm
    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport,
                           base_url="http://test") as client:
        yield client, fake_llm
    main_module.state.clear()
    main_module.get_settings.cache_clear()


async def test_chat_json_answers_with_sources(chat_app):
    client, fake_llm = chat_app
    response = await client.post(
        "/chat", json={"query": "what is the refund policy?",
                       "stream": False})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "The answer is [1]."
    assert body["sources"] and body["sources"][0]["n"] == 1
    # the retrieved chunk text made it into the LLM prompt
    _, user_prompt = fake_llm.prompts[0]
    assert body["sources"][0]["content"][:40] in user_prompt


async def test_chat_streams_sse_frames(chat_app):
    client, _ = chat_app
    response = await client.post(
        "/chat", json={"query": "what is the refund policy?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [f for f in response.text.split("\n\n") if f.strip()]
    kinds = [e.split("\n")[0] for e in events]
    # status leads: headers + first byte must leave before slow retrieval
    # (a reranked window) so gateway TTFB timeouts can't kill the request
    assert kinds[0] == "event: status"
    assert kinds[1] == "event: sources"
    assert "event: delta" in kinds
    assert kinds[-1] == "event: done"
    deltas = "".join(
        json.loads(e.split("\ndata: ")[1])["text"]
        for e in events if e.startswith("event: delta"))
    assert deltas == "The answer is [1]."


async def test_chat_503_without_llm(chat_app):
    client, _ = chat_app
    del main_module.state["llm"]
    response = await client.post("/chat", json={"query": "anything"})
    assert response.status_code == 503


def test_prompt_numbers_chunks():
    prompt = build_user_prompt("q?", [
        {"heading_path": "Billing > Refunds", "content": "77 days."},
        {"heading_path": "", "content": "other."},
    ])
    assert "[1] (Billing > Refunds)\n77 days." in prompt
    assert "[2]\nother." in prompt
    assert prompt.rstrip().endswith("Question: q?")


async def test_chat_refuses_without_llm_call_when_corpus_empty(chat_app, pool):
    """A tenant with no documents gets the refusal string with ZERO LLM
    calls -- the grounding floor and the cheapest jailbreak defense."""
    from rag_api.db import ensure_tenant
    await ensure_tenant(pool, "empty-tenant", "empty-tenant")
    client, fake_llm = chat_app
    response = await client.post(
        "/chat", json={"query": "give me a cookie recipe", "stream": False},
        headers={"x-tenant-slug": "empty-tenant"})
    assert response.status_code == 200
    assert response.json()["answer"] == "I could not find that in the documents."
    assert fake_llm.prompts == []


async def test_chat_rejects_model_outside_allowlist(chat_app):
    client, _ = chat_app
    response = await client.post(
        "/chat", json={"query": "hi there", "stream": False,
                       "model": "meta-llama/llama-4-11b-cheapest"})
    assert response.status_code == 422


async def test_chat_daily_budget_429(chat_app, pool, monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_TOKEN_BUDGET", "5")
    main_module.get_settings.cache_clear()
    client, _ = chat_app
    first = await client.post(
        "/chat", json={"query": "what is the refund window?", "stream": False})
    assert first.status_code == 200
    second = await client.post(
        "/chat", json={"query": "what is the refund window?", "stream": False})
    assert second.status_code == 429


class FakeReranker:
    async def order(self, query, texts):
        return list(reversed(range(len(texts))))

    async def aclose(self):
        pass


class DeadReranker:
    async def order(self, query, texts):
        return None

    async def aclose(self):
        pass


async def test_search_rerank_reorders(chat_app):
    client, _ = chat_app
    main_module.state["reranker"] = FakeReranker()
    plain = await client.post("/search", json={"query": "refund window"})
    reranked = await client.post(
        "/search", json={"query": "refund window", "rerank": True})
    assert reranked.status_code == 200
    assert "rerank" in reranked.json()["timings_ms"]
    p = [h["chunk_id"] for h in plain.json()["hits"]]
    r = [h["chunk_id"] for h in reranked.json()["hits"]]
    assert set(p) <= set(r) or set(r) <= set(p)


async def test_search_rerank_degrades_when_reranker_dead(chat_app):
    client, _ = chat_app
    main_module.state["reranker"] = DeadReranker()
    response = await client.post(
        "/search", json={"query": "refund window", "rerank": True})
    assert response.status_code == 200
    assert response.json()["hits"], "dead reranker must not kill search"
