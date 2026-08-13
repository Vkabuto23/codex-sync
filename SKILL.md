---
name: codex-sync
description: Sync, restore, or link a Codex chat's working context across computers through a private GitHub state repository. Use for requests such as sync this chat, save context for another computer, restore a saved chat, continue work from another device, link this thread, chat-sync, chat-restore, chat-link, or configure milestone/task-completion sync. Preserve working state rather than internal Codex sessions; never use for project source-code synchronization or credential storage.
---

# Codex Sync

Transfer the useful working state of a logical chat, not Codex's internal session. Keep the project source in its normal repository. Use the bundled CLI for deterministic GitHub, Git, authorization, link, marker, and filesystem operations; keep semantic and summarization decisions in the model.

## Resolve the operation

- Treat `$codex-sync sync`, `&chat-sync`, and natural-language save/sync requests as `sync`.
- Treat `$codex-sync restore [chat]`, `&chat-restore [chat]`, and natural-language restore/continue requests as `restore`.
- Treat `$codex-sync link [chat]`, `&chat-link [chat]`, and natural-language link/bind requests as `link`.
- Use `$codex-sync` as the documented explicit invocation. Do not claim that `&chat-*` are separately registered skills; current Codex uses `$skill-name` for explicit skill invocation.

## Preserve the security model

Identify a saved chat by its human-readable `project name + chat name`.

- A canonical source has the same normalized project and chat names as the saved chat. Only a canonical source may write with `sync`.
- A same-name linked thread receives role `source` and may sync and restore.
- A linked thread whose project or chat differs receives role `consumer` and may restore only. Never allow it to sync, even if it has a valid thread ID.
- When `linked-chats.md` is absent, use open mode: canonical sources may sync and restore is allowed without a thread ID.
- When `linked-chats.md` exists, use strict mode: require the current thread ID for sync and restore. Require role `source` for sync; allow `source` or `consumer` for restore.
- Allow `link` to add the current thread explicitly. Derive its role from the names; never accept a caller-supplied role.
- Create `<current-project-root>/.codex-sync/linked-with.md` for every consumer link. Use this local marker to resolve later restores. Never create it for a canonical source.

Do not weaken these rules based on semantic similarity. Semantic matching selects a candidate; authorization uses normalized canonical names and linked roles.

## Locate the CLI

Resolve `scripts/codex_sync.py` relative to this `SKILL.md`. Run it with Python 3.10+.

Start every operation with:

```text
python <skill>/scripts/codex_sync.py doctor
python <skill>/scripts/codex_sync.py bootstrap
```

The CLI requires `git` and an authenticated GitHub CLI session. It obtains the GitHub login from `gh api user --jq .login`, creates `{login}-codex-sync` as a private repository when missing, verifies that an existing repository is private, and maintains a stable local clone.

Stop on missing dependencies, failed authentication, a public state repository, a dirty state clone, non-fast-forward conflicts, or secret-scan failures. Never force-push.

## Determine project, chat, and thread

Use the natural project name already shown by Codex or the repository/directory name. Use the visible chat title when available; otherwise infer a concise task title. Never use a path, UUID, hash, or thread ID as the primary name.

Obtain the current thread ID only from `CODEX_THREAD_ID`. Pass `--thread-id` only when a trusted host supplies an equivalent stable value. If no ID exists, keep open-mode sync/restore working and report that linking or strict-mode access is unavailable. Never inspect or modify Codex session storage to discover or replace an ID.

List saved chats before choosing a target:

```text
python <skill>/scripts/codex_sync.py list [--project <name>]
```

Match in this order: exact, normalized, then semantic comparison using names and `sync.md`. Prefer an obvious existing chat over creating a near-duplicate. Ask the user only when multiple candidates remain materially ambiguous. Pass the selected canonical names exactly as listed to the CLI.

## Sync

