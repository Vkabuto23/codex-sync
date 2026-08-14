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

- A canonical source has the same project name and the exact same user-facing chat title as the saved chat. Only a canonical source may write with `sync`.
- A same-name linked thread receives role `source` and may sync and restore.
- A linked thread whose project or chat differs receives role `consumer` and may restore only. Never allow it to sync, even if it has a valid thread ID.
- When `linked-chats.md` is absent, use open mode: canonical sources may sync and restore is allowed without a thread ID.
- When `linked-chats.md` exists, use strict mode: require the current thread ID for sync and restore. Require role `source` for sync; allow `source` or `consumer` for restore.
- Allow `link` to add the current thread explicitly. Derive its role from the names; never accept a caller-supplied role.
- Create `<current-project-root>/.codex-sync/linked-with.md` for every consumer link. Use this local marker to resolve later restores. Never create it for a canonical source.

Do not weaken these rules based on semantic similarity. Use semantic matching only to select restore/link targets. Never use it to choose or invent a sync destination.

## Locate the CLI

Resolve `scripts/codex_sync.py` relative to this `SKILL.md`. Run it with Python 3.10+.

Start every operation with:

```text
python <skill>/scripts/codex_sync.py doctor
python <skill>/scripts/codex_sync.py bootstrap
```

The CLI requires `git` and an authenticated GitHub CLI session. It obtains the GitHub login from `gh api user --jq .login`, creates `{login}-codex-sync` as a private repository when missing, verifies that an existing repository is private, and maintains a stable local clone.

Treat GitHub access as sandbox-sensitive. When the host already declares network or OS credential-store access restricted, run `doctor`, `bootstrap`, and every GitHub-dependent codex-sync command with the host's approved system/escalated access from the outset. Otherwise try normally once; if the CLI reports network, sandbox, permission, or credential-store isolation, repeat the exact command through the approval flow. Do not ask the user to run `gh auth login` until the approved retry also reports a real authentication failure such as HTTP 401 or bad credentials. Never try to bypass the approval flow or read token values.

Stop on missing dependencies, failed authentication, a public state repository, a dirty state clone, non-fast-forward conflicts, or secret-scan failures. Never force-push.

## Determine project, exact chat title, and thread

Use the natural project name already shown by Codex or the repository/directory name. Never infer, summarize, translate, shorten, or reuse an old name for the current chat.

Before every sync or link, resolve the exact user-facing title:

```text
python <skill>/scripts/codex_sync.py current-title
```

The CLI uses the documented read-only Codex App Server `thread/read` method with `CODEX_THREAD_ID` and returns `thread.name`. Copy the returned `title` byte-for-byte into `--chat` and optionally `--current-chat`. The `write` and `link` commands verify it again before any GitHub mutation and reject a mismatch.

If App Server cannot return a title or returns `null`, stop. Ask the user to copy the exact visible chat title. Only after that explicit answer may you pass it with `--current-chat <exact-title> --user-confirmed-title`. Never generate a fallback title yourself.

Preserve Cyrillic and other Unicode characters. Normalize only to Unicode NFC for cross-platform consistency. Do not transliterate. If the exact title contains Windows-forbidden filename characters (`< > : " / \\ | ? *`), is a reserved filename, has leading/trailing whitespace, or exceeds 100 characters, ask the user to rename the chat; never silently replace characters.

Obtain the current thread ID only from `CODEX_THREAD_ID`. Pass `--thread-id` only when a trusted host supplies an equivalent stable value. If no ID exists, keep restore working and allow open-mode sync only after the user explicitly supplies the exact title via `--user-confirmed-title`; report that linking or strict-mode access is unavailable. Never inspect or modify Codex session storage to discover or replace an ID.

List saved chats before choosing a restore or link target:

```text
python <skill>/scripts/codex_sync.py list [--project <name>]
```

For restore/link, match in this order: exact, normalized, then semantic comparison using names and `sync.md`. Ask the user only when multiple candidates remain materially ambiguous. For sync, do not perform semantic matching: use only the exact title returned by `current-title`. If no directory with that exact title exists, create it as a new saved chat.

## Sync

1. Run `current-title` and treat its exact `title` as both the current chat and canonical saved-chat name.
2. Run `inspect --project <current-project> --chat <exact-title>` to pull the latest state and learn paths/mode. Never inspect or select a differently named chat for sync.
3. Confirm that the current project and exact current title equal the canonical names. Do not write from a consumer or differently named chat.
4. Read any existing `sync.md`, `context.md`, and `links.md` needed to preserve durable knowledge.
5. Create three UTF-8 Markdown staging files using the templates in `assets/templates/`:
   - Replace `sync.md` with a compact current checkpoint: task, status, completed work, current work, next step, constraints, blockers.
   - Merge `context.md` as durable memory: decisions, reasons, requirements, rejected options worth retaining, important facts. Deduplicate and remove only clearly obsolete material.
   - Update `links.md` with meaningful repositories, directories, servers, APIs, documents, services, or environments. Record secret locations, never secret values.
