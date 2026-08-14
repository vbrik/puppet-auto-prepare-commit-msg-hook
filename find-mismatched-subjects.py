#!/usr/bin/env python3
"""Find commits whose real subject doesn't match what prepare-commit-msg
would have generated for them.

Walks a repo's commit history from HEAD backwards (newest to oldest, the
default `git log` order), skipping merge commits, and runs each commit's
diff through prepare-commit-msg's determine_scope() heuristic. A commit is
a "mismatch" when the heuristic produces a scope but the commit's actual
subject doesn't start with "<scope> --- ". Commits where the heuristic
abstains (no scope) are skipped -- there's nothing to compare against.
Commits listed in --skip-file are ignored entirely. Commits whose diff
contains a case-insensitive substring of "passw", "priv", "cert", or
"secret" are never shown -- a note is printed instead, since the diff
itself might be sensitive.

Stops once --count mismatches have been found, or history is exhausted. For
each mismatch, prints the scope the hook would have prefilled followed by a
`git show` of the commit.
"""

import argparse
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

SCRIPT_DIR = Path(__file__).resolve().parent
HOOK_PATH = SCRIPT_DIR / 'prepare-commit-msg'

# Always colored, regardless of whether stdout is a terminal.
COLOR_RESET = '\033[0m'
COLOR_SCOPE = '\033[1;36m'  # bold cyan
COLOR_SEPARATOR = '\033[1;35m'  # bold magenta -- distinct from git's own diff colors
COLOR_WARN = '\033[1;33m'  # bold yellow


def load_hook() -> ModuleType:
    """Import prepare-commit-msg (no .py extension) as a module."""
    loader = importlib.machinery.SourceFileLoader('prepare_commit_msg', str(HOOK_PATH))
    spec = importlib.util.spec_from_file_location(
        'prepare_commit_msg', HOOK_PATH, loader=loader
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _run_git(args: list[str]) -> str:
    """Run `git <args>`, returning stdout; exits the program on failure."""
    result = subprocess.run(
        ['git', *args], capture_output=True, text=True, encoding='utf-8', check=False
    )
    if result.returncode != 0:
        print(result.stderr.rstrip())
        sys.exit(1)
    return result.stdout


def git_log_shas(repo_path: Path, authors: list[str] | None) -> list[str]:
    """SHAs of non-merge commits reachable from HEAD, newest first.

    Multiple authors are OR'd together, matching `git log`'s own behavior
    for repeated --author flags.
    """
    args = ['-C', str(repo_path), 'log', '--no-merges', '--format=%H']
    args += [f'--author={author}' for author in authors or []]
    return _run_git(args).splitlines()


def git_diff(repo_path: Path, sha: str) -> str:
    """Diff body of commit `sha` (no header/subject)."""
    return _run_git(
        ['-C', str(repo_path), '-c', 'core.pager=', 'show', '--format=', sha]
    )


def git_subject(repo_path: Path, sha: str) -> str:
    """Subject line of commit `sha`."""
    return _run_git(['-C', str(repo_path), 'show', '-s', '--format=%s', sha]).strip()


def print_git_show(repo_path: Path, sha: str) -> None:
    """Print `git show` for `sha`, with color forced on regardless of tty status."""
    subprocess.run(
        [
            'git',
            '-C',
            str(repo_path),
            '-c',
            'core.pager=',
            '-c',
            'color.ui=always',
            'show',
            sha,
        ],
        check=True,
    )


def scope_mismatch(scope: str, subject: str) -> bool:
    """True if `subject` doesn't start with the prefix the hook generates for `scope`."""
    return not subject.startswith(f'{scope} --- ')


SEPARATOR = '━' * 78

SENSITIVE_KEYWORDS = ('passw', 'priv', 'cert', 'secret')


def contains_sensitive_content(diff_text: str) -> bool:
    """True if `diff_text` contains a case-insensitive hit for any of SENSITIVE_KEYWORDS."""
    lower = diff_text.lower()
    return any(keyword in lower for keyword in SENSITIVE_KEYWORDS)


def read_skip_shas(path: Path) -> frozenset[str]:
    """Parse a skip-list file: one full commit SHA per line, blank lines and
    '#'-prefixed comments ignored.
    """
    shas = set()
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        sha = raw_line.split('#', 1)[0].strip()
        if sha:
            shas.add(sha)
    return frozenset(shas)


class Mismatch(NamedTuple):
    sha: str
    scope: str  # the scope the hook would have prefilled


def find_mismatches(
    hook: ModuleType,
    repo_path: Path,
    authors: list[str] | None,
    count: int,
    skip: frozenset[str] = frozenset(),
) -> list[Mismatch]:
    """Return up to `count` mismatches, newest first, ignoring any SHA in `skip`."""
    mismatches: list[Mismatch] = []
    for sha in git_log_shas(repo_path, authors):
        if len(mismatches) >= count:
            break
        if sha in skip:
            continue
        diff_text = git_diff(repo_path, sha)
        if contains_sensitive_content(diff_text):
            print(
                f'{COLOR_WARN}Skipping {sha}: diff may contain sensitive content'
                f'{COLOR_RESET}'
            )
            continue
        if 'diff --git ' not in diff_text:
            continue  # no diff content (e.g. empty commit) -- nothing to run the heuristic on
        scope = hook.determine_scope(diff_text, hook.Trace())
        if scope is None:
            continue  # hook would abstain -- nothing to compare against
        subject = git_subject(repo_path, sha)
        if scope_mismatch(scope, subject):
            mismatches.append(Mismatch(sha, scope))
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--repo-path', required=True, type=Path, help='git checkout to scan'
    )
    parser.add_argument(
        '-n',
        '--count',
        required=True,
        type=int,
        help='number of mismatched commits to find',
    )
    parser.add_argument(
        '--author',
        action='append',
        metavar='PATTERN',
        help='filter commits by author (git log --author pattern); may be repeated, '
        "matches any (OR'd)",
    )
    parser.add_argument(
        '--environment-conf',
        type=Path,
        help='environment.conf to read module directories from '
        '(default: <repo-path>/environment.conf)',
    )
    parser.add_argument(
        '--skip-file',
        type=Path,
        help='file listing commit SHAs (one per line, # comments allowed) to skip, '
        'e.g. known-bad commits already triaged',
    )
    args = parser.parse_args()

    if args.count < 0:
        parser.error('--count must be >= 0')

    repo_path = args.repo_path.expanduser().resolve()
    if not (repo_path / '.git').exists():
        parser.error(f'{repo_path} does not look like a git repository (no .git)')

    skip = read_skip_shas(args.skip_file) if args.skip_file else frozenset()

    os.environ['PREPARE_COMMIT_MSG_ENVIRONMENT_CONF'] = str(
        args.environment_conf.expanduser().resolve()
        if args.environment_conf
        else repo_path / 'environment.conf'
    )
    hook = load_hook()

    mismatches = find_mismatches(hook, repo_path, args.author, args.count, skip)
    for i, (sha, scope) in enumerate(mismatches):
        if i:
            print(flush=True)
            print(f'{COLOR_SEPARATOR}{SEPARATOR}{COLOR_RESET}', flush=True)
            print(flush=True)
        print(
            f'{COLOR_SCOPE}Hook would have generated: {scope} --- {COLOR_RESET}',
            flush=True,
        )
        print_git_show(repo_path, sha)

    if len(mismatches) < args.count:
        print(
            f'{COLOR_WARN}Scanned entire history; found only '
            f'{len(mismatches)}/{args.count} mismatches.{COLOR_RESET}'
        )


if __name__ == '__main__':
    main()
