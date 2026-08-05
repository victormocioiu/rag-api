#!/bin/bash
# 1) luna x completeness-prompt rung  2) pick overall winner
# 3) full-500 answers at winner       4) judge ONCE (resume-safe)
cd "$(dirname "$0")/.."
KEY=$(kubectl get deploy rag-api -n rag -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_API_KEY")].value}')
API=https://rag-api.tail17a16a.ts.net
BENCH=../EnterpriseRAG-Bench

gen () { # answers-file model prompt-style subset-args...
  local out="$1" model="$2" style="$3"; shift 3
  for c in 8 2; do
    LLM_API_KEY="$KEY" LLM_MODEL="$model" LLM_BASE_URL=https://openrouter.ai/api/v1 \
    uv run --with httpx python -u bench/answer_bench.py \
      --questions $BENCH/questions.jsonl --api-url $API --tenant erb-v1 \
      --state bench/state-erb-v1.jsonl --answers "$out" --concurrency $c \
      --prompt-style "$style" --chunks 8 --max-tokens 8192 "$@"
  done
}
judge () { # answers-file results-name
  (cd $BENCH && LLM_PROVIDER=openai LLM_API_KEY="$KEY" \
    OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
    LLM_MODEL_NAME=openai/gpt-5.6-luna CHEAP_LLM_MODEL_NAME=openai/gpt-5.6-luna \
    uv run --python 3.12 --with-requirements requirements.txt python -u \
    -m src.scripts.answer_evaluation.metrics_based_eval \
    --answers-file "../rag-api/$1" \
    --results-file "answer_evaluation/$2.json" --parallelism 12 --resume)
  cp $BENCH/answer_evaluation/$2.json results/$2.json
}

gen bench/answers-ladder-luna-complete.jsonl "openai/gpt-5.6-luna" complete \
    --subset bench/ladder-subset.txt
judge bench/answers-ladder-luna-complete.jsonl results-ladder-luna-complete

judge bench/answers-ladder-haiku.jsonl results-ladder-haiku-lunajudge

WINNER=$(python3 -c "
import json
combo = json.load(open('results/results-ladder-luna-complete.json'))['aggregate_stats']['combined_correctness_completeness_score']
haiku = json.load(open('results/results-ladder-haiku-lunajudge.json'))['aggregate_stats']['combined_correctness_completeness_score']
print('luna-complete' if combo > haiku else 'haiku')")
echo "WINNER: $WINNER"
if [ "$WINNER" = "luna-complete" ]; then
  MODEL="openai/gpt-5.6-luna"; STYLE="complete"
else
  MODEL="anthropic/claude-haiku-4.5"; STYLE="terse"
fi

gen bench/answers-submission.jsonl "$MODEL" "$STYLE"
judge bench/answers-submission.jsonl results-submission-official
echo "FINAL RUN DONE"
