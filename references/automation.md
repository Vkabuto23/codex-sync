# Automation boundaries

Read this reference only when the user asks for automatic synchronization.

## Supported inside an active Codex task

Codex can treat sync as a required workflow action when the user explicitly requests one of these policies:

- before the final completion response;
- before switching to a materially different task;
- at meaningful milestones such as completing a phase, choosing an architecture, removing a blocker, or changing the plan.

Record the requested policy in the live conversation and perform a normal authorized sync at the relevant point. Do not treat every small clarification as a task switch or milestone.

## Git hooks

A Git hook can run deterministic commands, but it cannot synthesize fresh `sync.md`, `context.md`, and `links.md` without access to live model context. Therefore do not install a hook that claims to perform full context sync.

If the user already has staged state files and explicitly wants push automation, a hook may call a deterministic Git-only helper, but preserving existing hooks and handling hook-manager conventions is required. This skill intentionally does not install such a hook by default.

## Timers and scheduled tasks

A system scheduler or Codex scheduled task can fetch/push already-authored files, but it cannot be assumed to see or summarize a currently active chat. Do not claim timer-based live-context sync unless the host exposes both the target thread and its current context to the scheduled run and this is verified in that environment.

Offer the reliable fallback: sync at explicit milestones, task completion, or task switches while the conversation is active.
