# AGENTS

## Project Purpose

`hermes-arxiv-agent` is a Hermes-based paper monitoring project for arXiv.

It is designed to:

- search arXiv daily with configurable topic queries and quotas
- download newly discovered PDFs
- use Hermes/LLM to extract author affiliations and generate `summary_cn`
- write results back to `papers_record.xlsx`
- send a daily Feishu report
- send a second, separate daily investment advice message after the paper report
- provide a paper viewer website, either locally or via GitHub Pages

The default research topics and quotas are configured in `search_topics.json`.

## Core Data Flow

Main runtime entry:

- [monitor.py](/home/wsg/hermes_path/hermes-arxiv-agent/monitor.py:1)

Persistent data:

- `papers_record.xlsx`: source of truth for paper metadata, affiliations, summaries, and crawl dates
- `papers/`: downloaded PDFs
- `new_papers.json`: intermediate file for Hermes/agent processing
- `pending_llm_ids.txt`: papers still missing `affiliations` or `summary_cn`
- `viewer/papers_data.json`: static website data built from the Excel file
- `investment_advice/investment_state.json`: local investment suggestion state, ignored by git
- `logs/investment_dca.log`: investment suggestion calculation log

Daily flow:

1. `python3 monitor.py`
2. arXiv search returns the newest matching papers
3. batched low-cost DeepSeek calls screen candidate titles and abstracts, reject papers where recommendation is only an incidental evaluation domain, classify topics, and detect abstract-stated open-source code
4. quota selection keeps at least one paper per available topic, then fills remaining slots in topic priority order up to 10 papers
5. only selected PDFs are downloaded and appended/upserted into Excel
6. Hermes/agent reads `new_papers.json`
7. Hermes/agent extracts `affiliations` from PDFs and writes `summary_cn`
8. Hermes/agent updates `papers_record.xlsx`
9. `python3 viewer/build_data.py` rebuilds `viewer/papers_data.json`
10. `python3 monitor.py --sync-pending-state` refreshes `pending_llm_ids.txt`
11. optional: `bash scripts/publish_viewer.sh` pushes viewer changes and triggers GitHub Pages
12. `python3 -m investment_advice.dca` computes the daily investment advice
13. the cron output sends the arXiv paper report first, then a separate investment advice message

Production scheduling on this server uses `daily_run.py` through a Hermes
`no-agent` cron script. This avoids loading the full Hermes agent/tool prompt
before the pipeline starts and prevents long initial streaming requests from
failing with `Broken pipe`.

In no-agent cron mode, `daily_run.py` sends the arXiv report and investment
advice as two separate Feishu messages through `hermes send`, then prints
`[SILENT]` so the cron stdout delivery does not merge them back into one
message.

Important:

- `topic_name`, `code_open_source`, and `code_url` are persisted in Excel and exported to the viewer
- `code_open_source` is inferred only from the arXiv abstract; absence of evidence is stored as `摘要未说明`
- affiliation extraction is now done by Hermes/agent during the cron workflow
- old standalone extractor scripts were removed from the main repo flow
- `crawled_date` means the latest processing/write-back date, not a permanent first-seen date
- investment advice is a suggestion only; it never executes trades
- investment advice output must contain only `推荐投资金额` and `推荐原因说明`
- investment advice output must not reveal the investment object, market object, data source, URLs, platform, code, index, fund, or ETF names
- investment advice must not be written to `viewer/papers_data.json` or published on GitHub Pages; Pages only shows paper viewer data
- `DAILY_RUN_DIRECT_SEND=1` enables two separate Feishu sends from `daily_run.py`; `DAILY_RUN_SEND_TARGET` defaults to `feishu`

## Deployment Modes

This repo supports two deployment modes.

### 1. Local Mode

Use this when the user wants:

- daily Feishu delivery
- local Excel/PDF storage
- local web viewer via `python3 viewer/run_viewer.py`

Characteristics:

- uses the upstream repository directly
- does not require a fork
- does not push to GitHub Pages
- generated cron prompt comes from `cronjob_prompt.txt`

### 2. GitHub Pages Mode

This is an enhanced version of local mode.

It includes everything in local mode, plus:

- automatic static-site publishing to the user's own GitHub fork
- GitHub Actions deployment for Pages

Characteristics:

- requires the user to fork the repository first
- `origin` should point to the user's own fork
- SSH is preferred for Git pushes
- generated cron prompt comes from `cronjob_prompt.pages.txt`
- cron includes `bash scripts/publish_viewer.sh`

## Deployment Files

Key deployment and ops files:

- [README.md](/home/wsg/hermes_path/hermes-arxiv-agent/README.md:1): user-facing install and usage guide
- [AGENT_SKILL.md](/home/wsg/hermes_path/hermes-arxiv-agent/AGENT_SKILL.md:1): Hermes deployment skill
- [UPDATE_CRON_SKILL.md](/home/wsg/hermes_path/hermes-arxiv-agent/UPDATE_CRON_SKILL.md:1): Hermes skill for refreshing cron only
- [prepare_deploy.sh](/home/wsg/hermes_path/hermes-arxiv-agent/prepare_deploy.sh:1): generates `cronjob_prompt.generated.txt`
- [cronjob_prompt.txt](/home/wsg/hermes_path/hermes-arxiv-agent/cronjob_prompt.txt:1): local mode cron template
- [cronjob_prompt.pages.txt](/home/wsg/hermes_path/hermes-arxiv-agent/cronjob_prompt.pages.txt:1): GitHub Pages mode cron template