6. Select only small artifacts required to continue and unavailable elsewhere.
7. Call `write` with the exact title, the three staging files, and any artifacts. Add `--enable-linking` only when the user explicitly asks to enable strict linking on this first sync.

```text
python <skill>/scripts/codex_sync.py write \
  --project <current-project> --chat <exact-current-title> \
  --current-project <current-project> --current-chat <exact-current-title> \
  --sync-file <staged-sync.md> --context-file <staged-context.md> \
  --links-file <staged-links.md> [--artifact <path> ...] [--enable-linking]
```

Let the CLI enforce authorization, scan for obvious secrets, commit only real changes, pull/rebase safely, and push. Report the repository and saved `projects/<project>/<chat>` path without exposing credentials.

## Restore

1. Run `list`, then select the canonical saved chat. If the current project contains `.codex-sync/linked-with.md`, allow the CLI to resolve the target by omitting `--project` and `--chat`.
2. Decide whether this is a fresh restore-only chat. Treat it as fresh only when the conversation was created for this restore and contains no earlier substantive task. Do not infer freshness merely from a generic or generated title.
3. For a fresh restore-only chat, rename it automatically to the exact canonical source title before presenting restored work. Prefer the host's native thread-title tool (for example `set_thread_title` in Codex App) so the open UI updates immediately. Then call `restore` normally with the new exact title. If no native title tool exists, add `--empty-chat`; the CLI uses App Server `thread/name/set` as a portable fallback. `--current-chat` may be omitted only with `--empty-chat`.

```text
python <skill>/scripts/codex_sync.py restore \
  [--project <canonical-project> --chat <canonical-chat>] \
  --current-project <current-project> --current-chat <current-chat> \
  --project-root <current-project-root> [--empty-chat]
```

4. Read `title_alignment` in the result. If the current title differs, `may_offer_semantic_sync` is true, and the current title is semantically similar to the canonical source title, ask once whether to rename it to the exact source title. Do not offer merely because both chats are in the same project. Never rename a non-empty chat without consent.
5. On acceptance, prefer the host's native thread-title tool to rename the open chat immediately, then run `title-sync --accept` to verify the persisted title and clear any refusal. If no native tool exists, `title-sync --accept` performs the rename through App Server. On refusal, run `title-sync --decline` immediately. The decline is stored locally by current thread ID. If `suggestion_declined_locally` is true on any later restore in that chat, never ask again. A later explicit user request to align the title may still use `--accept`, which clears the refusal.

```text
python <skill>/scripts/codex_sync.py title-sync \
  --project <canonical-project> --chat <canonical-chat> \
  (--accept | --decline)
```

6. Read the returned `sync_path` and `links_path` first. Reconstruct the immediate task and explain briefly what was restored.
7. Read only relevant sections of `context_path` when `sync.md` is insufficient, an old decision matters, or ambiguity remains. Do not load it automatically in full.
8. Use artifacts only when needed. Do not write or commit during restore.

Restore never imports, clones, resumes, or assigns an old thread ID. It may change only the current thread's user-facing name under the rules above.

## Link

Select an existing canonical saved chat, then call:

```text
python <skill>/scripts/codex_sync.py link \
  --project <canonical-project> --chat <canonical-chat> \
  --current-project <current-project> --current-chat <current-chat> \
  --project-root <current-project-root>
```

The CLI reads `CODEX_THREAD_ID` and the exact App Server title, computes `source` only for exactly matching project+chat names and `consumer` otherwise, updates `linked-chats.md` without duplicates, commits and pushes it, and writes the local consumer marker. If an existing local marker points elsewhere, stop; use `--replace-marker` only after the user explicitly confirms reassignment.

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
- Sandbox/network/credential-store isolation: retry the same command with approved system/escalated access; do not misdiagnose it as logout.
- Unauthenticated `gh` confirmed after an approved retry: stop and ask the user to run `gh auth login`.
- Missing `CODEX_THREAD_ID`: disable linking and strict-mode access; preserve restore and allow open-mode sync only after explicit exact-title confirmation.
- Missing or unverifiable current title: stop sync/link and ask the user to copy the exact visible title; never infer one.
- App Server title differs from `--chat`/`--current-chat`: stop before bootstrap, file writes, commit, or push.
- Fresh-chat rename failure: stop and report that automatic title alignment could not be completed; do not silently continue with a different title.
- UI title remains stale after CLI fallback: verify the persisted title, use the host's native title tool when available, and report the refresh limitation instead of claiming the visible UI changed.
- Non-portable exact title: ask the user to rename the chat instead of silently sanitizing it.
- Consumer sync: refuse and explain that cross-project links are restore-only.
- Unlinked strict restore/sync: refuse and direct the user to link first.
- Git conflict or rejected safe rebase: stop without force-pushing or deleting either version.
- No actual changes: report an up-to-date state and do not create an empty commit.
- Unsupported background context access: explain the limitation; never pretend a scheduler can synthesize live LLM state.
