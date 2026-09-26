# Installer progress (portable hook)

- seam 1 green: `install --portable` writes a home-relative Claude hook; check passes (test_tw_portable.py seam1)
- seam 2 green: portable command run by bash denies a bad dispatch, admits a good one, both OS branches, bogus --python-cmd falls back (mutation-checked red: wrong path, no interpreter)
- seam 3 green: install --portable -> check -> uninstall restores prior settings (test_tw_install.py; mutation-checked red: manifest recording the exec entry)
- seam 4 green: install --harness claude writes no ~/.codex; manifest records harnesses; check/uninstall follow it (old manifests default to both)
- docs: README install section covers --harness, --portable, --python-cmd
- seam 5 green: install adopts an identical synced owned entry (manifest "adopted"), refuses a differing one naming --python-cmd; test_tw_portable.py seam5
  - decision: uninstall keeps adopted entries (removes only entries this machine wrote). Reason: settings.json syncs, so B removing A's entry would silently unguard A; the machine that wrote it owns its removal.
- seam 6 green: portable hook with no interpreter exits 2 (stderr fix hint) when any activation state exists under $h/.thinker-worker/state, else exit 0; test_tw_portable.py seam6 (PATH=empty dir, both OS branches)
