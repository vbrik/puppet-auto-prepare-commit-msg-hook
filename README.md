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
