# d009 independent tests - artifact manifest

Intended relay location (write blocked this run - PUSH_BLOCKED):
  Dolesh-avkalan/drop : drive-tool/module-003/d009-independent-tests/

Files in this bundle and their target paths:

  d009-sarvam-independent-tests.md  -> drive-tool/module-003/d009-independent-tests/d009-sarvam-independent-tests.md
  scripts/containment_assert.py     -> drive-tool/module-003/d009-independent-tests/containment_assert.py
  scripts/raw_nofollow_probe.py     -> drive-tool/module-003/d009-independent-tests/raw_nofollow_probe.py
  scripts/bounded_read_checks.py    -> drive-tool/module-003/d009-independent-tests/bounded_read_checks.py
  scripts/root_rename_anchor.py     -> drive-tool/module-003/d009-independent-tests/root_rename_anchor.py
  scripts/fifo_timeout.py           -> drive-tool/module-003/d009-independent-tests/fifo_timeout.py
  scripts/fd_cleanup.py             -> drive-tool/module-003/d009-independent-tests/fd_cleanup.py
  scripts/diff_check.py             -> drive-tool/module-003/d009-independent-tests/diff_check.py
  run_all.sh                        -> drive-tool/module-003/d009-independent-tests/run_all.sh
  logs/*.log                        -> drive-tool/module-003/d009-independent-tests/logs/*.log

Tested revisions:
  new c2b324dab4cf720178a36a58b5f1cf1339730151 (feature/module-003-review-fixes)
  old 110b27e81cfead478eb6e400a44043f6e14f14b7
Environment: Python 3.11.2 / 3.12.13, Linux 4.19.0-gvisor, /scratch v9fs.
