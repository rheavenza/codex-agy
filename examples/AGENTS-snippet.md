# Codex + Antigravity Engineering Workflow

## Authority hierarchy

1. Human — product/design authority
2. Codex — senior engineer / technical lead / reviewer
3. Antigravity — implementation engineer
4. Automated checks — deterministic evidence

Codex owns technical acceptance. Antigravity never accepts its own work.

## Codex responsibilities

Codex must:

- inspect and validate the ticket before delegation;
- preserve architecture and scope;
- delegate implementation through the ag_worker MCP server where appropriate;
- inspect the complete worker diff;
- independently rerun important verification;
- reject unrelated changes;
- send precise review findings through fix_review;
- integrate only after technical acceptance.

A worker report is evidence, not proof.

## Antigravity responsibilities

Antigravity may:

- read applicable repository instructions;
- inspect relevant implementation;
- edit files within ticket scope;
- add appropriate tests;
- run permitted verification.

Antigravity must not:

- broaden ticket scope;
- redesign unrelated systems;
- use Git for integration;
- push;
- merge;
- declare its own work accepted or done;
- hide failed tests or limitations;
- access another checkout of the repository.

## Human gates

Gameplay feel, visual quality, animation, UX, level design, narrative feel, and other subjective criteria remain human playtest gates unless explicitly measurable.

A technically clean worker branch may therefore end in READY_FOR_PLAYTEST rather than DONE.