1. Run `inspect --project <canonical-project> --chat <canonical-chat>` to pull the latest state and learn paths/mode.
2. Confirm that the current project and current chat normalize to the canonical names. Do not write from a consumer or differently named chat.
3. Read any existing `sync.md`, `context.md`, and `links.md` needed to preserve durable knowledge.
4. Create three UTF-8 Markdown staging files using the templates in `assets/templates/`:
   - Replace `sync.md` with a compact current checkpoint: task, status, completed work, current work, next step, constraints, blockers.
   - Merge `context.md` as durable memory: decisions, reasons, requirements, rejected options worth retaining, important facts. Deduplicate and remove only clearly obsolete material.
   - Update `links.md` with meaningful repositories, directories, servers, APIs, documents, services, or environments. Record secret locations, never secret values.
5. Select only small artifacts required to continue and unavailable elsewhere.
6. Call `write` with both canonical and current names, the three staging files, and any artifacts. Add `--enable-linking` only when the user explicitly asks to enable strict linking on this first sync.

```text
python <skill>/scripts/codex_sync.py write \
  --project <canonical-project> --chat <canonical-chat> \
  --current-project <current-project> --current-chat <current-chat> \
  --sync-file <staged-sync.md> --context-file <staged-context.md> \
  --links-file <staged-links.md> [--artifact <path> ...] [--enable-linking]
```

Let the CLI enforce authorization, scan for obvious secrets, commit only real changes, pull/rebase safely, and push. Report the repository and saved `projects/<project>/<chat>` path without exposing credentials.

## Restore

1. Run `list`, then select the canonical saved chat. If the current project contains `.codex-sync/linked-with.md`, allow the CLI to resolve the target by omitting `--project` and `--chat`.
2. Call `restore` with the current project/chat names and project root. The CLI pulls current state and enforces strict linking.

```text
python <skill>/scripts/codex_sync.py restore \
  [--project <canonical-project> --chat <canonical-chat>] \
  --current-project <current-project> --current-chat <current-chat> \
  --project-root <current-project-root>
```

3. Read the returned `sync_path` and `links_path` first. Reconstruct the immediate task and explain briefly what was restored.
4. Read only relevant sections of `context_path` when `sync.md` is insufficient, an old decision matters, or ambiguity remains. Do not load it automatically in full.
5. Use artifacts only when needed. Do not write or commit during restore.

Restore never imports, clones, resumes, or changes an internal Codex thread and never assigns an old thread ID.

## Link

Select an existing canonical saved chat, then call:

```text
python <skill>/scripts/codex_sync.py link \
  --project <canonical-project> --chat <canonical-chat> \
  --current-project <current-project> --current-chat <current-chat> \
  --project-root <current-project-root>
```

The CLI reads `CODEX_THREAD_ID`, computes `source` for normalized same-name project+chat and `consumer` otherwise, updates `linked-chats.md` without duplicates, commits and pushes it, and writes the local consumer marker. If an existing local marker points elsewhere, stop; use `--replace-marker` only after the user explicitly confirms reassignment.

After linking, run restore separately when the user requested both. Do not make link silently restore state.

## Protect state and artifacts

- Never store passwords, tokens, keys, cookies, `.env` contents, authentication files, or private keys.
- Treat private GitHub storage as defense in depth, not permission to store credentials.
- Keep `sync.md` compact and current, not append-only and not a transcript.
- Keep `context.md` curated, not an unbounded conversation dump.
- Keep artifacts small; prefer a link in `links.md` for source-controlled or large files.
- Do not copy the workspace or project repository into the state repository.
- Do not edit `linked-chats.md` or `linked-with.md` by hand when the CLI can do it.

Read [state-format.md](references/state-format.md) when authoring or interpreting state files. Read [automation.md](references/automation.md) only when the user requests automatic, hook-based, milestone, task-switch, completion, scheduled, or timer sync.

## Handle failures

- Missing `gh`: stop and ask the user to install GitHub CLI.
- Unauthenticated `gh`: stop and ask the user to run `gh auth login`.
- Missing `CODEX_THREAD_ID`: disable linking and strict-mode access only; preserve open-mode sync/restore.
- Consumer sync: refuse and explain that cross-project links are restore-only.
- Unlinked strict restore/sync: refuse and direct the user to link first.
- Git conflict or rejected safe rebase: stop without force-pushing or deleting either version.
- No actual changes: report an up-to-date state and do not create an empty commit.
- Unsupported background context access: explain the limitation; never pretend a scheduler can synthesize live LLM state.
