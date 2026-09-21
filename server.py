from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mcp.server import MCPServer


mcp = MCPServer("codex-agy")
WORKER_LOCK = asyncio.Lock()

AGY_BIN = (
    os.environ.get("AGY_BIN")
    or shutil.which("agy")
    or str(Path.home() / ".local/bin/agy")
)


def git(*args: str, cwd: Path, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd}\n{result.stderr}"
        )
    return result.stdout.strip()


def workspace() -> Path:
    raw = os.environ.get("AG_WORKSPACE")
    if not raw:
        raise RuntimeError("AG_WORKSPACE is not configured")

    repo = Path(raw).expanduser().resolve()
    if not repo.exists():
        raise RuntimeError(f"AG_WORKSPACE does not exist: {repo}")

    toplevel = Path(
        git("rev-parse", "--show-toplevel", cwd=repo)
    ).resolve()

    if toplevel != repo:
        raise RuntimeError(
            f"AG_WORKSPACE must point at the Git repository root: {toplevel}"
        )

    return repo


def repo_id(repo: Path) -> str:
    return hashlib.sha256(str(repo).encode()).hexdigest()[:16]


def state_root(repo: Path) -> Path:
    root = (
        Path.home()
        / ".local"
        / "state"
        / "codex-agy"
        / repo_id(repo)
    )
    (root / "worktrees").mkdir(parents=True, exist_ok=True)
    (root / "tasks").mkdir(parents=True, exist_ok=True)
    return root


def sanitize_ticket(ticket_id: str) -> str:
    value = re.sub(
        r"[^A-Za-z0-9._-]+",
        "-",
        ticket_id,
    ).strip("-")

    if not value:
        raise ValueError("invalid ticket id")

    return value


def state_path(repo: Path, ticket_id: str) -> Path:
    return (
        state_root(repo)
        / "tasks"
        / f"{sanitize_ticket(ticket_id)}.json"
    )


def load_state(
    repo: Path,
    ticket_id: str,
) -> dict[str, Any]:
    path = state_path(repo, ticket_id)

    if not path.exists():
        raise RuntimeError(
            f"no worker state for {ticket_id}"
        )

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def save_state(
    repo: Path,
    ticket_id: str,
    state: dict[str, Any],
) -> None:
    state_path(repo, ticket_id).write_text(
        json.dumps(state, indent=2) + "\n",
        encoding="utf-8",
    )


def create_worktree(
    repo: Path,
    ticket_id: str,
) -> dict[str, Any]:
    path = state_path(repo, ticket_id)

    if path.exists():
        return load_state(repo, ticket_id)

    ticket = sanitize_ticket(ticket_id)
    branch = f"ag/{ticket}"
    worktree = (
        state_root(repo)
        / "worktrees"
        / ticket
    ).resolve()

    base_sha = git(
        "rev-parse",
        "HEAD",
        cwd=repo,
    )

    if git(
        "branch",
        "--list",
        branch,
        cwd=repo,
    ):
        raise RuntimeError(
            f"worker branch already exists: {branch}"
        )

    git(
        "worktree",
        "add",
        "-b",
        branch,
        str(worktree),
        base_sha,
        cwd=repo,
    )

    state = {
        "ticket_id": ticket_id,
        "branch": branch,
        "worktree": str(worktree),
        "base_sha": base_sha,
        "head_sha": None,
        "conversation_id": None,
    }

    save_state(repo, ticket_id, state)
    return state


def run_bytes(
    args: list[str],
    cwd: Path,
) -> bytes:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

    return result.stdout


