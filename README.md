# codex-sync

`codex-sync` moves the **working context** of a Codex chat between computers through a private GitHub repository. It saves what you are doing, what is already done, durable decisions, relevant external links, the next step, and optional small artifacts.

It does **not** copy project source code, migrate Codex's internal session files, import an old thread, or assign an old thread ID to a new thread. On another computer you create a normal new Codex chat and restore the saved working context into it. A fresh restore-only chat is automatically given the source chat's exact user-facing title.

## What gets created

The skill itself lives in this public repository. On first use it discovers the login from your authenticated GitHub CLI session and creates a separate private repository:

```text
Public skill:  owner/codex-sync
Private state: <your-github-login>/<your-github-login>-codex-sync
```

The private repository is deliberately readable by humans:

```text
projects/
└── aurora-platform/
    └── Supplier parser/
        ├── sync.md
        ├── context.md
        ├── links.md
        ├── linked-chats.md   # optional; enables strict mode
        └── artifacts/
```

- `sync.md` — compact current checkpoint: where the work is and what happens next.
- `context.md` — curated long-term decisions, requirements, rationale, and important facts.
- `links.md` — relevant repositories, directories, servers, APIs, documents, and services.
- `linked-chats.md` — optional allowed local thread IDs and their `source` or `consumer` role.
- `artifacts/` — only small files genuinely required on the other computer.

## Codex sandbox and GitHub authentication

Codex commands inherit the host sandbox, which may block `api.github.com` or access to the OS credential store even when GitHub CLI is already authenticated. `codex-sync` distinguishes these isolation failures from genuine authentication errors. In a restricted Codex environment, rerun GitHub-dependent commands through the normal approval flow with system/network access; do not reauthenticate unless the approved retry also returns HTTP 401 or bad credentials.

The skill never reads or prints the GitHub token. It verifies the account with `gh api user --jq .login` only.

## Requirements

