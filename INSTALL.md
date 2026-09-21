# Installation Guide

This guide installs the complete local pipeline:

~~~text
Codex -> MCP -> codex-agy -> agy -> isolated Git worktree
~~~

The examples assume Linux.

## 1. Install prerequisites

You need:

- Git
- Python 3.11 or newer
- uv
- OpenAI Codex CLI
- Google Antigravity CLI (agy)

On Arch/CachyOS, install the base tools with:

~~~bash
sudo pacman -S --needed git python uv
~~~

Verify:

~~~bash
git --version
python --version
uv --version
codex --version
agy --version
~~~

## 2. Authenticate Codex

Use Codex's normal account login:

~~~bash
codex
~~~

Confirm a normal Codex session works before configuring MCP.

## 3. Authenticate Antigravity

Run agy interactively:

~~~bash
agy
~~~

Sign in with your Google account.

Headless mode uses cached credentials, so verify:

~~~bash
agy -p "Reply with exactly ANTIGRAVITY_OK"
~~~

Expected:

~~~text
ANTIGRAVITY_OK
~~~

Then verify machine-readable output:

~~~bash
agy -p "Reply with exactly ANTIGRAVITY_OK" --output-format json
~~~

The bridge uses headless JSON output, JSON-schema constrained output, conversation IDs, sandbox mode, and a 30-minute print timeout.

## 4. Configure Antigravity isolation

Antigravity's current CLI settings support:

- enableTerminalSandbox
- toolPermission
- allowNonWorkspaceAccess
- fine-grained permission allow/deny rules

Use the example at examples/antigravity-settings.json as a starting point.

The core settings are:

~~~json
{
  "enableTerminalSandbox": true,
  "toolPermission": "proceed-in-sandbox",
  "allowNonWorkspaceAccess": false
}
~~~

Do not use:

~~~text
--dangerously-skip-permissions
~~~

Headless file access inside the active workspace is allowed by Antigravity; shell commands should be explicitly allowed only when needed.

The sample configuration denies Git to the worker because the bridge owns worker Git bookkeeping.

Adjust the allow-list for your project. Examples:

~~~text
Godot:
command(godot --headless)

Node:
command(npm test)
command(npm run lint)
command(npm run typecheck)
command(npm run build)
~~~

If your test command is not allowed in headless mode, Antigravity can soft-deny it. Codex must treat a missing required verification run as a review failure rather than assuming success.

## 5. Clone the bridge

~~~bash
mkdir -p ~/.local/share
git clone https://github.com/rheavenza/codex-agy.git ~/.local/share/codex-agy
cd ~/.local/share/codex-agy
~~~

Install Python dependencies:

~~~bash
uv sync
~~~

Make the launcher executable:

~~~bash
chmod +x launch.sh
~~~

The project uses the current MCP Python SDK v2 API and MCPServer.

## 6. Test the MCP server manually

Choose the project Codex will manage.

Example:

~~~text
/home/rhea/workspace/CROWNLESS
~~~

Run:

~~~bash
AG_WORKSPACE=/home/rhea/workspace/CROWNLESS   ~/.local/share/codex-agy/launch.sh
~~~

For an stdio MCP server, silently waiting for input is normal. Press Ctrl+C after confirming it stays alive.

If it crashes, run:

~~~bash
cd ~/.local/share/codex-agy
uv sync
uv run python server.py
~~~

## 7. Configure Codex

Edit:

~~~text
~/.codex/config.toml
~~~

Add:

~~~toml
[mcp_servers.ag_worker]
command = "/home/YOU/.local/share/codex-agy/launch.sh"
env = { AG_WORKSPACE = "/absolute/path/to/your/project" }
startup_timeout_sec = 30
tool_timeout_sec = 2400
~~~

For CROWNLESS, the concrete example is:

~~~toml
[mcp_servers.ag_worker]
command = "/home/rhea/.local/share/codex-agy/launch.sh"
env = { AG_WORKSPACE = "/home/rhea/workspace/CROWNLESS" }
startup_timeout_sec = 30
tool_timeout_sec = 2400
~~~

Use absolute paths.

Restart Codex completely after changing MCP configuration.

## 8. Test Codex -> MCP