Mode persistence:

- `.deploy_mode` stores `local` or `pages`
- `prepare_deploy.sh` reads it unless `DEPLOY_MODE` is explicitly provided

## Viewer

Viewer files:

- [viewer/index.html](/home/wsg/hermes_path/hermes-arxiv-agent/viewer/index.html:1)
- [viewer/app.js](/home/wsg/hermes_path/hermes-arxiv-agent/viewer/app.js:1)
- [viewer/styles.css](/home/wsg/hermes_path/hermes-arxiv-agent/viewer/styles.css:1)
- [viewer/build_data.py](/home/wsg/hermes_path/hermes-arxiv-agent/viewer/build_data.py:1)

Viewer behavior:

- reads `viewer/papers_data.json`
- supports filtering by `crawled_date` or `published_date`
- favorites are stored in browser `localStorage`
- GitHub Pages mode does not use server-side favorites

## Publish Safety Rules

GitHub Pages publishing is intentionally guarded.

- `scripts/publish_viewer.sh` refuses to publish if `pending_llm_ids.txt` is non-empty
- it only stages site-related files
- it retries `git push` with backoff
- it pushes to the current configured remote; it should never be hardcoded to the upstream repo

If a user is in GitHub Pages mode, publishing must target their own fork, not `genggng/hermes-arxiv-agent` unless they explicitly own and use that repository.

## Common Commands

Local viewer:

```bash
cd viewer
python3 run_viewer.py
```

Rebuild viewer data:

```bash
python3 viewer/build_data.py
```

Refresh pending state:

```bash
python3 monitor.py --sync-pending-state
```

Regenerate deploy prompt:

```bash
bash prepare_deploy.sh
```

Regenerate deploy prompt for Pages mode:

```bash
DEPLOY_MODE=pages bash prepare_deploy.sh
```

Manual Pages publish:

```bash
bash scripts/publish_viewer.sh
```

Generate investment advice only:

```bash
python3 -m investment_advice.dca
```

## What To Check First In A New Session

When starting a new work session on this repo, check these first:

1. `git status --short`
2. current deployment mode from `.deploy_mode` if it exists
3. whether the task is about local mode or GitHub Pages mode
4. whether `pending_llm_ids.txt` is empty
5. whether the user wants code changes, cron updates, or only data publishing
6. whether the task touches the investment advice module and its local state

Useful questions to answer early:

- Is this a deployment problem, a data-processing problem, or a viewer/UI problem?
- Is the user working in local mode or GitHub Pages mode?
- If publishing is involved, does `origin` point to the user's own fork?
- If investment advice is involved, is the request about config, state, output wording, or the daily cron flow?

## Current Conventions

- prefer `rg` for search
- use `apply_patch` for file edits
- avoid touching unrelated untracked user files
- do not revert user changes unless explicitly asked
- for Pages-related changes, preserve the distinction between local mode and Pages mode

## Recent Changes And Known Pitfalls

Recent important changes:

- GitHub Pages support was added as an optional deployment mode on top of local mode
- viewer favorites were migrated from server-side file storage to browser `localStorage`
- mobile viewer layout was improved, including narrow-screen filter behavior and date input sizing
- a favicon was added for the viewer
- arXiv fetch size was increased from 20 to 50
- SSH is now the recommended Git remote mode for Pages publishing
- update-cron instructions were split into explicit local-mode and GitHub-Pages-mode phrases
- legacy standalone affiliation extractor scripts were removed from the repo flow
- `investment_advice/` was added for a second daily investment suggestion message after the arXiv report

Known historical pitfalls:

### 1. Incomplete viewer data was previously published too early

Old behavior:

- `monitor.py` used to export `viewer/papers_data.json` before Hermes finished writing `affiliations` and `summary_cn`
- this caused GitHub Pages to publish incomplete summaries or affiliations

Current fix:

- `monitor.py` no longer exports viewer data at that premature point
- `scripts/publish_viewer.sh` refuses to publish when `pending_llm_ids.txt` is non-empty

### 2. Git push could fail after local commit

Old behavior:

- `publish_viewer.sh` could commit successfully and then fail on `git push`
- there was no retry logic

Current fix:

- push now retries with backoff
- if push still fails, the local commit remains and can be pushed manually later

### 3. HTTPS remotes caused auth confusion for Pages publishing

Old behavior:

- users could add SSH keys to GitHub, but the repo remote was still `https://...`
- pushes failed because the repo was not actually using SSH auth

Current fix:

- Pages-mode docs and deployment logic now prefer SSH remotes
- publishing should target the current configured remote, ideally the user's fork over SSH

### 4. Upstream repo must not be the default publish target for open-source users

Old risk:

- automation could accidentally be interpreted as publishing to the upstream public repo

Current fix:

- local mode does not publish at all
- GitHub Pages mode requires the user's own fork
- docs and skills now distinguish the two modes explicitly

### 5. `crawled_date` is intentionally the latest processed date

This is not a bug.

- `published_date` is the arXiv-side date
- `crawled_date` is the latest date the record was processed and written back locally
- reprocessed papers may therefore show today's `crawled_date`

### 6. Affiliation extraction now depends on the Hermes/agent workflow

This is intentional.

- there is no standalone extractor in the main production path anymore
- if affiliation quality becomes a problem, the first place to inspect is the cron prompt and Hermes/LLM workflow, not a removed local script
