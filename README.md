## find-mismatched-subjects.py

Dev helper that scans a repo's commit history (newest first, non-merge
commits) and reports commits whose real subject doesn't start with the
scope prefix `prepare-commit-msg` would have generated for them -- useful
for spotting heuristic regressions or subjects that were written by hand.
Stops once it's found the requested number of mismatches. For each
mismatch, prints the scope the hook would have prefilled, then a
`git show` of the commit, separated from the next mismatch by a divider
line. All output goes to stdout.

```bash
./find-mismatched-subjects.py --repo-path /path/to/puppet/repo -n 10
./find-mismatched-subjects.py --repo-path /path/to/puppet/repo -n 5 --author alice --author bob
./find-mismatched-subjects.py --repo-path /path/to/puppet/repo -n 10 --skip-file triaged.txt
```

`--skip-file` takes a file of commit SHAs (one per line, `#` comments allowed,
same format as the fixture lists below) to exclude from consideration --
handy for commits already triaged as known, accepted mismatches.

Commits whose diff contains a case-insensitive substring of "passw", "priv",
"cert", or "secret" are never printed -- a skip notice is printed instead,
since the diff itself might be sensitive.

## Testing

Regression tests replay a curated set of real commits through
`prepare-commit-msg`'s scope-detection heuristic (`determine_scope()`) and
check that it still does the right thing.

### Fixtures

- `correct-prefill.txt` -- commit SHAs where the hook must reproduce the
  scope already encoded in that commit's own subject (the part before
  `" --- "`).
- `abstain-prefill.txt` -- commit SHAs where the hook must produce no scope
  at all, regardless of that commit's actual subject.

Each file is a flat list of SHAs, one per line; `#`-prefixed lines are
comments. No diff content is stored in this repo -- at test time, each SHA
is resolved against a real git checkout, so listed commits must stay
reachable there. A trailing `# xfail: <reason>` on a SHA line marks a known,
accepted heuristic gap rather than a live regression.

### Adding a fixture

When the hook does the wrong thing on a real commit:

1. Note the commit's SHA.
2. Append it to `correct-prefill.txt` (if the hook should have prefilled a
   specific scope) or `abstain-prefill.txt` (if it should have abstained).
3. Fix the heuristic in `prepare-commit-msg`, and rerun the suite to confirm
   nothing else regressed.

### Running the tests

Tests need access to a git checkout containing the fixture commits, via
`--repo-path` or the `PREPARE_COMMIT_MSG_TEST_REPO` environment variable:

```bash
pytest tests/ --repo-path /path/to/puppet/repo
# or
PREPARE_COMMIT_MSG_TEST_REPO=/path/to/puppet/repo pytest tests/
```
