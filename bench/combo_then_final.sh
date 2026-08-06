#!/bin/bash
cd "$(dirname "$0")/.."
KEY=$(kubectl get deploy rag-api -n rag -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_KEY")].value}')
BENCH=../EnterpriseRAG-Bench

gen () { for c in 2 1; do
  LLM_API_KEY="$KEY" LLM_MODEL="$2" LLM_BASE_URL=https://openrouter.ai/api/v1 \
  uv run --with httpx python -u bench/answer_bench.py \
    --questions $BENCH/questions.jsonl --api-url https://rag-api.tail17a16a.ts.net \
    --tenant erb-v1 --state bench/state-erb-v1.jsonl $4 \
    --answers "bench/$1" --concurrency $c --chunks "$3" --max-tokens 8192 --rerank
done; }
judge () {
  (cd $BENCH && LLM_PROVIDER=openai LLM_API_KEY="$KEY" \
    OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
    LLM_MODEL_NAME=openai/gpt-5.6-luna CHEAP_LLM_MODEL_NAME=openai/gpt-5.6-luna \
    uv run --python 3.12 --with-requirements requirements.txt python -u \
    -m src.scripts.answer_evaluation.metrics_based_eval \
    --answers-file "../rag-api/bench/$1" \
    --results-file "answer_evaluation/$2.json" --parallelism 12 --resume)
  cp $BENCH/answer_evaluation/$2.json results/
}

# combo slice: sonnet-5 x rerank x k12
gen answers-ladder-sonnet-k12.jsonl "anthropic/claude-sonnet-5" 12 "--subset bench/ladder-subset.txt"
judge answers-ladder-sonnet-k12.jsonl results-ladder-sonnet-k12

WINNER=$(python3 <<'PY'
import json
cands = {"sonnet-k8": 43.12, "haiku-k12": 42.66}
try:
    cands["sonnet-k12"] = json.load(open("results/results-ladder-sonnet-k12.json"))[
        "aggregate_stats"]["combined_correctness_completeness_score"]
except Exception:
    pass
print(max(cands, key=lambda k: cands[k]))
PY
)
echo "PICK: $WINNER"
case "$WINNER" in
  sonnet-k12) MODEL="anthropic/claude-sonnet-5"; CHUNKS=12;;
  sonnet-k8)  MODEL="anthropic/claude-sonnet-5"; CHUNKS=8;;
  haiku-k12)  MODEL="anthropic/claude-haiku-4.5"; CHUNKS=12;;
esac
gen answers-submission-final.jsonl "$MODEL" "$CHUNKS" ""
judge answers-submission-final.jsonl results-submission-final
echo "FINAL500 DONE ($WINNER)"
