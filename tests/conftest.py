"""Shared fixtures for the prepare-commit-msg regression suite.

Fixture lists live at the repo root: correct-prefill.txt and abstain-prefill.txt,
each just a list of commit SHAs (no diff content, so nothing sensitive lives in
this repo). At test time each SHA is resolved against a real git checkout --
supplied via --repo-path or PREPARE_COMMIT_MSG_TEST_REPO -- via `git show`.

correct-prefill.txt entries must reproduce the scope already encoded in that
commit's own real subject (the part before ' --- '). abstain-prefill.txt
entries must produce no scope at all, regardless of their actual subject.

A list entry may carry an inline `# xfail: <reason>` annotation to mark a
known, accepted heuristic gap rather than a real regression -- see
abstain-prefill.txt for an example.
"""

import importlib.machinery
import importlib.util
import os
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / 'prepare-commit-msg'


def pytest_addoption(parser):
    parser.addoption(
        '--repo-path',
        default=None,
        help='Git checkout containing the fixture commits (overrides '
        'PREPARE_COMMIT_MSG_TEST_REPO if both are given).',
    )


@pytest.fixture(scope='session')
def repo_path(request) -> Path:
    raw = request.config.getoption('--repo-path') or os.environ.get(
        'PREPARE_COMMIT_MSG_TEST_REPO'
    )
    if not raw:
        pytest.fail(
            'Set --repo-path or PREPARE_COMMIT_MSG_TEST_REPO to a git checkout '
            'containing the fixture commits.'
        )
    path = Path(raw).expanduser().resolve()
    if not (path / '.git').exists():
        pytest.fail(f'{path} does not look like a git repository (no .git)')
    return path


@pytest.fixture(scope='session')
def hook():
    """Import prepare-commit-msg as a module, once per test session.

    spec_from_file_location() returns None for extensionless files unless
    given an explicit loader, hence SourceFileLoader rather than plain
    module_from_spec(spec_from_file_location(name, path)).
    """
    loader = importlib.machinery.SourceFileLoader('prepare_commit_msg', str(HOOK_PATH))
    spec = importlib.util.spec_from_file_location(
        'prepare_commit_msg', HOOK_PATH, loader=loader
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def real_module_dirs(repo_path, monkeypatch):
    """Point prepare-commit-msg at the real repo's own environment.conf.

    _load_module_dirs()/_module_re() key their lru_cache on the resolved
    conf path/module dirs, so no manual cache-busting is needed here even
    though this fixture reruns for every test.
    """
    monkeypatch.setenv(
        'PREPARE_COMMIT_MSG_ENVIRONMENT_CONF', str(repo_path / 'environment.conf')
    )


def git_diff(repo_path: Path, sha: str) -> str:
    """Return just the diff body of commit `sha` (no header/subject)."""
    result = subprocess.run(
        ['git', '-C', str(repo_path), 'show', '--format=', sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f'git show --format= {sha} in {repo_path} failed:\n{result.stderr}'
        )
    return result.stdout


def git_subject(repo_path: Path, sha: str) -> str:
    """Return the subject line of commit `sha`."""
    result = subprocess.run(
        ['git', '-C', str(repo_path), 'show', '-s', '--format=%s', sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f'git show -s --format=%s {sha} in {repo_path} failed:\n{result.stderr}'
        )
    return result.stdout.strip()


class FixtureEntry(NamedTuple):
    sha: str
    xfail_reason: str | None


def read_shas(path: Path) -> list[FixtureEntry]:
    """Parse a fixture list file: one sha per line, '#'-prefixed lines are
    full-line comments, and a trailing '# xfail: <reason>' on a sha line
    marks that entry as a known, accepted failure.
    """
    if not path.exists():
        return []
    entries = []
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        sha_part, _, comment_part = raw_line.partition('#')
        sha = sha_part.strip()
        if not sha:
            continue
        comment = comment_part.strip()
        reason = (
            comment.removeprefix('xfail:').strip()
            if comment.startswith('xfail:')
            else None
        )
        entries.append(FixtureEntry(sha, reason))
    return entries


def _params(entries: list[FixtureEntry]) -> list:
    return [
        pytest.param(e.sha, marks=pytest.mark.xfail(reason=e.xfail_reason, strict=True))
        if e.xfail_reason
        else pytest.param(e.sha)
        for e in entries
    ]


def pytest_generate_tests(metafunc):
    if 'correct_prefill_sha' in metafunc.fixturenames:
        entries = read_shas(REPO_ROOT / 'correct-prefill.txt')
        metafunc.parametrize(
            'correct_prefill_sha', _params(entries), ids=[e.sha for e in entries]
        )
    if 'abstain_prefill_sha' in metafunc.fixturenames:
        entries = read_shas(REPO_ROOT / 'abstain-prefill.txt')
        metafunc.parametrize(
            'abstain_prefill_sha', _params(entries), ids=[e.sha for e in entries]
        )
