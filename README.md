# codex-agy

A local MCP bridge for running a two-agent engineering workflow:

- **Codex** acts as the senior engineer, architect, reviewer, and integration authority.
- **Google Antigravity (agy)** acts as the implementation worker.
- **codex-agy** connects them through MCP, isolates implementation in Git worktrees, records worker state, and enforces safety/integrity checks.

The bridge does not require a Gemini API key. Codex uses its normal OpenAI login. Antigravity uses the Google-account login cached by the official agy CLI.

> Experimental developer tooling. Review the code and local permissions before using it on important repositories.

## Architecture

~~~text
Human / product owner
        |
        v
      Codex
senior / reviewer
        |
        | MCP stdio
        v
    codex-agy
   Python bridge
        |
        | create Git worktree
        | launch agy headlessly
        v
  Antigravity / agy
 implementation worker
        |
        | edit + test
        v
   ag/<ticket>
   worker branch
        |
        v
      Codex
   review + verify
      /      \
   reject    accept
     |          |
 fix_review     integrate
     |
 same agy conversation
~~~

## Authority model

| Role | Responsibility |
| --- | --- |
| Human | Product/design authority and subjective acceptance |
| Codex | Architecture, ticket validation, review, independent verification, integration decision |
| Antigravity | Implementation, debugging, permitted verification, review fixes |
| Bridge | Worktree isolation, worker invocation, state tracking, Git bookkeeping, integrity checks |

Antigravity never approves, merges, pushes, or marks its own implementation accepted.

## Why worktrees?

Codex and Antigravity should not mutate the same checkout.

For ticket P3-001:

~~~text
Primary checkout
/home/you/workspace/project
    ^
    | Codex reviews here

Worker checkout
~/.local/state/codex-agy/<repo-id>/worktrees/P3-001
    ^
    | agy edits here

Worker branch
ag/P3-001
~~~

The worker branch begins at the primary checkout's current HEAD. Commit the ticket and any context the worker needs before delegation.

## Safety invariants

The current pipeline deliberately uses defense in depth:

1. A dedicated Git worktree for every delegated ticket.
2. Antigravity runs with the terminal sandbox enabled.
3. The bridge never uses --dangerously-skip-permissions.
4. The agy process does not inherit AG_WORKSPACE or Git-routing environment variables.
5. The worker prompt forbids locating or editing another checkout.
6. The bridge fingerprints the primary checkout before and after agy runs.
7. Any primary-checkout mutation during a worker run rejects the result.
8. A completed worker report with no worktree changes is rejected.
9. The worker's files_changed report must match Git-visible changed paths.
10. The bridge, not Antigravity, performs the worker commit.

This intentionally favors false positives over silently accepting an escaped write.

## MCP tools

The server exposes:

- **ping()** — simple MCP connectivity test.
- **diagnose()** — validate workspace, Git, agy binary, and state directory.
- **implement_ticket(ticket_id, ticket_path)** — delegate a committed ticket in an isolated worktree.
- **fix_review(ticket_id, review)** — send Codex review feedback back to the same Antigravity conversation.
- **worker_status(ticket_id)** — inspect branch, worktree, head, and saved conversation state.

## Quick start

Full instructions are in [INSTALL.md](INSTALL.md).

~~~bash
git clone https://github.com/rheavenza/codex-agy.git ~/.local/share/codex-agy
cd ~/.local/share/codex-agy
uv sync
chmod +x launch.sh
~~~

Configure Codex in ~/.codex/config.toml:

~~~toml
[mcp_servers.ag_worker]
command = "/home/YOU/.local/share/codex-agy/launch.sh"
env = { AG_WORKSPACE = "/absolute/path/to/your/project" }
startup_timeout_sec = 30
tool_timeout_sec = 2400
~~~

Restart Codex and test:

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

## Normal engineering loop

~~~text
READY ticket committed
        |
        v
Codex inspects ticket + architecture
        |
        v
