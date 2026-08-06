#!/bin/bash
cd "$(dirname "$0")/.."
KEY=$(kubectl get deploy rag-api -n rag -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_KEY")].value}')
BENCH=../EnterpriseRAG-Bench
for c in 2 1; do
  LLM_API_KEY="$KEY" LLM_MODEL="anthropic/claude-haiku-4.5" LLM_BASE_URL=https://openrouter.ai/api/v1 \
  uv run --with httpx python -u bench/answer_bench.py \
    --questions $BENCH/questions.jsonl --api-url https://rag-api.tail17a16a.ts.net \
    --tenant erb-v1 --state bench/state-erb-v1.jsonl \
    --answers bench/answers-submission-rerank.jsonl --concurrency $c \
    --chunks 8 --max-tokens 8192 --rerank
done
(cd $BENCH && LLM_PROVIDER=openai LLM_API_KEY="$KEY" \
  OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
  LLM_MODEL_NAME=openai/gpt-5.6-luna CHEAP_LLM_MODEL_NAME=openai/gpt-5.6-luna \
  uv run --python 3.12 --with-requirements requirements.txt python -u \
  -m src.scripts.answer_evaluation.metrics_based_eval \
  --answers-file ../rag-api/bench/answers-submission-rerank.jsonl \
  --results-file answer_evaluation/results-submission-rerank.json \
  --parallelism 12 --resume)
cp $BENCH/answer_evaluation/results-submission-rerank.json results/
echo "RERANK SUBMISSION DONE"
