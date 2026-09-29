# Installer progress (portable hook)

- 2026-09-29 lifecycle repair: activation validates routing before publishing state; upgrade retains accepted file/manifest bytes for conflict checks, checks retired files before removal, and rejects non-file targets or non-directory parents before writing. `test_tw_lifecycle.py` failed against the prior implementation for all six scenarios and passes after these scoped changes. This is optimistic conflict detection, not a multi-file transaction or a live installation/trust check.

- 2026-09-28 transport repair: Windows PowerShell forwarding adds a UTF-8 BOM on this host. The hook now reads bytes and explicitly decodes `utf-8-sig` instead of using locale-dependent stdin text. `test_tw_hook_transport.py` reproduces the pre-fix denial and checks BOM/plain UTF-8, Unicode under cp1252, the generated Windows command, and continued rejection of malformed input and unsupported models. This repairs parsing, not model availability or hook trust. Desktop live-dispatch validation is recorded by the investigating chat.

- seam 1 green: `install --portable` writes a home-relative Claude hook; check passes (test_tw_portable.py seam1)
- seam 2 green: portable command run by bash denies a bad dispatch, admits a good one, both OS branches, bogus --python-cmd falls back (mutation-checked red: wrong path, no interpreter)
- seam 3 green: install --portable -> check -> uninstall restores prior settings (test_tw_install.py; mutation-checked red: manifest recording the exec entry)
- seam 4 green: install --harness claude writes no ~/.codex; manifest records harnesses; check/uninstall follow it (old manifests default to both)
- docs: README install section covers --harness, --portable, --python-cmd
- seam 5 green: install adopts an identical synced owned entry (manifest "adopted"), refuses a differing one naming --python-cmd; test_tw_portable.py seam5
- seam 6 green: portable hook with no interpreter exits 2 (stderr fix hint) when any activation state exists under $h/.thinker-worker/state, else exit 0; test_tw_portable.py seam6 (PATH=empty dir, both OS branches)
- seam 7 green: --portable Codex entry = POSIX command (same search as Claude) + PowerShell -EncodedCommand commandWindows (PATH search; --python-cmd not applied); test_tw_codex_portable.py covers no-absolute-path, posix + cmd/C execution deny/admit, no-interpreter exit 2 only when activated, round trip
- docs: README covers adopt, no-interpreter block, Codex --portable
- seam 8a green: install (and re-install refresh) writes `<ledger-dir>/<machine-id>.json` (default `<home>/.claude/thinker-worker-installs`; `--ledger-dir`; id from `TW_MACHINE_ID` else OS-hostname) with machine_id, os, installed_at/updated_at, tw_sha256, flags, per-harness entry + written/adopted, status; test_tw_ledger.py seam a
- seam 8b green: `machines` (read-only) marks this machine, flags installed machines whose tw.py sha differs from the newest by updated_at, prints the in-place `upgrade` command; seam b
- seam 8c green: uninstall removes a shared entry only if no other installed ledger claims it, else keeps it and names the holder; ledger -> uninstalled; seam c (mutation-checked red: counting own ledger as a claim)
  - decision: ownership follows ledgers, not who wrote the entry. seam5 test expects removal when no other ledger is visible.
  - caveat: installs that predate ledgers publish none until `install` is rerun on that machine; until then another machine's uninstall will remove the shared entry.
- docs: README covers ledgers, `machines`, new uninstall rule