Start a fresh Codex session in your project:

~~~bash
cd /absolute/path/to/project
codex
~~~

Ask:

~~~text
Call the ag_worker ping tool.
~~~

Expected:

~~~text
pong
~~~

Then:

~~~text
Call ag_worker diagnose and summarize the result.
~~~

A healthy diagnostic should identify:

- the configured repository;
- the repository HEAD;
- the agy executable;
- agy_exists = true;
- the bridge state directory.

Do not delegate real work until ping and diagnose are healthy.

## 9. Add the authority contract to the project

Copy or adapt examples/AGENTS-snippet.md into the target repository's AGENTS.md.

The important organizational rule is:

~~~text
Human -> product/design authority
Codex -> senior / reviewer / acceptance
Antigravity -> implementation only
Tests -> deterministic evidence
~~~

Antigravity must not accept its own work.

## 10. Create a smoke-test ticket

Create a deliberately tiny ticket in the target project:

~~~markdown
# MCP-SMOKE

## Goal

Verify Codex can delegate a repository modification to Antigravity.

## Scope

Create docs/antigravity-mcp-smoke.md containing exactly:

Antigravity MCP worker operational.

## Non-goals

Do not modify any other file.

## Acceptance criteria

- File exists on the isolated worker branch.
- Exact text exists.
- No unrelated files changed.
~~~

Commit the ticket before delegation:

~~~bash
git add docs/tickets/MCP-SMOKE.md
git commit -m "test: add MCP smoke ticket"
~~~

## 11. Delegate through Codex

Use:

~~~text
Act as senior engineer.

Review docs/tickets/MCP-SMOKE.md.

Do not implement the ticket yourself.

If the ticket is valid, delegate it through the ag_worker MCP implementation worker.

When Antigravity finishes:
1. inspect the complete diff,
2. verify every acceptance criterion independently,
3. reject unrelated changes,
4. confirm the primary checkout was not modified by the worker,
5. report whether the implementation is technically acceptable.

Do not merge yet.
~~~

A successful run should look conceptually like:

~~~text
primary checkout
unchanged

worker branch
ag/MCP-SMOKE

base_sha
old commit

head_sha
new worker commit

diff
docs/antigravity-mcp-smoke.md | 1 +
~~~

## 12. Test the review loop

If Codex finds a problem, it should call:

~~~text
fix_review(ticket_id, review)
~~~

The bridge saves Antigravity's conversation_id from the original run and resumes that exact conversation with --conversation.

After each fix, Codex must review the entire ticket diff again rather than trusting the worker report.

## 13. Integration policy

Do not expose a merge MCP tool to Antigravity.

Keep the boundary:

~~~text
Antigravity
  edit + test
       |
       v
bridge
  validate + worker commit
       |
       v
Codex
  review + independent verification
       |
       v
human/Codex
  integration decision
~~~

## 14. Cleaning up worktrees

The bridge currently leaves worktrees in place deliberately.

Inspect:

~~~bash
git worktree list
~~~

After merging or abandoning a ticket:

~~~bash
git worktree remove /path/from/worker_status
git branch -d ag/TICKET-ID
git worktree prune
~~~

Use branch -D only when intentionally discarding unmerged work.

The bridge state is under:

~~~text
~/.local/state/codex-agy/<repo-id>/
~~~

## 15. Updating codex-agy

~~~bash
cd ~/.local/share/codex-agy
git pull
uv sync
~~~

Restart Codex after updating the bridge.

## 16. Troubleshooting checklist

If MCP fails to start:

~~~bash
ls -l ~/.local/share/codex-agy/launch.sh
chmod +x ~/.local/share/codex-agy/launch.sh
cd ~/.local/share/codex-agy
uv sync
AG_WORKSPACE=/absolute/path/to/project ./launch.sh
~~~

If Codex reports a duplicate MCP namespace, check both global and project-level Codex configs and register the bridge only once.

If the bridge reports a primary-checkout safety violation, do not bypass it. Fix Antigravity isolation or stop editing the primary checkout while the worker is active.

If the bridge reports completed with no worker changes, inspect Antigravity permissions and active workspace. This guard exists specifically to prevent a worker from mutating the wrong checkout while the review branch remains empty.
