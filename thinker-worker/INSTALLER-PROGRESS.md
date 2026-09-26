# Installer progress (portable hook)

- seam 1 green: `install --portable` writes a home-relative Claude hook; check passes (test_tw_portable.py seam1)
- seam 2 green: portable command run by bash denies a bad dispatch, admits a good one, both OS branches, bogus --python-cmd falls back (mutation-checked red: wrong path, no interpreter)
- seam 3 green: install --portable -> check -> uninstall restores prior settings (test_tw_install.py; mutation-checked red: manifest recording the exec entry)
- seam 4 green: install --harness claude writes no ~/.codex; manifest records harnesses; check/uninstall follow it (old manifests default to both)
- docs: README install section covers --harness, --portable, --python-cmd
- seam 5 green: install adopts an identical synced owned entry (manifest "adopted"), refuses a differing one naming --python-cmd; test_tw_portable.py seam5
  - decision: uninstall keeps adopted entries (removes only entries this machine wrote). Reason: settings.json syncs, so B removing A's entry would silently unguard A; the machine that wrote it owns its removal.
- seam 6 green: portable hook with no interpreter exits 2 (stderr fix hint) when any activation state exists under $h/.thinker-worker/state, else exit 0; test_tw_portable.py seam6 (PATH=empty dir, both OS branches)
- seam 7 green: --portable Codex entry = POSIX command (same search as Claude) + PowerShell -EncodedCommand commandWindows (PATH search; --python-cmd not applied); test_tw_codex_portable.py covers no-absolute-path, posix + cmd/C execution deny/admit, no-interpreter exit 2 only when activated, round trip
- docs: README covers adopt, no-interpreter block, Codex --portable
- seam 8a green: install (and re-install refresh) writes `<ledger-dir>/<machine-id>.json` (default `<home>/.claude/thinker-worker-installs`; `--ledger-dir`; id from `TW_MACHINE_ID` else OS-hostname) with machine_id, os, installed_at/updated_at, tw_sha256, flags, per-harness entry + written/adopted, status; test_tw_ledger.py seam a
- seam 8b green: `machines` (read-only) marks this machine, flags installed machines whose tw.py sha differs from the newest by updated_at, prints `uninstall && install <own flags>`; seam b
- seam 8c green: uninstall removes a shared entry only if no other installed ledger claims it, else keeps it and names the holder; ledger -> uninstalled; seam c (mutation-checked red: counting own ledger as a claim)
  - decision (supersedes seam 5's "keep adopted entries"): ownership follows ledgers, not who wrote the entry. seam5 test now expects removal when no other ledger is visible.
  - caveat: installs that predate ledgers publish none until `install` is rerun on that machine; until then another machine's uninstall will remove the shared entry.
- docs: README covers ledgers, `machines`, new uninstall rule