- Codex with local skills support
- Python 3.10 or newer
- Git
- [GitHub CLI](https://cli.github.com/)
- An authenticated GitHub CLI session

Authenticate once:

```shell
gh auth login
gh auth status
```

The token needs permission to create and use private repositories. `codex-sync` never prints or stores the token.

## Install

The simplest Codex installation is:

```text
$skill-installer install from https://github.com/Vkabuto23/codex-sync
```

For a manual user-scoped installation, clone into Codex's user skill directory.

macOS/Linux:

```shell
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/Vkabuto23/codex-sync "$HOME/.agents/skills/codex-sync"
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force -Path "$HOME\.agents\skills" | Out-Null
git clone https://github.com/Vkabuto23/codex-sync "$HOME\.agents\skills\codex-sync"
```

Codex normally detects a new skill automatically. Restart Codex if it does not appear.

## First use

Invoke the skill explicitly:

```text
$codex-sync sync this chat
```

Or ask naturally:

```text
Save this chat's context so I can continue on my Mac.
```

The first operation checks `git`, `gh`, and authentication, discovers your GitHub login, creates `<login>-codex-sync` as **private** if it does not exist, and maintains a local service clone at a stable OS-appropriate location.

Current Codex uses `$codex-sync` for explicit skill invocation. The requested forms `&chat-sync`, `&chat-restore`, and `&chat-link` are recognized as text aliases by the skill, but they are not three separately registered Codex commands.

## Sync, restore, and link

### Sync is write

```text
$codex-sync sync this chat
```

Sync replaces the compact checkpoint, merges durable context and links, copies explicitly selected small artifacts, then commits and pushes only when something changed.

Before writing, the CLI obtains the exact user-facing chat title from Codex App Server `thread/read` using `CODEX_THREAD_ID`. The State Repository directory uses that exact `thread.name`. The model is not allowed to summarize, translate, infer, or reuse an older title.

For example, if the sidebar title is:

```text
GZapp main chat
```

then the only valid destination is:

```text
projects/GZapp/GZapp main chat/
```

`Search and testing 5.5`, `GZapp search`, or any other model-generated alternative is rejected before bootstrap, file writes, commit, or push.

Only the canonical source may write: the current project name and exact current chat title must equal the saved source. A chat linked from another project is a restore-only consumer and can never overwrite it.

### Exact titles and Cyrillic

Git and GitHub support Unicode paths, so Cyrillic titles are kept directly:

```text
projects/GZapp/Поиск и обработка/
```

The CLI preserves titles as Unicode NFC and never transliterates them. A title containing Windows-forbidden filename characters (`< > : " / \\ | ? *`), a reserved Windows device name, leading/trailing whitespace, or more than 100 characters cannot be represented portably across Windows and macOS. In that case sync stops and asks the user to rename the Codex chat; characters are never silently replaced.

If the current host cannot retrieve `thread.name`, sync also stops. The only fallback is to ask the user to copy the exact visible title and then use the explicit `--user-confirmed-title` path. The model must not invent a fallback.

### Restore is read

```text
$codex-sync restore Supplier parser
```

Restore pulls the latest state, reads `sync.md` and `links.md` first, and loads only relevant parts of `context.md` when needed. It does not push, mutate the saved state, resume an old Codex session, or change the current thread ID.

When the current conversation was created only for restore and has no earlier substantive task, restore renames it automatically to the exact canonical source title. In Codex App it prefers the native thread-title action so the open sidebar updates immediately. Other hosts fall back to the documented Codex App Server `thread/name/set` method. A non-empty chat is never renamed without consent.

If a non-empty chat has a semantically similar title, Codex offers title alignment once. Accepting renames the current chat. Refusing writes a local preference keyed by the current thread ID, outside both the project and State Repository, so that local chat is not asked again. An explicit later request can still align the title and clear the refusal.

Saved chats are searched by exact match, normalized match, then semantic match. Codex proposes a short candidate list when the choice is genuinely ambiguous, instead of creating or restoring a near-duplicate blindly.

### Link adds explicit authorization

```text
$codex-sync link Supplier parser
```

Linking uses the stable `CODEX_THREAD_ID` supplied by current Codex hosts. It never reads or modifies internal session storage.

The role is derived, not chosen:

| Current location | Role | Restore | Sync |
| --- | --- | --- | --- |
| Same project and exact chat title as the saved source | `source` | Yes | Yes |
| Any different project or chat | `consumer` | Yes | **No** |

This is the central safety rule. Five computers can all write when each has the same canonical project/chat and each thread is linked as a source. Ten chats in other projects can consume the same context, but all ten remain restore-only.

For a consumer link, the skill also creates a local marker:

```text
<consumer-project>/.codex-sync/linked-with.md
```

The marker records which canonical saved chat this local project/chat restores from. It prevents the cross-project relationship from being lost and lets later restores resolve the target without relying only on similar names.

## Open mode and strict mode

New saved chats start in open mode unless linking is explicitly enabled. In open mode there is no `linked-chats.md`; canonical sources can sync and restore does not require a thread ID.

The presence of `linked-chats.md` enables strict mode. Then:

- sync requires a linked `source` thread and matching canonical names;
- restore requires a linked `source` or `consumer` thread;
- an unlinked thread is refused and must run link first;
- a consumer is refused for sync even though it is linked.

If a Codex host does not expose a reliable `CODEX_THREAD_ID`, restore still works and open-mode sync remains available only after the user explicitly copies and confirms the exact visible title. Linking and access to strict chats are reported as unavailable; they are never simulated.

## Typical Windows → Mac workflow

Without strict linking:

1. On Windows, run `$codex-sync sync this chat` in project `aurora-platform`, chat `Supplier parser`.
2. On the Mac, open the same logical project, create a new Codex chat, and run `$codex-sync restore Supplier parser`.
3. The Mac chat receives the working context and the exact title `Supplier parser`; its local Codex thread remains a new, unrelated internal session.

With strict linking:

1. On Windows, sync and explicitly enable linking. The Windows thread becomes a `source`.
2. On the Mac, use the same project and chat names and run `$codex-sync link Supplier parser`. The Mac thread becomes another `source`, so both devices may sync.
3. In a different project, run link to the same saved chat. That thread becomes a `consumer`, gets `.codex-sync/linked-with.md`, and may restore but never sync.

## Automatic sync

Automatic behavior is opt-in. While a Codex task is active, the skill can treat sync as a required action:

- before reporting task completion;
- before switching to a materially different task;
- at meaningful milestones.

A Git hook or OS timer cannot independently synthesize current `sync.md`, `context.md`, and `links.md` without access to live model context. The skill therefore does not pretend that a background shell process can perform full context sync. Timer-based live-chat sync is supported only if a future/current host verifiably exposes the target thread and its current context to the scheduled run.

## Security and conflict handling

- The state repository must be private. The CLI refuses an existing public repository of the expected name.
- Passwords, API keys, access tokens, cookies, private keys, `.env` contents, and credential files are forbidden even in the private repository.
- Artifacts are size-limited and checked for obvious credentials.
- The CLI fetches before writes, uses fast-forward updates and a safe rebase retry, never force-pushes, and stops on unresolved conflicts.
- A dirty service clone causes a stop instead of silently discarding local data.
- Project code and whole workspaces are never copied into the state repository.

## Direct CLI diagnostics

Most users should let Codex operate the bundled CLI. For troubleshooting:

```shell
python scripts/codex_sync.py doctor
python scripts/codex_sync.py current-title
python scripts/codex_sync.py bootstrap
python scripts/codex_sync.py list
python scripts/codex_sync.py title-sync --help
```

Use `python scripts/codex_sync.py --help` for the deterministic command interface.

## License

MIT
