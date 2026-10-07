# Local use

This folder is the complete portable skill. Installation is optional; copying instructions below is a manual action for the recipient. Keep `SKILL.md`, the three supporting Markdown files, `agents/`, `LICENSE`, and `ATTRIBUTION.md` together.

- Claude Code: copy the folder as `.claude/skills/systematic-debugging/` in a project, or `~/.claude/skills/systematic-debugging/` for personal local discovery. Invoke `/systematic-debugging` with the failure details. These paths are for local Claude Code; Cowork and cloud sessions use their own skill discovery.
- Codex: copy the folder as `.agents/skills/systematic-debugging/` in a project, or `~/.agents/skills/systematic-debugging/` for user discovery. Invoke `$systematic-debugging` with the reproduction or failure. `agents/openai.yaml` supplies optional Codex UI metadata; no MCP dependency is required.
- Any local agent: ask it to read `systematic-debugging/SKILL.md` from the chosen location and follow the relative Markdown references as needed. If the agent has no skill loader, attach or supply those files directly. Tool names, test runner, and operating system are chosen by the receiving environment.

Provide expected versus observed behavior, reproduction steps, relevant output, recent changes, and prior fix attempts when available. Example: “Use systematic-debugging to diagnose this test failure. Establish the cause before editing, test one hypothesis at a time, and report verification evidence.”

Paths and invocation verified on 2026-10-07 against [Claude Code skills documentation](https://code.claude.com/docs/en/skills) and [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills). Recheck the receiving product's documentation if discovery differs. This extraction performs no installation or settings changes.
