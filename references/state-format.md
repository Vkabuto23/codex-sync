# State format

Use this reference when creating, merging, or interpreting saved chat state.

## Repository tree

```text
projects/
└── <human project name>/
    └── <human chat name>/
        ├── sync.md
        ├── context.md
        ├── links.md
        ├── linked-chats.md   # optional; its presence enables strict mode
        └── artifacts/        # optional contents
```

Project and chat directory names are human-readable. A chat directory must equal the exact user-facing Codex `thread.name`, preserved as Unicode NFC. Cyrillic and other Unicode scripts are stored without transliteration. Never infer or silently sanitize a chat title. If it contains Windows-invalid characters, trailing dots/spaces, a reserved device name, or exceeds 100 characters, require the user to rename the chat before sync. UUIDs and thread IDs never become the primary directory name.

## `sync.md`

Answer “Where is the work now?” in a compact checkpoint. Replace stale checkpoint information instead of appending a history.

Required headings:

- Current task
- Current status
- Completed
- In progress
- Next step
- Constraints
- Blockers

Prefer short bullets. Include only enough detail for another Codex instance to continue immediately.

## `context.md`

Answer “What must remain remembered?” Preserve durable decisions and their reasons, requirements, meaningful rejected alternatives, important discoveries, and stable technical facts. Merge duplicates. Update changed decisions in place. Delete only clearly obsolete facts.

Organize by meaningful topic headings rather than chronology. Do not paste transcripts.

## `links.md`

Answer “What external resources matter?” Use one section per resource:

```markdown
## Primary repository

- Type: GitHub repository
- Target: owner/project
- Purpose: Application source and issues
- Notes: Optional non-secret detail
```

Never include secret values. It is acceptable to say that `OPENAI_API_KEY` is expected in the environment.

## `linked-chats.md`

The CLI owns this Markdown table:

```markdown
# Linked Codex threads

| Thread | Role | Project | Chat | Device |
| --- | --- | --- | --- | --- |
| 11111111-1111-1111-1111-111111111111 | source | aurora-platform | Parser work | workstation |
| 22222222-2222-2222-2222-222222222222 | consumer | reporting | Supplier dashboard | laptop |
```

Presence enables strict mode. `source` is computed only when project name and exact chat title equal the canonical directory names. Every other link is `consumer` and restore-only.

## Local `linked-with.md`

For consumer links, the CLI writes:

```text
<consumer project root>/.codex-sync/linked-with.md
```

It records the canonical source project/chat, state repository, local thread, and restore-only access. It is local navigation state; it does not grant write authority. A marker pointing at a different source must not be overwritten without explicit user confirmation.

## `artifacts/`

Store only small files that are required for continuation and unavailable from the project repository or another stable resource. Reject credentials, `.env` files, private keys, Git credential stores, and oversized files. Preserve only file names, not arbitrary source directory trees.
