#!/usr/bin/env bash
set -euo pipefail

# Override this if needed. When left unchanged, the script uses its own location.
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
DEPLOY_MODE_FILE=".deploy_mode"
DEFAULT_DEPLOY_MODE="local"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "ERROR: PROJECT_DIR does not exist: $PROJECT_DIR" >&2
  exit 1
fi

if [[ ! -f "$PROJECT_DIR/monitor.py" ]]; then
  echo "ERROR: monitor.py not found under PROJECT_DIR: $PROJECT_DIR" >&2
  exit 1
fi

DEPLOY_MODE="${DEPLOY_MODE:-}"
if [[ -z "$DEPLOY_MODE" && -f "$PROJECT_DIR/$DEPLOY_MODE_FILE" ]]; then
  DEPLOY_MODE="$(tr -d '[:space:]' < "$PROJECT_DIR/$DEPLOY_MODE_FILE")"
fi
DEPLOY_MODE="${DEPLOY_MODE:-$DEFAULT_DEPLOY_MODE}"

if [[ "$DEPLOY_MODE" != "local" && "$DEPLOY_MODE" != "pages" ]]; then
  echo "ERROR: DEPLOY_MODE must be 'local' or 'pages', got: $DEPLOY_MODE" >&2
  exit 1
fi

export PROJECT_DIR
export DEPLOY_MODE

python3 - <<'PY'
import os
import re
from pathlib import Path

project_dir = Path(os.environ["PROJECT_DIR"]).resolve()
project_dir_str = str(project_dir)
deploy_mode = os.environ["DEPLOY_MODE"]


root = project_dir

# cronjob prompt: generate from template, do not overwrite template
template_name = "cronjob_prompt.txt" if deploy_mode == "local" else "cronjob_prompt.pages.txt"
cron_template = root / template_name
cron_generated = root / "cronjob_prompt.generated.txt"
cron_text = cron_template.read_text(encoding="utf-8")
cron_text = re.sub(
    r"^【重要】.*(?:\r?\n)?",
    "",
    cron_text,
    count=1,
    flags=re.MULTILINE,
)
cron_text = cron_text.replace("/path/to/hermes-arxiv-agent", project_dir_str)
cron_generated.write_text(cron_text, encoding="utf-8")
(root / ".deploy_mode").write_text(deploy_mode + "\n", encoding="utf-8")

print(f"Patched repository for PROJECT_DIR={project_dir_str}")
print("Updated files:")
print(f"- .deploy_mode ({deploy_mode})")
print(f"- {template_name}")
print("- cronjob_prompt.generated.txt")
print("")
print("Next step inside Hermes chat:")
print("1. Read the full current contents of cronjob_prompt.generated.txt")
print("2. Send a Hermes slash command: /cron add <prompt>")
print("3. Do not try to run /cron add in bash or a system shell")
PY
