---
name: hermes-arxiv-agent-update-cron
description: Use this skill inside a Hermes conversation when a user already has a working local checkout of hermes-arxiv-agent and only wants to refresh the cron prompt and update or recreate the existing daily cron job without recloning the repo or reinstalling dependencies, while preserving either local mode or GitHub Pages mode.
---

# Hermes Arxiv Agent Update Cron

This skill is only for updating the existing cron configuration of a local `hermes-arxiv-agent` checkout.

Do not use this skill for first-time installation, dependency setup, or repository cloning.

Use it when the user wants any of the following:

- refresh the cron prompt after pulling new code
- update the current daily arXiv cron job to match the latest repository logic
- recreate the cron job from the current local repository without reinstalling anything
- ensure the cron prompt includes the latest GitHub Pages publishing step
- switch or preserve the deployment mode of the existing cron job

## Goal

Leave the user with:

1. the existing local repository untouched and reused in place
2. a freshly generated `cronjob_prompt.generated.txt` pointing to the real local path
3. a Hermes cron job whose prompt matches that generated file
4. delivery set to `feishu` rather than `local`

If the repository is in GitHub Pages mode, also leave the user with:

5. the repository `origin` or chosen publish remote pointing to the user's own writable fork
6. a remote configuration suitable for non-interactive Git pushes, preferably SSH

## Required Workflow

Follow this order unless the user explicitly asks for a subset.

### 1. Reuse the existing local repository

Do not clone the repository again.
Do not ask the user to rename directories.

Locate the existing local checkout of `hermes-arxiv-agent` and capture its absolute path as `PROJECT_DIR`.

If the user already provided the path, use that exact path.

### 2. Regenerate the cron prompt

Determine the intended deployment mode before regenerating:

- if the user explicitly says `更新本地模式定时任务`, use `local`
- if the user explicitly says `更新 GitHub Pages 模式定时任务`, use `pages`
- otherwise, if `.deploy_mode` exists, use that mode
- otherwise default to `local`

Mode priority is:

1. explicit user update phrase
2. `.deploy_mode`
3. default `local`

Do not ask the user to choose freely if the mode is already clear from the user's phrase or `.deploy_mode`.

Run inside `PROJECT_DIR`:

```bash
bash prepare_deploy.sh
```

This must regenerate `cronjob_prompt.generated.txt` from the tracked `cronjob_prompt.txt` template.

Do not hand-edit the generated prompt.

If the intended mode is GitHub Pages, run:

```bash
DEPLOY_MODE=pages bash prepare_deploy.sh
```

If the intended mode is GitHub Pages, ensure the publish remote points to the user's own writable fork, not the upstream repository.

### 3. Validate the generated prompt

Confirm that `cronjob_prompt.generated.txt`:

- contains the real absolute `PROJECT_DIR`
- does not contain placeholder paths such as `/path/to/hermes-arxiv-agent`
- in local mode, does not include the static-site publishing step
- in GitHub Pages mode, includes the static-site publishing step:

```bash
bash scripts/publish_viewer.sh
```

If the generated prompt does not include that publishing step, stop and tell the user the local repository is not on the expected version.

### 4. Update the Hermes cron job

Use the full current contents of `cronjob_prompt.generated.txt` as the exact cron prompt payload.

Preferred behavior:

- if Hermes supports editing the existing cron job, update it in place
- otherwise, delete the old cron job and recreate a single replacement job with the new prompt

Do not create duplicate active cron jobs for the same workflow.

This is a Hermes chat task. Treat `/cron add`, `/cron list`, and any edit/delete operation as Hermes commands, not shell commands.

### 5. Verify the final state

Confirm all of the following:

- there is exactly one active daily cron job for this repository workflow
- the active job uses the latest generated prompt
- delivery is set to `feishu`
- local mode stays local-only
- GitHub Pages mode contains the publish step and points to the user's own writable fork

## Behavior Rules

- Do not reclone the repository.
- Do not reinstall Python dependencies unless the user explicitly asks.
- Do not rewrite the cron prompt from memory.
- Prefer `prepare_deploy.sh` over manual prompt edits.
- Keep the local checkout path exactly as found.
- If the cron system cannot edit jobs in place, replace the old one cleanly rather than leaving duplicates.
- Treat `cronjob_prompt.txt` as the template source of truth and `cronjob_prompt.generated.txt` as the deployable cron payload.
- Respect the current deployment mode unless the user explicitly asks to switch modes.
- In GitHub Pages mode, prefer a fork remote that the user owns; do not direct scheduled publishing to the upstream public repository by default.

## Suggested User-Facing Outcome

At the end, the user should be able to continue using the existing local repository and existing data, while the daily cron job now also publishes updated `viewer/papers_data.json` to GitHub and triggers GitHub Pages deployment.