def hash_path(path: Path) -> str:
    h = hashlib.sha256()

    if path.is_symlink():
        h.update(
            os.readlink(path).encode(
                "utf-8",
                errors="surrogateescape",
            )
        )
        return h.hexdigest()

    if not path.exists():
        return "<missing>"

    if path.is_dir():
        return "<directory>"

    with path.open("rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


def checkout_snapshot(
    repo: Path,
) -> dict[str, Any]:
    tracked_diff = run_bytes(
        [
            "git",
            "diff",
            "--binary",
            "HEAD",
            "--",
        ],
        repo,
    )

    staged_diff = run_bytes(
        [
            "git",
            "diff",
            "--cached",
            "--binary",
            "HEAD",
            "--",
        ],
        repo,
    )

    untracked_raw = run_bytes(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        repo,
    )

    untracked = sorted(
        value.decode(
            "utf-8",
            errors="surrogateescape",
        )
        for value in untracked_raw.split(b"\0")
        if value
    )

    h = hashlib.sha256()
    h.update(tracked_diff)
    h.update(staged_diff)

    hashes: dict[str, str] = {}

    for relative in untracked:
        digest = hash_path(repo / relative)
        hashes[relative] = digest

        h.update(
            relative.encode(
                "utf-8",
                errors="surrogateescape",
            )
        )
        h.update(b"\0")
        h.update(digest.encode())
        h.update(b"\0")

    return {
        "fingerprint": h.hexdigest(),
        "untracked": untracked,
        "untracked_hashes": hashes,
    }


def assert_live_checkout_unchanged(
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    if before["fingerprint"] != after["fingerprint"]:
        raise RuntimeError(
            "SAFETY VIOLATION: primary checkout changed "
            "while Antigravity was running. "
            "Worker result rejected; no worker commit created."
        )


def changed_paths(
    worktree: Path,
) -> list[str]:
    tracked = run_bytes(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            "HEAD",
            "--",
        ],
        worktree,
    )

    staged = run_bytes(
        [
            "git",
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "HEAD",
            "--",
        ],
        worktree,
    )

    untracked = run_bytes(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        worktree,
    )

    result: set[str] = set()

    for raw in (
        tracked.split(b"\0")
        + staged.split(b"\0")
        + untracked.split(b"\0")
    ):
        if raw:
            result.add(
                raw.decode(
                    "utf-8",
                    errors="surrogateescape",
                )
            )

    return sorted(result)


def normalize_reported_paths(
    paths: list[str],
) -> list[str]:
    normalized: set[str] = set()

    for value in paths:
        path = Path(value)

        if (
            path.is_absolute()
            or ".." in path.parts
        ):
            raise RuntimeError(
                f"worker reported unsafe file path: {value}"
            )

        normalized.add(path.as_posix())

    return sorted(normalized)


def commit_changes(
    state: dict[str, Any],
    message: str,
) -> str:
    worktree = Path(state["worktree"])

    if not git(
        "status",
        "--porcelain",
        cwd=worktree,
    ):
        return git(
            "rev-parse",
            "HEAD",
            cwd=worktree,
        )

    git(
        "add",
        "-A",
        cwd=worktree,
    )

    git(
        "commit",
        "-m",
        message,
        cwd=worktree,
    )

    return git(
        "rev-parse",
        "HEAD",
        cwd=worktree,
    )


WORKER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "completed",
                "blocked",
                "failed",
            ],
        },
        "summary": {
            "type": "string",
        },
        "files_changed": {
            "type": "array",
            "items": {"type": "string"},
        },
        "tests_run": {
            "type": "array",
            "items": {"type": "string"},
        },
        "tests_passed": {
            "type": "array",
            "items": {"type": "string"},
        },
        "tests_failed": {
            "type": "array",
            "items": {"type": "string"},
        },
        "architectural_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "known_limitations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "follow_up_items": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "status",
        "summary",
        "files_changed",
        "tests_run",
        "tests_passed",
        "tests_failed",
        "architectural_notes",
        "known_limitations",
        "follow_up_items",
    ],
    "additionalProperties": False,
}


WORKER_RULES = """
You are the implementation engineer.
Codex is the senior engineer and reviewer.

WORKSPACE SECURITY CONTRACT:
- The current working directory is your entire allowed project workspace.
- Use workspace-relative paths only.
- Never access, locate, or modify another checkout of this repository.
- Never inspect environment variables to discover another project root.
- Never follow Git worktree metadata to locate the primary checkout.
- Do not use Git commands. The orchestration bridge owns Git bookkeeping.
- If required material is unavailable inside this workspace, report BLOCKED.

ENGINEERING AUTHORITY:
- Codex owns architecture, scope, acceptance, and review.
- You own implementation of the assigned ticket only.
- Do not broaden scope.
- Do not redesign unrelated systems.
- Do not push or merge.
- Do not approve or mark the ticket DONE/ACCEPTED.
- Run appropriate permitted verification.
- Report failures and limitations accurately.
- Every files_changed entry must be a workspace-relative path.
"""


