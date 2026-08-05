#!/bin/bash
cd "$(dirname "$0")/.."
KEY=$(kubectl get deploy rag-api -n rag -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_KEY")].value}')
API=https://rag-api.tail17a16a.ts.net
BENCH=../EnterpriseRAG-Bench

gen () { # name model chunks
  for c in 3 1; do
    LLM_API_KEY="$KEY" LLM_MODEL="$2" LLM_BASE_URL=https://openrouter.ai/api/v1 \
    uv run --with httpx python -u bench/answer_bench.py \
      --questions $BENCH/questions.jsonl --api-url $API --tenant erb-v1 \
      --state bench/state-erb-v1.jsonl --subset bench/ladder-subset.txt \
      --answers "bench/answers-ladder-$1.jsonl" --concurrency $c \
      --chunks "$3" --max-tokens 8192
  done
}
judge () { # name
  (cd $BENCH && LLM_PROVIDER=openai LLM_API_KEY="$KEY" \
    OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
    LLM_MODEL_NAME=openai/gpt-5.4 CHEAP_LLM_MODEL_NAME=openai/gpt-5-mini \
    uv run --python 3.12 --with-requirements requirements.txt python -u \
    -m src.scripts.answer_evaluation.metrics_based_eval \
    --answers-file ../rag-api/bench/answers-ladder-$1.jsonl \
    --results-file answer_evaluation/results-ladder-$1.json --parallelism 4 --resume)
  cp $BENCH/answer_evaluation/results-ladder-$1.json results/erb-ladder-$1.json
}

gen haiku-k16 "anthropic/claude-haiku-4.5" 16
gen luna      "openai/gpt-5.6-luna"        8
while pgrep -f rejudge_mini.sh >/dev/null; do sleep 60; done
judge haiku-k16
judge luna
echo "LADDER2 DONE"
