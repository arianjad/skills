# Skills

Claude Code skills I use in my research workflow (physics, AMO, lots of long-paper reading and code-as-experiment work).

## Read & comprehension

- **read-it-fully** — When you tell Claude to "read this fully" or "in depth", actually have it survey first, chunk semantically, walk every section, and cite specifics from each chunk — instead of skimming and pattern-matching to a familiar shape. Tested on synthetic logs, transcripts, numerical campaign data, and real physics PDFs from my Downloads. Helps measurably on long inputs without easy navigational shortcuts; stays out of the way otherwise.

  ```bash
  npx skills@latest add arianjad/skills/read-it-fully
  ```

  Or manual:

  ```bash
  mkdir -p ~/.claude/skills/read-it-fully
  curl -fsSL https://raw.githubusercontent.com/arianjad/skills/main/read-it-fully/SKILL.md \
    -o ~/.claude/skills/read-it-fully/SKILL.md
  ```

## Why a collection

These accumulate over time as I find friction points worth a skill. New ones land here under their own directory. Each `SKILL.md` is the canonical text Claude Code loads.

## License

MIT. See `LICENSE`.
