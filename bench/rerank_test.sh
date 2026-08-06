#!/bin/bash
cd "$(dirname "$0")/.."
S=$1
KEY=$(kubectl get deploy rag-api -n rag -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_KEY")].value}')
LLM_API_KEY="$KEY" uv run --with httpx python -u $S/rerank_answers.py $S "$(pwd)"
cd ../EnterpriseRAG-Bench
LLM_PROVIDER=openai LLM_API_KEY="$KEY" OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
LLM_MODEL_NAME=openai/gpt-5.6-luna CHEAP_LLM_MODEL_NAME=openai/gpt-5.6-luna \
uv run --python 3.12 --with-requirements requirements.txt python -u \
  -m src.scripts.answer_evaluation.metrics_based_eval \
  --answers-file ../rag-api/bench/answers-ladder-rerank.jsonl \
  --results-file answer_evaluation/results-ladder-rerank.json --parallelism 12 --resume
cp answer_evaluation/results-ladder-rerank.json ../rag-api/results/
echo "RERANK TEST DONE"
