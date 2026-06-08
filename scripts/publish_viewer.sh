#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
DATE_TAG="${DATE_TAG:-$(date +%F)}"
PUSH_MAX_ATTEMPTS="${PUSH_MAX_ATTEMPTS:-5}"
PUSH_RETRY_DELAY="${PUSH_RETRY_DELAY:-10}"
PUBLISH_REMOTE="${PUBLISH_REMOTE:-origin}"
PUBLISH_BRANCH="${PUBLISH_BRANCH:-}"

cd "$PROJECT_DIR"

if [[ ! -d .git ]]; then
  echo "[ERROR] Not a git repository: $PROJECT_DIR" >&2
  exit 1
fi

BRANCH="${BRANCH:-$(git branch --show-current)}"
if [[ -z "$BRANCH" ]]; then
  echo "[ERROR] Could not determine target branch. Set BRANCH explicitly." >&2
  exit 1
fi
PUBLISH_BRANCH="${PUBLISH_BRANCH:-$BRANCH}"

if [[ ! -f viewer/papers_data.json ]]; then
  echo "[ERROR] Missing viewer/papers_data.json. Run python3 viewer/build_data.py first." >&2
  exit 1
fi

if [[ -f pending_llm_ids.txt ]] && [[ -s pending_llm_ids.txt ]]; then
  echo "[ERROR] pending_llm_ids.txt is not empty. Refusing to publish incomplete viewer data." >&2
  echo "[HINT] Finish the LLM补全流程, then run python3 viewer/build_data.py and python3 monitor.py --sync-pending-state before publishing." >&2
  exit 1
fi

changed_paths=()
for path in viewer/papers_data.json viewer/index.html viewer/app.js viewer/styles.css; do
  if [[ -n "$(git status --porcelain -- "$path")" ]]; then
    changed_paths+=("$path")
  fi
done

if [[ ${#changed_paths[@]} -eq 0 ]]; then
  echo "[INFO] No viewer changes to publish."
  exit 0
fi

git add "${changed_paths[@]}"

if git diff --cached --quiet; then
  echo "[INFO] No staged viewer changes to publish."
  exit 0
fi

git commit -m "chore(viewer): update site data for ${DATE_TAG}" -- "${changed_paths[@]}"

attempt=1
delay="$PUSH_RETRY_DELAY"
while true; do
  if git push "$PUBLISH_REMOTE" "$PUBLISH_BRANCH"; then
    break
  fi

  if (( attempt >= PUSH_MAX_ATTEMPTS )); then
    echo "[ERROR] git push failed after ${PUSH_MAX_ATTEMPTS} attempts." >&2
    echo "[HINT] Retry manually with: git push ${PUBLISH_REMOTE} ${PUBLISH_BRANCH}" >&2
    exit 1
  fi

  echo "[WARN] git push failed on attempt ${attempt}/${PUSH_MAX_ATTEMPTS}. Retrying in ${delay}s..." >&2
  sleep "$delay"
  attempt=$((attempt + 1))
  delay=$((delay * 2))
done

echo "[OK] Published viewer changes to ${PUBLISH_REMOTE}/${PUBLISH_BRANCH}"
