# puppet-auto-prepare-commit-msg-hook

A git `prepare-commit-msg` hook that automatically prefixes commit subjects
with a scope, following IceCube's Puppet repository convention of
`<SCOPE> --- <subject>`. The scope -- a Puppet class name, node hostname, or
file path -- is inferred from the staged diff, so contributors don't have to
type it by hand and commit subjects stay consistent.

## How it works

The hook parses the staged diff and looks for Puppet `class`/`define`/`node`
declarations in hunk headers, changed lines, and surrounding context. Files
outside `manifests/` (e.g. under `files/`, `templates/`, `hiera/`,
`hostfiles/`) are mapped to a scope based on their path instead. See the
heuristic itself, `determine_scope()` in `prepare-commit-msg`, for the exact
precedence rules. When no scope can be determined, the hook leaves the
commit message untouched -- it never blocks or fails a commit.

It's tailored to IceCube's Puppet layout (module directories read from
`environment.conf`) but the diff-parsing logic, including domain stripping
from fully-qualified node names, is layout-agnostic and can likely be
adapted to other Puppet repos.

## Installation

From inside the target git repository:

```bash
/path/to/prepare-commit-msg --install
```

This symlinks the script to `.git/hooks/prepare-commit-msg`. It will prompt
before overwriting an existing hook.

By default, module directories are read from an `environment.conf` two
levels above the script file (i.e. one directory above wherever the script's
parent directory lives). Override this with `--environment-conf` or the
`PREPARE_COMMIT_MSG_ENVIRONMENT_CONF` environment variable if that layout
doesn't fit.

## Usage

Once installed, the hook runs automatically on `git commit` and prepends
`<SCOPE> --- ` to the message. It's skipped for `--amend`, merges, squashes,
and `-m` commits, to avoid double-prefixing.

For debugging or scripting, run the script directly with no arguments to use
testing mode: it reads a diff from stdin, writes the scope prefix to stdout
(exiting 1 if none was found), and writes a JSON decision trace to stderr
explaining which heuristic branch fired.

```bash
git diff --cached | ./prepare-commit-msg
```

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

## Development

The script has no runtime dependencies beyond Python's standard library.
`pytest` is required to run the test suite, and `ruff` is used for
formatting and linting:

```bash
ruff format prepare-commit-msg tests/
ruff check prepare-commit-msg tests/
```

## License

MIT -- see [LICENSE](LICENSE).
