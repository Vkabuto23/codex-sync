#!/usr/bin/env python3
"""Deterministic Git/GitHub and authorization layer for the codex-sync skill."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


VERSION = "1.0.0"
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
THREAD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,199}$")
KNOWN_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)"
        r"\s*[:=]\s*['\"]?(?!<|\$\{|expected\b|set\b|redacted\b)[A-Za-z0-9/+_.=-]{12,}"
    ),
]
BLOCKED_ARTIFACT_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "auth.json",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}


class SyncError(RuntimeError):
    """A safe, user-actionable failure."""


@dataclass(frozen=True)
class RepoContext:
    username: str
    full_name: str
    url: str
    path: Path


@dataclass(frozen=True)
class LinkRecord:
    thread: str
    role: str
    project: str
    chat: str
    device: str


def log(message: str) -> None:
    print(f"[codex-sync] {message}", file=sys.stderr)


def redact(text: str) -> str:
    text = re.sub(r"\b(?:gh[opusr]_|github_pat_|sk-(?:proj-)?)[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)
    text = re.sub(r"(?i)(authorization:\s*(?:bearer|token)\s+)\S+", r"\1[REDACTED]", text)
    return text


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode:
        detail = redact((result.stderr or result.stdout).strip())
        if len(detail) > 1200:
            detail = detail[:1200] + "…"
        raise SyncError(f"Command failed ({command[0]}): {detail or 'unknown error'}")
    return result


def emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def require_program(name: str, install_hint: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SyncError(f"Required program '{name}' was not found. {install_hint}")
    return path


def github_username() -> str:
    require_program("gh", "Install GitHub CLI from https://cli.github.com/ and run 'gh auth login'.")
    status = run(["gh", "auth", "status"], check=False)
    if status.returncode:
        raise SyncError("GitHub CLI is not authenticated. Run 'gh auth login', then retry.")
    result = run(["gh", "api", "user", "--jq", ".login"])
    username = result.stdout.strip()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", username):
        raise SyncError("GitHub CLI returned an invalid account login.")
    return username


def default_state_path(repository_name: str) -> Path:
    configured = os.environ.get("CODEX_SYNC_STATE_DIR")
    if configured:
        return Path(configured).expanduser().resolve() / repository_name
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return (base / "codex-sync" / "state" / repository_name).resolve()


def check_dependencies() -> dict[str, str]:
    git_path = require_program("git", "Install Git 2.30 or newer.")
    gh_path = require_program("gh", "Install GitHub CLI from https://cli.github.com/.")
    username = github_username()
    git_version = run([git_path, "--version"]).stdout.strip()
    gh_version = run([gh_path, "--version"]).stdout.splitlines()[0].strip()
    return {
        "git": git_version,
        "gh": gh_version,
        "github_username": username,
        "thread_id_available": str(bool(os.environ.get("CODEX_THREAD_ID"))).lower(),
        "python": platform.python_version(),
    }


def repository_metadata(full_name: str) -> dict[str, object] | None:
    result = run(["gh", "api", f"repos/{full_name}"], check=False)
    if result.returncode:
        combined = f"{result.stdout}\n{result.stderr}"
        if "HTTP 404" in combined or "Not Found" in combined:
            return None
        raise SyncError(f"Could not inspect GitHub repository {full_name}: {redact(result.stderr.strip())}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SyncError("GitHub CLI returned malformed repository metadata.") from exc


def ensure_private_remote(username: str) -> tuple[str, str]:
    repository_name = f"{username}-codex-sync"
    full_name = f"{username}/{repository_name}"
    metadata = repository_metadata(full_name)
    if metadata is None:
        log(f"Creating private state repository {full_name}")
        run(
            [
                "gh",
                "repo",
                "create",
                full_name,
                "--private",
                "--description",
                "Private, human-readable Codex working-context state",
                "--disable-issues",
                "--disable-wiki",
            ]
        )
        metadata = repository_metadata(full_name)
    if not metadata or metadata.get("private") is not True:
        raise SyncError(
            f"Refusing to use {full_name}: the state repository must exist as a private repository."
        )
    clone_url = str(metadata.get("clone_url") or f"https://github.com/{full_name}.git")
    return full_name, clone_url


def configure_local_identity(repo: Path, username: str) -> None:
    if not run(["git", "config", "user.name"], cwd=repo, check=False).stdout.strip():
        run(["git", "config", "user.name", username], cwd=repo)
    if not run(["git", "config", "user.email"], cwd=repo, check=False).stdout.strip():
        run(["git", "config", "user.email", f"{username}@users.noreply.github.com"], cwd=repo)


def remote_matches(repo: Path, full_name: str) -> bool:
    result = run(["git", "remote", "get-url", "origin"], cwd=repo, check=False)
    if result.returncode:
        return False
    normalized = result.stdout.strip().lower().removesuffix(".git")
    expected = full_name.lower()
    return normalized.endswith(f"github.com/{expected}") or normalized.endswith(f"github.com:{expected}")


def has_commit(repo: Path, revision: str = "HEAD") -> bool:
    return run(["git", "rev-parse", "--verify", revision], cwd=repo, check=False).returncode == 0


def assert_clean(repo: Path) -> None:
    status = run(["git", "status", "--porcelain"], cwd=repo).stdout.strip()
    if status:
        raise SyncError(
            f"The codex-sync service clone is dirty at {repo}. Resolve or commit those changes before retrying."
        )


def current_branch(repo: Path) -> str:
    branch = run(["git", "branch", "--show-current"], cwd=repo).stdout.strip()
    return branch or "main"


def pull_latest(repo: Path) -> str:
    assert_clean(repo)
    run(["git", "fetch", "--prune", "origin"], cwd=repo)
    branch = current_branch(repo)
    remote_ref = f"origin/{branch}"
    if has_commit(repo, remote_ref):
        run(["git", "merge", "--ff-only", remote_ref], cwd=repo)
    return branch


def initialize_empty_repository(repo: Path, username: str) -> None:
    (repo / "projects").mkdir(parents=True, exist_ok=True)
    (repo / "projects" / ".gitkeep").write_text("", encoding="utf-8")
    (repo / "README.md").write_text(
        "# Codex Sync State\n\n"
        "Private, human-readable working-context state managed by the `codex-sync` skill.\n\n"
        "Do not store credentials, secrets, project source trees, or internal Codex session files here.\n",
        encoding="utf-8",
    )
    configure_local_identity(repo, username)
    run(["git", "add", "--", "README.md", "projects/.gitkeep"], cwd=repo)
    run(["git", "commit", "-m", "Initialize codex-sync state repository"], cwd=repo)
    run(["git", "branch", "-M", "main"], cwd=repo)
    run(["git", "push", "-u", "origin", "main"], cwd=repo)


def ensure_repository() -> RepoContext:
    require_program("git", "Install Git 2.30 or newer.")
    username = github_username()
    full_name, clone_url = ensure_private_remote(username)
    repo = default_state_path(full_name.split("/", 1)[1])
    if (repo / ".git").is_dir():
        if not remote_matches(repo, full_name):
            raise SyncError(f"Existing state directory {repo} points to an unexpected Git remote.")
    else:
        if repo.exists() and any(repo.iterdir()):
            raise SyncError(f"State directory {repo} exists and is not an empty Git clone.")
        repo.parent.mkdir(parents=True, exist_ok=True)
        log(f"Cloning state repository into {repo}")
        run(["git", "clone", clone_url, str(repo)])
    configure_local_identity(repo, username)
    if not has_commit(repo):
        initialize_empty_repository(repo, username)
    else:
        pull_latest(repo)
    return RepoContext(username=username, full_name=full_name, url=f"https://github.com/{full_name}", path=repo)


def safe_name(value: str, kind: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = INVALID_PATH_CHARS.sub("-", value)
    value = re.sub(r"\s+", " ", value).rstrip(" .")
    if not value or value in {".", ".."}:
        raise SyncError(f"{kind} name is empty after safe filesystem normalization.")
    stem = value.split(".", 1)[0].upper()
    if stem in RESERVED_WINDOWS_NAMES:
        value += "-project" if kind == "project" else "-chat"
    if len(value) > 100:
        value = value[:100].rstrip(" .")
    return value


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def canonical_names(project: str, chat: str) -> tuple[str, str]:
    return safe_name(project, "project"), safe_name(chat, "chat")


def chat_path(repo: Path, project: str, chat: str) -> Path:
    project_name, chat_name = canonical_names(project, chat)
    return repo / "projects" / project_name / chat_name


def relative_posix(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()


def parse_link_records(path: Path) -> list[LinkRecord]:
    if not path.exists():
        return []
    records: list[LinkRecord] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.startswith("|") or raw.startswith("| ---") or raw.startswith("| Thread"):
            continue
        cells = [cell.strip().replace("\\|", "|") for cell in raw.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise SyncError(f"Malformed link table in {path}.")
        record = LinkRecord(*cells)
        if record.role not in {"source", "consumer"} or not THREAD_RE.fullmatch(record.thread):
            raise SyncError(f"Invalid link record in {path}.")
        records.append(record)
    return records


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


def write_link_records(path: Path, records: Iterable[LinkRecord]) -> None:
    unique = {record.thread: record for record in records}
    lines = [
        "# Linked Codex threads",
        "",
        "| Thread | Role | Project | Chat | Device |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in sorted(unique.values(), key=lambda item: (item.role, item.project.casefold(), item.chat.casefold(), item.thread)):
        lines.append(
            "| " + " | ".join(markdown_cell(value) for value in asdict(record).values()) + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_thread_id(explicit: str | None, *, required: bool) -> str | None:
    thread_id = explicit or os.environ.get("CODEX_THREAD_ID")
    if not thread_id:
        if required:
            raise SyncError(
                "Current Codex thread ID is unavailable. Linking and strict-mode access cannot be simulated; use open mode or a host that exposes CODEX_THREAD_ID."
            )
        return None
    if not THREAD_RE.fullmatch(thread_id):
        raise SyncError("The current Codex thread ID has an unexpected format.")
    return thread_id


def computed_role(current_project: str, current_chat: str, source_project: str, source_chat: str) -> str:
    current_project_name, current_chat_name = canonical_names(current_project, current_chat)
    if normalized(current_project_name) == normalized(source_project) and normalized(current_chat_name) == normalized(source_chat):
        return "source"
    return "consumer"


def assert_canonical_writer(current_project: str, current_chat: str, source_project: str, source_chat: str) -> None:
    if computed_role(current_project, current_chat, source_project, source_chat) != "source":
        raise SyncError(
            "Sync denied: only a chat with the same canonical project and chat names may write. Cross-project or differently named links are restore-only consumers."
        )


def authorize_strict(path: Path, thread_id: str, *, write: bool) -> LinkRecord:
    records = parse_link_records(path)
    record = next((item for item in records if item.thread == thread_id), None)
    if record is None:
        raise SyncError("This saved chat uses strict linking and the current thread is not linked. Run link first.")
    if write and record.role != "source":
        raise SyncError("Sync denied: the current linked thread is a restore-only consumer.")
    return record


def secret_findings(path: Path, text: str) -> list[str]:
    findings: list[str] = []
    for index, pattern in enumerate(KNOWN_SECRET_PATTERNS, start=1):
        if pattern.search(text):
            findings.append(f"{path.name}: secret pattern {index}")
    return findings


def read_safe_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SyncError(f"Expected a UTF-8 Markdown file: {path}") from exc


def validate_state_inputs(paths: Sequence[Path]) -> None:
    findings: list[str] = []
    for path in paths:
        if not path.is_file():
            raise SyncError(f"Required staged state file does not exist: {path}")
        findings.extend(secret_findings(path, read_safe_text(path)))
    if findings:
        raise SyncError("Possible credential material detected; nothing was written. " + "; ".join(findings))


def validate_artifact(path: Path) -> None:
    if not path.is_file():
        raise SyncError(f"Artifact is not a file: {path}")
    if path.name.casefold() in BLOCKED_ARTIFACT_NAMES or path.suffix.casefold() in {".pem", ".key", ".p12", ".pfx"}:
        raise SyncError(f"Blocked credential-like artifact: {path.name}")
    size = path.stat().st_size
    if size > MAX_ARTIFACT_BYTES:
        raise SyncError(f"Artifact {path.name} is larger than the {MAX_ARTIFACT_BYTES // (1024 * 1024)} MiB limit.")
    if size <= 2 * 1024 * 1024:
        sample = path.read_bytes()
        text = sample.decode("utf-8", errors="ignore")
        findings = secret_findings(path, text)
        if findings:
            raise SyncError("Possible credential material detected in artifact; nothing was written. " + "; ".join(findings))


def commit_and_push(repo: Path, paths: Sequence[Path], message: str) -> tuple[bool, str | None]:
    branch = current_branch(repo)
    relative = [relative_posix(path, repo) for path in paths]
    run(["git", "add", "--", *relative], cwd=repo)
    changed = run(["git", "diff", "--cached", "--quiet"], cwd=repo, check=False).returncode != 0
    if not changed:
        return False, None
    run(["git", "commit", "-m", message], cwd=repo)
    commit = run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    pushed = run(["git", "push", "origin", branch], cwd=repo, check=False)
    if pushed.returncode:
        log("Push was rejected; attempting one safe rebase on the latest remote state")
        run(["git", "fetch", "origin"], cwd=repo)
        remote_ref = f"origin/{branch}"
        rebased = run(["git", "rebase", remote_ref], cwd=repo, check=False)
        if rebased.returncode:
            run(["git", "rebase", "--abort"], cwd=repo, check=False)
            raise SyncError("Concurrent state changes caused a Git conflict. Rebase was aborted; no force push was attempted.")
        second = run(["git", "push", "origin", branch], cwd=repo, check=False)
        if second.returncode:
            raise SyncError("State changed concurrently again. Push stopped without force; retry after reviewing the remote state.")
        commit = run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    return True, commit


def marker_path(project_root: str) -> Path:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise SyncError(f"Current project root does not exist: {root}")
    return root / ".codex-sync" / "linked-with.md"


def marker_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    pattern = re.compile(r"^- ([A-Za-z ]+): `([^`]*)`$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            values[match.group(1).casefold().replace(" ", "_")] = match.group(2)
    return values


def marker_text(ctx: RepoContext, source_project: str, source_chat: str, record: LinkRecord) -> str:
    return (
        "# Linked with Codex Sync\n\n"
        "This local chat consumes a canonical saved chat. The link is restore-only because its project or chat name differs from the source.\n\n"
        f"- State repository: `{ctx.full_name}`\n"
        f"- Source project: `{source_project}`\n"
        f"- Source chat: `{source_chat}`\n"
        f"- Local project: `{record.project}`\n"
        f"- Local chat: `{record.chat}`\n"
        f"- Local thread: `{record.thread}`\n"
        "- Access: `restore-only`\n\n"
        "Do not use this consumer chat to sync back into the canonical source.\n"
    )


def prepare_marker(path: Path, source_project: str, source_chat: str, replace: bool) -> None:
    existing = marker_values(path)
    if not existing:
        return
    same = (
        existing.get("source_project") == source_project
        and existing.get("source_chat") == source_chat
    )
    if not same and not replace:
        raise SyncError(
            f"Local marker {path} already points to another saved chat. Re-run with --replace-marker only after explicit confirmation."
        )


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="linked-with-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def resolve_restore_target(args: argparse.Namespace, repo: Path) -> tuple[str, str]:
    if bool(args.project) != bool(args.chat):
        raise SyncError("Provide both --project and --chat, or omit both and use a local linked-with marker.")
    if args.project and args.chat:
        return canonical_names(args.project, args.chat)
    if not args.project_root:
        raise SyncError("A --project-root is required when resolving restore from a local marker.")
    values = marker_values(marker_path(args.project_root))
    source_project = values.get("source_project")
    source_chat = values.get("source_chat")
    if not source_project or not source_chat:
        raise SyncError("No usable .codex-sync/linked-with.md marker was found. Specify --project and --chat.")
    return canonical_names(source_project, source_chat)


def cmd_doctor(_args: argparse.Namespace) -> None:
    details = check_dependencies()
    details.update({"ok": True, "version": VERSION})
    emit(details)


def cmd_bootstrap(_args: argparse.Namespace) -> None:
    ctx = ensure_repository()
    emit({"ok": True, "repository": ctx.full_name, "private": True, "url": ctx.url, "local_path": str(ctx.path)})


def iter_saved_chats(repo: Path, project_filter: str | None = None) -> list[dict[str, object]]:
    projects_root = repo / "projects"
    wanted = normalized(safe_name(project_filter, "project")) if project_filter else None
    result: list[dict[str, object]] = []
    if not projects_root.exists():
        return result
    for project in sorted((p for p in projects_root.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        if wanted and normalized(project.name) != wanted:
            continue
        for chat in sorted((p for p in project.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
            sync_file = chat / "sync.md"
            if not sync_file.is_file():
                continue
            text = read_safe_text(sync_file)
            summary = " ".join(line.strip("# -*\t") for line in text.splitlines() if line.strip())[:300]
            result.append(
                {
                    "project": project.name,
                    "chat": chat.name,
                    "strict_linking": (chat / "linked-chats.md").is_file(),
                    "summary": summary,
                }
            )
    return result


def cmd_list(args: argparse.Namespace) -> None:
    ctx = ensure_repository()
    emit({"repository": ctx.full_name, "chats": iter_saved_chats(ctx.path, args.project)})


def cmd_inspect(args: argparse.Namespace) -> None:
    ctx = ensure_repository()
    source_project, source_chat = canonical_names(args.project, args.chat)
    target = chat_path(ctx.path, source_project, source_chat)
    exists = (target / "sync.md").is_file()
    emit(
        {
            "repository": ctx.full_name,
            "project": source_project,
            "chat": source_chat,
            "exists": exists,
            "strict_linking": (target / "linked-chats.md").is_file(),
            "chat_path": str(target),
            "sync_path": str(target / "sync.md"),
            "context_path": str(target / "context.md"),
            "links_path": str(target / "links.md"),
        }
    )


def cmd_write(args: argparse.Namespace) -> None:
    ctx = ensure_repository()
    source_project, source_chat = canonical_names(args.project, args.chat)
    assert_canonical_writer(args.current_project, args.current_chat, source_project, source_chat)
    staged = [Path(args.sync_file).resolve(), Path(args.context_file).resolve(), Path(args.links_file).resolve()]
    validate_state_inputs(staged)
    artifacts = [Path(item).resolve() for item in args.artifact]
    for artifact in artifacts:
        validate_artifact(artifact)

    target = chat_path(ctx.path, source_project, source_chat)
    linked_path = target / "linked-chats.md"
    thread_id: str | None = None
    link_changed = False
    if linked_path.exists():
        thread_id = get_thread_id(args.thread_id, required=True)
        authorize_strict(linked_path, thread_id, write=True)
    elif args.enable_linking:
        thread_id = get_thread_id(args.thread_id, required=True)
        current_project, current_chat = canonical_names(args.current_project, args.current_chat)
        record = LinkRecord(thread_id, "source", current_project, current_chat, socket.gethostname())
        write_link_records(linked_path, [record])
        link_changed = True

    target.mkdir(parents=True, exist_ok=True)
    destinations = [target / "sync.md", target / "context.md", target / "links.md"]
    for source, destination in zip(staged, destinations):
        shutil.copyfile(source, destination)
    artifacts_dir = target / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    keep = artifacts_dir / ".gitkeep"
    if not artifacts and not any(artifacts_dir.iterdir()):
        keep.write_text("", encoding="utf-8")
    copied_artifacts: list[Path] = []
    for artifact in artifacts:
        destination = artifacts_dir / safe_name(artifact.name, "chat")
        shutil.copyfile(artifact, destination)
        copied_artifacts.append(destination)
    changed_paths = [target]
    changed, commit = commit_and_push(ctx.path, changed_paths, f"Sync {source_project} / {source_chat}")
    emit(
        {
            "ok": True,
            "repository": ctx.full_name,
            "saved_path": relative_posix(target, ctx.path),
            "strict_linking": linked_path.exists(),
            "link_initialized": link_changed,
            "artifacts": [item.name for item in copied_artifacts],
            "changed": changed,
            "commit": commit,
        }
    )


def cmd_restore(args: argparse.Namespace) -> None:
    ctx = ensure_repository()
    source_project, source_chat = resolve_restore_target(args, ctx.path)
    target = chat_path(ctx.path, source_project, source_chat)
    sync_path = target / "sync.md"
    links_path = target / "links.md"
    context_path = target / "context.md"
    if not sync_path.is_file() or not links_path.is_file() or not context_path.is_file():
        raise SyncError(f"Saved chat is missing required state files: {source_project} / {source_chat}")
    linked_path = target / "linked-chats.md"
    authorization = "open"
    role: str | None = None
    if linked_path.exists():
        thread_id = get_thread_id(args.thread_id, required=True)
        record = authorize_strict(linked_path, thread_id, write=False)
        authorization = "strict"
        role = record.role
    emit(
        {
            "ok": True,
            "repository": ctx.full_name,
            "project": source_project,
            "chat": source_chat,
            "authorization": authorization,
            "role": role,
            "sync_path": str(sync_path),
            "links_path": str(links_path),
            "context_path": str(context_path),
            "artifacts_path": str(target / "artifacts"),
            "sync_text": read_safe_text(sync_path),
            "links_text": read_safe_text(links_path),
            "note": "Read context_path selectively only if the compact checkpoint is insufficient.",
        }
    )


def cmd_link(args: argparse.Namespace) -> None:
    ctx = ensure_repository()
    source_project, source_chat = canonical_names(args.project, args.chat)
    target = chat_path(ctx.path, source_project, source_chat)
    if not (target / "sync.md").is_file():
        raise SyncError(f"Cannot link a missing saved chat: {source_project} / {source_chat}")
    thread_id = get_thread_id(args.thread_id, required=True)
    current_project, current_chat = canonical_names(args.current_project, args.current_chat)
    role = computed_role(current_project, current_chat, source_project, source_chat)
    record = LinkRecord(thread_id, role, current_project, current_chat, socket.gethostname())
    local_marker: Path | None = None
    if role == "consumer":
        if not args.project_root:
            raise SyncError("Cross-project consumer links require --project-root so linked-with.md can be created locally.")
        local_marker = marker_path(args.project_root)
        prepare_marker(local_marker, source_project, source_chat, args.replace_marker)

    linked_path = target / "linked-chats.md"
    records = parse_link_records(linked_path)
    records = [item for item in records if item.thread != thread_id]
    records.append(record)
    write_link_records(linked_path, records)
    changed, commit = commit_and_push(ctx.path, [linked_path], f"Link thread to {source_project} / {source_chat}")

    if local_marker:
        atomic_write(local_marker, marker_text(ctx, source_project, source_chat, record))
    emit(
        {
            "ok": True,
            "repository": ctx.full_name,
            "project": source_project,
            "chat": source_chat,
            "thread": thread_id,
            "role": role,
            "permissions": ["restore", "sync"] if role == "source" else ["restore"],
            "local_marker": str(local_marker) if local_marker else None,
            "changed": changed,
            "commit": commit,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Private GitHub-backed state transport for the codex-sync skill. Outputs JSON on stdout and diagnostics on stderr."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check Git, GitHub CLI, authentication, and thread-ID availability")
    doctor.set_defaults(func=cmd_doctor)

    bootstrap = subparsers.add_parser("bootstrap", help="Create/verify the private state repository and stable local clone")
    bootstrap.set_defaults(func=cmd_bootstrap)

    list_parser = subparsers.add_parser("list", help="List human-readable saved projects and chats")
    list_parser.add_argument("--project", help="Optional normalized project filter")
    list_parser.set_defaults(func=cmd_list)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect paths and strict-mode status for one canonical saved chat")
    inspect_parser.add_argument("--project", required=True)
    inspect_parser.add_argument("--chat", required=True)
    inspect_parser.set_defaults(func=cmd_inspect)

    write = subparsers.add_parser("write", help="Authorize, validate, commit, and push a canonical chat sync")
    write.add_argument("--project", required=True, help="Canonical source project")
    write.add_argument("--chat", required=True, help="Canonical source chat")
    write.add_argument("--current-project", required=True)
    write.add_argument("--current-chat", required=True)
    write.add_argument("--sync-file", required=True)
    write.add_argument("--context-file", required=True)
    write.add_argument("--links-file", required=True)
    write.add_argument("--artifact", action="append", default=[])
    write.add_argument("--enable-linking", action="store_true")
    write.add_argument("--thread-id", help=argparse.SUPPRESS)
    write.set_defaults(func=cmd_write)

    restore = subparsers.add_parser("restore", help="Authorize read-only restore and return compact state paths/content")
    restore.add_argument("--project")
    restore.add_argument("--chat")
    restore.add_argument("--current-project", required=True)
    restore.add_argument("--current-chat", required=True)
    restore.add_argument("--project-root")
    restore.add_argument("--thread-id", help=argparse.SUPPRESS)
    restore.set_defaults(func=cmd_restore)

    link = subparsers.add_parser("link", help="Link the current thread as a computed source or restore-only consumer")
    link.add_argument("--project", required=True, help="Canonical source project")
    link.add_argument("--chat", required=True, help="Canonical source chat")
    link.add_argument("--current-project", required=True)
    link.add_argument("--current-chat", required=True)
    link.add_argument("--project-root")
    link.add_argument("--replace-marker", action="store_true")
    link.add_argument("--thread-id", help=argparse.SUPPRESS)
    link.set_defaults(func=cmd_link)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except SyncError as exc:
        print(f"codex-sync: {redact(str(exc))}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("codex-sync: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
