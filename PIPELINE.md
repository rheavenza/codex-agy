# Pipeline Design

## Goal

The pipeline turns Codex into the engineering authority and Antigravity into a bounded implementation worker.

The central invariant is:

> The agent that implements a ticket does not approve or integrate that ticket.

## States

A practical project board can use:

~~~text
BACKLOG
  ->
READY
  ->
ACTIVE
  ->
CODE_REVIEW
  ->
READY_FOR_PLAYTEST
  ->
DONE
~~~

READY_FOR_PLAYTEST is optional for purely technical tasks and recommended for subjective gameplay, visual, UX, animation, level-design, or narrative work.

## Ticket start

Codex reads the ticket and relevant architecture first.

Before delegation Codex should confirm:

- the ticket is actually READY;
- scope is bounded;
- dependencies exist;
- acceptance criteria are testable;
- required verification is listed;
- the ticket is committed to HEAD.

Codex then calls implement_ticket.

## Delegation

The bridge:

1. Records the primary HEAD as base_sha.
2. Creates branch ag/<ticket>.
3. Creates a linked worktree under ~/.local/state/codex-agy.
4. Reads the ticket from the worker worktree.
5. Fingerprints the primary checkout.
6. Launches agy with the worker worktree as cwd.
7. Removes AG_WORKSPACE and Git routing variables from the child environment.
8. Uses JSON-schema constrained worker output.
9. Fingerprints the primary checkout again.
10. Rejects the run if the primary checkout changed.
11. Compares files_changed against Git-visible worktree changes.
12. Commits validated changes to the worker branch.
13. Returns base_sha, head_sha, branch, diff_stat, worker report, and conversation_id to Codex.

## Worker contract

Antigravity is told to:

- treat cwd as the complete authorized workspace;
- use workspace-relative paths;
- stay inside ticket scope;
- read applicable AGENTS.md files;
- run permitted verification;
- report failures;
- avoid Git commands;
- never push or merge;
- never declare acceptance.

## Review

Codex should not accept the worker report at face value.

Codex independently:

1. inspects base_sha..head_sha;
2. checks every changed file;
3. checks for unrelated changes;
4. runs important tests itself;
5. verifies acceptance criteria;
6. checks architecture and regressions.

If problems exist, Codex constructs a precise review and calls fix_review.

## Review-fix loop

fix_review resumes the exact Antigravity conversation recorded during implementation.

The bridge repeats the same safety checks, validates the new changed-file report, and creates a new worker commit.

Codex then reviews the full ticket diff again.

This repeats until:

- technically acceptable;
- blocked for a real dependency/design decision;
- or abandoned by the human.

## Integration

Antigravity has no merge function.

Once technically acceptable, Codex or the human integrates the worker branch according to the target project's normal Git/PR policy.

For projects using pull requests, the natural mapping is:

~~~text
Antigravity worker branch
        ->
PR / diff
        ->
Codex review
        ->
human or authorized merge
~~~

## Safety rationale

### Why the primary-checkout fingerprint exists

A worker can accidentally write to the live repository while its isolated branch remains clean. That makes a normal reviewer blind: the branch says nothing changed even though the user's checkout was mutated.

The bridge therefore fingerprints:

- tracked unstaged changes;
- staged changes;
- untracked file paths and content.

If that fingerprint changes while agy is running, the worker result is rejected before the bridge commits anything.

### Why worker files_changed is checked

Structured output is useful but still model-generated.

The bridge treats Git as the source of truth and requires the reported file list to equal the actual changed file list.

### Why Antigravity does not own Git

The implementation agent does not need integration authority.

Keeping Git bookkeeping in the bridge means Antigravity can focus on code while Codex retains review authority.

### Why --dangerously-skip-permissions is prohibited

It removes the exact approval boundary that protects the workstation when an agent chooses a risky tool or path.

Use the sandbox and narrowly-scoped permission rules instead.

## Failure behavior

The bridge should fail loudly when:

- AG_WORKSPACE is invalid;
- a worker branch already exists without matching saved state;
- the ticket path escapes the worktree;
- agy exits non-zero;
- agy does not return SUCCESS;
- structured output is missing;
- the primary checkout mutates;
- a completed worker returns no isolated changes;
- reported changed paths differ from Git;
- a review fix produces no new commit.

A failure is preferable to silently integrating ambiguous work.
