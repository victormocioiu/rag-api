#!/bin/bash
# Answering-model ladder: generate 100-q answers per rung, judge each.
set -x
cd "$(dirname "$0")/.."
KEY=$(kubectl get deploy rag-api -n rag -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_KEY")].value}')
API=https://rag-api.tail17a16a.ts.net
BENCH=../EnterpriseRAG-Bench

gen () { # name model style chunks
  LLM_API_KEY="$KEY" LLM_MODEL="$2" LLM_BASE_URL=https://openrouter.ai/api/v1 \
  uv run --with httpx python -u bench/answer_bench.py \
    --questions $BENCH/questions.jsonl --api-url $API --tenant erb-v1 \
    --state bench/state-erb-v1.jsonl --subset bench/ladder-subset.txt \
    --answers "bench/answers-ladder-$1.jsonl" --concurrency 3 \
    --prompt-style "$3" --chunks "$4"
  # one retry sweep for provider flakes
  LLM_API_KEY="$KEY" LLM_MODEL="$2" LLM_BASE_URL=https://openrouter.ai/api/v1 \
  uv run --with httpx python -u bench/answer_bench.py \
    --questions $BENCH/questions.jsonl --api-url $API --tenant erb-v1 \
    --state bench/state-erb-v1.jsonl --subset bench/ladder-subset.txt \
    --answers "bench/answers-ladder-$1.jsonl" --concurrency 1 \
    --prompt-style "$3" --chunks "$4"
}

judge () { # name
  (cd $BENCH && LLM_PROVIDER=openai LLM_API_KEY="$KEY" \
    OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
    LLM_MODEL_NAME=openai/gpt-5.4 CHEAP_LLM_MODEL_NAME=openai/gpt-5-mini \
    uv run --python 3.12 --with-requirements requirements.txt python -u \
    -m src.scripts.answer_evaluation.metrics_based_eval \
    --answers-file ../rag-api/bench/answers-ladder-$1.jsonl \
    --results-file answer_evaluation/results-ladder-$1.json \
    --parallelism 4)
  cp $BENCH/answer_evaluation/results-ladder-$1.json results/erb-ladder-$1.json
}

gen mini    "openai/gpt-5-mini"                        terse    8
gen haiku   "anthropic/claude-haiku-4.5"               terse    8
gen complete "mistralai/mistral-small-3.2-24b-instruct" complete 8
gen k16     "mistralai/mistral-small-3.2-24b-instruct" terse    16

judge mini
judge haiku
judge complete
judge k16
echo "LADDER DONE"
