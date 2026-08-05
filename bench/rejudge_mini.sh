#!/bin/bash
# wait for the main ladder to finish, then re-judge the repaired mini rung
while pgrep -f run_ladder.sh >/dev/null; do sleep 60; done
cd "$(dirname "$0")/.."
KEY=$(kubectl get deploy rag-api -n rag -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_KEY")].value}')
cd ../EnterpriseRAG-Bench
LLM_PROVIDER=openai LLM_API_KEY="$KEY" OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
LLM_MODEL_NAME=openai/gpt-5.4 CHEAP_LLM_MODEL_NAME=openai/gpt-5-mini \
uv run --python 3.12 --with-requirements requirements.txt python -u \
  -m src.scripts.answer_evaluation.metrics_based_eval \
  --answers-file ../rag-api/bench/answers-ladder-mini.jsonl \
  --results-file answer_evaluation/results-ladder-mini.json --parallelism 4 --resume
cp answer_evaluation/results-ladder-mini.json ../rag-api/results/erb-ladder-mini.json
echo "MINI REJUDGED"
