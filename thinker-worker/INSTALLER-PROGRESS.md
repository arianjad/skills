# Installer progress (portable hook)

- seam 1 green: `install --portable` writes a home-relative Claude hook; check passes (test_tw_portable.py seam1)
- seam 2 green: portable command run by bash denies a bad dispatch, admits a good one, both OS branches, bogus --python-cmd falls back (mutation-checked red: wrong path, no interpreter)
