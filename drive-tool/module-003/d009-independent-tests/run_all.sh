#!/usr/bin/env bash
# d009 consolidated runner - records every command's exit code and output.
# Produces a single battery.log. Does not modify any checkout.
set -u
cd /scratch/work/d009
NEW=/scratch/work/new-c2b324d
OLD=/scratch/work/old-110b27e
D7=/scratch/repos/drop/drive-tool/module-003/d007-sarvam-review-fixes
export TMPDIR=/scratch/tmp

run() { # label, command...
  local label="$1"; shift
  echo "==================== $label ===================="
  echo "\$ $*"
  "$@"
  echo "EXIT=$?  ($label)"
  echo
}

echo "d009 consolidated battery  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

echo "########## A. environment ##########"
cat logs/00_env.log
echo

echo "########## B. committed suites (in-checkout) ##########"
run "suite new py3.11" bash -o pipefail -c "cd $NEW && python3.11 -m unittest discover -s tests -v 2>&1 | tail -n 4"
run "suite new py3.12" bash -o pipefail -c "cd $NEW && python3.12 -m unittest discover -s tests -v 2>&1 | tail -n 4"
run "suite old py3.11" bash -o pipefail -c "cd $OLD && python3.11 -m unittest discover -s tests -v 2>&1 | tail -n 4"
run "suite old py3.12" bash -o pipefail -c "cd $OLD && python3.12 -m unittest discover -s tests -v 2>&1 | tail -n 4"

echo "########## C. independent checks (d009) ##########"
for py in python3.11 python3.12; do
  run "raw_nofollow_probe $py" bash -o pipefail -c "PYTHONPATH=$NEW $py raw_nofollow_probe.py"
done
for py in python3.11 python3.12; do
  run "containment NEW $py" bash -o pipefail -c "PYTHONPATH=$NEW $py containment_assert.py"
  run "containment OLD $py" bash -o pipefail -c "PYTHONPATH=$OLD $py containment_assert.py"
done
for py in python3.11 python3.12; do
  run "bounded_read NEW $py" bash -o pipefail -c "PYTHONPATH=$NEW $py bounded_read_checks.py"
  run "root_rename_anchor NEW $py" bash -o pipefail -c "PYTHONPATH=$NEW $py root_rename_anchor.py"
  run "fifo_timeout NEW $py" bash -o pipefail -c "PYTHONPATH=$NEW $py fifo_timeout.py"
  run "fd_cleanup NEW $py" bash -o pipefail -c "PYTHONPATH=$NEW $py fd_cleanup.py"
done

echo "########## D. revision diff ##########"
run "diff_check" python3 diff_check.py "$OLD" "$NEW"

echo "########## E. d007 reproducers (secondary cross-check) ##########"
run "d007 race_probe_assert NEW" bash -o pipefail -c "PYTHONPATH=$NEW python3.11 $D7/race_probe_assert.py"
run "d007 race_probe_assert OLD" bash -o pipefail -c "PYTHONPATH=$OLD python3.11 $D7/race_probe_assert.py"
run "d007 run_new_tests_on_old py3.11" bash -o pipefail -c "cd oldcheck && PYTHONPATH=$PWD/oldcheck python3.11 run_new_tests_on_old.py 2>&1 | tail -n 3"
run "d007 run_new_tests_on_old py3.12" bash -o pipefail -c "cd oldcheck && PYTHONPATH=$PWD/oldcheck python3.12 run_new_tests_on_old.py 2>&1 | tail -n 3"

echo "########## battery complete ##########"
