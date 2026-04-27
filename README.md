# Skills

Skills I use with Claude Code, mostly in my physics research — long papers, code-as-experiment work.

## Reading

- **read-it-fully** — Makes Claude actually walk every section of a long file and cite specifics, instead of skimming the start and end. Triggers on phrases like "read this fully", "read carefully", "in depth". Tested on synthetic logs, a meeting transcript, a 5000-line numerical campaign log, and real PDFs from my Downloads.

  ```bash
  npx skills@latest add arianjad/skills/read-it-fully
  ```

  Or manual:

  ```bash
  mkdir -p ~/.claude/skills/read-it-fully
  curl -fsSL https://raw.githubusercontent.com/arianjad/skills/main/read-it-fully/SKILL.md \
    -o ~/.claude/skills/read-it-fully/SKILL.md
  ```

## Adding more

New skills land here in their own subdirectory as I write them. Each `SKILL.md` is what Claude Code loads.

## License

MIT.
