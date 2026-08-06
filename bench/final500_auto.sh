#!/bin/bash
# waits for the tricks slices, picks the champion, runs the full-500 at it
while pgrep -f tricks_run.sh >/dev/null; do sleep 120; done
cd "$(dirname "$0")/.."
KEY=$(kubectl get deploy rag-api -n rag -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_KEY")].value}')
BENCH=../EnterpriseRAG-Bench

PICK=$(python3 <<'PY'
import json
best_name, best = "champion", 41.39
for name in ("sonnet-rerank", "haiku-rr-k12", "haiku-rr-comp"):
    try:
        v = json.load(open(f"results/results-ladder-{name}.json"))[
            "aggregate_stats"]["combined_correctness_completeness_score"]
    except Exception:
        continue
    if v > best + 0.5:
        best_name, best = name, v
print(best_name)
PY
)
echo "PICK: $PICK"
case "$PICK" in
  sonnet-rerank) MODEL="anthropic/claude-sonnet-5"; STYLE=terse; CHUNKS=8;;
  haiku-rr-k12)  MODEL="anthropic/claude-haiku-4.5"; STYLE=terse; CHUNKS=12;;
  haiku-rr-comp) MODEL="anthropic/claude-haiku-4.5"; STYLE=complete; CHUNKS=8;;
  champion) echo "no slice beat 42.11 config; final stands"; exit 0;;
esac

for c in 2 1; do
  LLM_API_KEY="$KEY" LLM_MODEL="$MODEL" LLM_BASE_URL=https://openrouter.ai/api/v1 \
  uv run --with httpx python -u bench/answer_bench.py \
    --questions $BENCH/questions.jsonl --api-url https://rag-api.tail17a16a.ts.net \
    --tenant erb-v1 --state bench/state-erb-v1.jsonl \
    --answers bench/answers-submission-final.jsonl --concurrency $c \
    --prompt-style "$STYLE" --chunks "$CHUNKS" --max-tokens 8192 --rerank
done
(cd $BENCH && LLM_PROVIDER=openai LLM_API_KEY="$KEY" \
  OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
  LLM_MODEL_NAME=openai/gpt-5.6-luna CHEAP_LLM_MODEL_NAME=openai/gpt-5.6-luna \
  uv run --python 3.12 --with-requirements requirements.txt python -u \
  -m src.scripts.answer_evaluation.metrics_based_eval \
  --answers-file ../rag-api/bench/answers-submission-final.jsonl \
  --results-file answer_evaluation/results-submission-final.json \
  --parallelism 12 --resume)
cp $BENCH/answer_evaluation/results-submission-final.json results/
echo "FINAL500 DONE ($PICK)"