async def call_agy(
    worktree: Path,
    prompt: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    schema = json.dumps(
        WORKER_SCHEMA,
        separators=(",", ":"),
    )

    command = [
        AGY_BIN,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--json-schema",
        schema,
        "--sandbox",
        "--print-timeout",
        "30m",
    ]

    if conversation_id:
        command.extend(
            [
                "--conversation",
                conversation_id,
            ]
        )

    child_env = os.environ.copy()

    for key in (
        "AG_WORKSPACE",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "OLDPWD",
    ):
        child_env.pop(key, None)

    child_env["PWD"] = str(worktree)

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=worktree,
        env=child_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    stdout_text = stdout.decode(
        "utf-8",
        errors="replace",
    )

    stderr_text = stderr.decode(
        "utf-8",
        errors="replace",
    )

    if process.returncode != 0:
        raise RuntimeError(
            f"agy failed ({process.returncode})\n"
            f"STDOUT:\n{stdout_text}\n"
            f"STDERR:\n{stderr_text}"
        )

    try:
        envelope = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "agy returned non-JSON output\n"
            f"STDOUT:\n{stdout_text}\n"
            f"STDERR:\n{stderr_text}"
        ) from exc

    if envelope.get("status") != "SUCCESS":
        raise RuntimeError(
            "agy did not finish successfully\n"
            f"status={envelope.get('status')}\n"
            f"error={envelope.get('error', '')}\n"
            f"STDERR:\n{stderr_text}"
        )

    return envelope


def extract_report(
    envelope: dict[str, Any],
) -> dict[str, Any]:
    report = envelope.get("structured_output")

    if not isinstance(report, dict):
        response = envelope.get("response")

        if isinstance(response, str):
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                parsed = None

            if isinstance(parsed, dict):
                report = parsed

    if not isinstance(report, dict):
        raise RuntimeError(
            "agy response did not contain structured_output. "
            "Check the installed agy JSON/schema support."
        )

    return report


def validate_worker_result(
    report: dict[str, Any],
    worktree: Path,
) -> list[str]:
    actual = changed_paths(worktree)

    reported = normalize_reported_paths(
        report.get(
            "files_changed",
            [],
        )
    )

    if (
        report.get("status") == "completed"
        and not actual
    ):
        raise RuntimeError(
            "WORKER INTEGRITY FAILURE: worker reported "
            "completed but isolated worktree contains no changes"
        )

    if reported != actual:
        raise RuntimeError(
            "WORKER INTEGRITY FAILURE: "
            "files_changed does not match Git\n"
            f"reported={reported}\n"
            f"actual={actual}"
        )

    return actual


@mcp.tool()
def ping() -> str:
    """Verify Codex-to-MCP connectivity."""
    return "pong"


@mcp.tool()
def diagnose() -> dict[str, Any]:
    """Validate workspace, Git, agy, and bridge state paths."""
    repo = workspace()

    agy_exists = (
        Path(AGY_BIN).exists()
        if "/" in AGY_BIN
        else shutil.which(AGY_BIN) is not None
    )

    return {
        "workspace": str(repo),
        "git_toplevel": git(
            "rev-parse",
            "--show-toplevel",
            cwd=repo,
        ),
        "head": git(
            "rev-parse",
            "HEAD",
            cwd=repo,
        ),
        "agy_binary": AGY_BIN,
        "agy_exists": agy_exists,
        "state_root": str(state_root(repo)),
    }