implement_ticket()
        |
        v
agy implements in isolated worktree
        |
        v
bridge validates result + commits worker branch
        |
        v
Codex reviews complete base_sha..head_sha diff
        |
        +-- reruns important verification
        +-- checks acceptance criteria
        +-- checks unrelated changes
        |
      issues?
      /    \
    yes     no
     |       |
fix_review   technically acceptable
     |       |
     +-------+
             |
       integrate / playtest gate
~~~

The worker report is evidence, not proof. Codex should independently verify important claims.

For gameplay feel, visuals, animation, UX, level design, narrative feel, or similar subjective work, stop at a human playtest gate rather than treating automated success as final acceptance.

## Ticket contract

Delegation works best when tickets contain:

- objective;
- read-first references;
- allowed scope;
- dependencies;
- required behavior;
- API/data constraints;
- acceptance criteria;
- verification;
- explicit out-of-scope items.

Example Codex instruction:

~~~text
Act as senior engineer.

Review docs/tickets/P3-001.md.
Do not implement the ticket yourself.

If the ticket is valid, delegate it through the ag_worker MCP implementation worker.

After the worker returns:
1. inspect the complete base_sha..head_sha diff,
2. independently run important verification,
3. verify every acceptance criterion,
4. reject unrelated changes,
5. send precise review feedback through fix_review if needed.

Do not merge until technically acceptable.
~~~

## Authentication

The bridge does not extract or reuse Antigravity OAuth tokens.

1. Authenticate Codex normally.
2. Run agy interactively once.
3. Sign in with your Google account.
4. Verify headless agy works.
5. The bridge launches the official agy process, which uses its own cached credentials.

## Repository layout

~~~text
codex-agy/
├── README.md
├── INSTALL.md
├── PIPELINE.md
├── pyproject.toml
├── server.py
├── launch.sh
├── .gitignore
└── examples/
    ├── codex-config.toml
    ├── antigravity-settings.json
    └── AGENTS-snippet.md
~~~

## Troubleshooting

### No such file or directory (os error 2)

Codex cannot launch the configured MCP command.

~~~bash
ls -l ~/.local/share/codex-agy/launch.sh
chmod +x ~/.local/share/codex-agy/launch.sh
~~~

Use an absolute command path in Codex config.

### connection closed: initialize response

The MCP process started and crashed before completing startup.

~~~bash
AG_WORKSPACE=/absolute/path/to/project ~/.local/share/codex-agy/launch.sh
~~~

Also verify:

~~~bash
cd ~/.local/share/codex-agy
uv sync
uv run python -c 'import mcp; print(mcp)'
~~~

### Duplicate MCP namespace

Do not register the same bridge both globally and project-locally. A unique MCP server id such as ag_worker is recommended.

### Worker says completed but the branch has no changes

Do not bypass the guard. Check Antigravity workspace and permission configuration.

### Primary checkout changed during worker execution

The bridge rejects the run. Confirm that non-workspace access is disabled, dangerous permission bypass is not used, nobody edited the primary checkout during the run, and the worker was not given an absolute path to the live checkout.

## Current limitations

- Local Git repositories only.
- One worker invocation is serialized at a time.
- The bridge does not merge or push.
- Worktree cleanup is manual.
- A new ticket worktree starts from committed HEAD, not uncommitted primary-checkout changes.
- Actual sandbox semantics depend on the installed Antigravity release.
- The primary-checkout guard detects mutation; it does not prove a process never read external data.

## Upstream references

- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Codex configuration: https://developers.openai.com/codex/config-reference/
- Antigravity headless CLI: https://antigravity.google/docs/cli/headless/
- Antigravity CLI reference: https://antigravity.google/docs/cli/reference/
- Antigravity permissions: https://antigravity.google/docs/cli-permissions
- Antigravity sandbox: https://antigravity.google/docs/sandbox?tab=cli

## License

No license has been selected yet.
