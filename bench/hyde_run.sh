#!/bin/bash
cd "$(dirname "$0")/.."
KEY=$(kubectl get deploy rag-api -n rag -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_KEY")].value}')
export SCRATCH=/private/tmp/claude-501/-Users-victor-edka-rag-rag-embedder/c6ad61ea-32ee-4fd1-b97d-e12588f0c3a/scratchpad
export SCRATCH=/private/tmp/claude-501/-Users-victor-edka-rag-rag-embedder/c6ad61ea-32ee-4fd1-b97d-e12588f0c23a/scratchpad
LLM_API_KEY="$KEY" uv run --with httpx python -u bench/hyde_proto.py
LLM_API_KEY="$KEY" uv run --with httpx python -u bench/hyde_proto.py
BENCH=../EnterpriseRAG-Bench
(cd $BENCH && LLM_PROVIDER=openai LLM_API_KEY="$KEY" \
  OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
  LLM_MODEL_NAME=openai/gpt-5.6-luna CHEAP_LLM_MODEL_NAME=openai/gpt-5.6-luna \
  uv run --python 3.12 --with-requirements requirements.txt python -u \
  -m src.scripts.answer_evaluation.metrics_based_eval \
  --answers-file ../rag-api/bench/answers-ladder-hyde.jsonl \
  --results-file answer_evaluation/results-ladder-hyde.json --parallelism 12 --resume)
cp $BENCH/answer_evaluation/results-ladder-hyde.json results/
echo "HYDE DONE"