@mcp.tool()
async def implement_ticket(
    ticket_id: str,
    ticket_path: str,
) -> dict[str, Any]:
    """Delegate one committed engineering ticket to Antigravity."""
    async with WORKER_LOCK:
        repo = workspace()

        state = create_worktree(
            repo,
            ticket_id,
        )

        worktree = Path(
            state["worktree"]
        )

        ticket_file = (
            worktree / ticket_path
        ).resolve()

        if not ticket_file.is_relative_to(
            worktree
        ):
            raise ValueError(
                "ticket_path escapes worker workspace"
            )

        if not ticket_file.exists():
            raise FileNotFoundError(ticket_path)

        ticket = ticket_file.read_text(
            encoding="utf-8"
        )

        prompt = f"""
{WORKER_RULES}

TICKET ID:
{ticket_id}

TICKET FILE:
{ticket_path}

--- TICKET ---
{ticket}
--- END TICKET ---

Before editing:
1. Read applicable AGENTS.md files.
2. Read only the documentation required by the ticket.
3. Inspect the existing implementation and tests.
4. Implement only the allowed scope.
5. Run appropriate permitted verification.

Return the required structured implementation report.
"""

        live_before = checkout_snapshot(repo)

        envelope = await call_agy(
            worktree,
            prompt,
        )

        live_after = checkout_snapshot(repo)

        assert_live_checkout_unchanged(
            live_before,
            live_after,
        )

        report = extract_report(envelope)

        actual_files = validate_worker_result(
            report,
            worktree,
        )

        head_sha = commit_changes(
            state,
            f"agent({ticket_id}): implementation",
        )

        if (
            report.get("status") == "completed"
            and head_sha == state["base_sha"]
        ):
            raise RuntimeError(
                "WORKER INTEGRITY FAILURE: "
                "completed implementation produced no worker commit"
            )

        state["conversation_id"] = envelope.get(
            "conversation_id"
        )

        state["head_sha"] = head_sha

        save_state(
            repo,
            ticket_id,
            state,
        )

        return {
            "ticket_id": ticket_id,
            "worker_status": report.get("status"),
            "branch": state["branch"],
            "worktree": state["worktree"],
            "base_sha": state["base_sha"],
            "head_sha": head_sha,
            "conversation_id": state[
                "conversation_id"
            ],
            "actual_files_changed": actual_files,
            "diff_stat": git(
                "diff",
                "--stat",
                f"{state['base_sha']}..{head_sha}",
                cwd=worktree,
            ),
            "worker_report": report,
            "review_required": True,
        }


@mcp.tool()
async def fix_review(
    ticket_id: str,
    review: str,
) -> dict[str, Any]:
    """Send Codex review findings to the same Antigravity conversation."""
    async with WORKER_LOCK:
        repo = workspace()

        state = load_state(
            repo,
            ticket_id,
        )

        worktree = Path(
            state["worktree"]
        )

        conversation_id = state.get(
            "conversation_id"
        )

        if not conversation_id:
            raise RuntimeError(
                "ticket has no saved Antigravity conversation id"
            )

        previous_head = git(
            "rev-parse",
            "HEAD",
            cwd=worktree,
        )

        prompt = f"""
{WORKER_RULES}

Codex reviewed ticket {ticket_id}.

--- CODEX REVIEW ---
{review}
--- END REVIEW ---

Address every BLOCKING and REQUIRED item.
Do not broaden scope.
Run appropriate permitted verification again.
Return the required structured implementation report.
"""

        live_before = checkout_snapshot(repo)

        envelope = await call_agy(
            worktree,
            prompt,
            conversation_id=conversation_id,
        )

        live_after = checkout_snapshot(repo)

        assert_live_checkout_unchanged(
            live_before,
            live_after,
        )

        report = extract_report(envelope)

        actual_files = validate_worker_result(
            report,
            worktree,
        )

        head_sha = commit_changes(
            state,
            f"agent({ticket_id}): address review",
        )

        if head_sha == previous_head:
            raise RuntimeError(
                "WORKER INTEGRITY FAILURE: "
                "review fix produced no new worker commit"
            )

        state["head_sha"] = head_sha

        save_state(
            repo,
            ticket_id,
            state,
        )

        return {
            "ticket_id": ticket_id,
            "worker_status": report.get("status"),
            "branch": state["branch"],
            "worktree": state["worktree"],
            "base_sha": state["base_sha"],
            "head_sha": head_sha,
            "actual_files_changed": actual_files,
            "diff_stat": git(
                "diff",
                "--stat",
                f"{state['base_sha']}..{head_sha}",
                cwd=worktree,
            ),
            "worker_report": report,
            "review_required": True,
        }


@mcp.tool()
def worker_status(
    ticket_id: str,
) -> dict[str, Any]:
    """Return stored worker state plus current Git status."""
    repo = workspace()

    state = load_state(
        repo,
        ticket_id,
    )

    worktree = Path(
        state["worktree"]
    )

    return {
        **state,
        "current_head": git(
            "rev-parse",
            "HEAD",
            cwd=worktree,
        ),
        "working_tree_clean": (
            git(
                "status",
                "--porcelain",
                cwd=worktree,
            )
            == ""
        ),
    }


if __name__ == "__main__":
    mcp.run()
