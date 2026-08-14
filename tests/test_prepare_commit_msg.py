"""Regression tests for prepare-commit-msg's determine_scope()."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import HOOK_PATH, git_diff, git_subject


def _fail_message(sha: str, expected: str | None, actual: str | None, trace) -> str:
    return (
        f'{sha}\n'
        f'expected: {expected!r}\nactual:   {actual!r}\n'
        f'trace:\n{json.dumps(trace, indent=2)}'
    )


def test_correct_prefill(hook, repo_path, correct_prefill_sha):
    """determine_scope() must reproduce the scope in the commit's own subject."""
    subject = git_subject(repo_path, correct_prefill_sha)
    if ' --- ' not in subject:
        raise ValueError(
            f"{correct_prefill_sha}: subject has no ' --- ' separator: {subject!r}"
        )
    expected_scope = subject.split(' --- ', 1)[0]

    diff_text = git_diff(repo_path, correct_prefill_sha)
    trace = hook.Trace()
    actual_scope = hook.determine_scope(diff_text, trace)
    assert actual_scope == expected_scope, _fail_message(
        correct_prefill_sha, expected_scope, actual_scope, hook._to_json(trace)
    )


def test_abstain_prefill(hook, repo_path, abstain_prefill_sha):
    """determine_scope() must return None, regardless of the commit's actual subject."""
    diff_text = git_diff(repo_path, abstain_prefill_sha)
    if 'diff --git ' not in diff_text:
        raise ValueError(
            f'{abstain_prefill_sha}: git show produced no diff content (merge commit?) '
            "-- doesn't exercise real heuristics, remove or replace this fixture"
        )

    trace = hook.Trace()
    actual_scope = hook.determine_scope(diff_text, trace)
    assert actual_scope is None, _fail_message(
        abstain_prefill_sha, None, actual_scope, hook._to_json(trace)
    )


def test_cli_environment_conf_flag(repo_path, correct_prefill_sha):
    """Smoke-test --environment-conf itself; the fixture-driven tests above
    never enter main(), so this is the only coverage of that flag's wiring.

    The autouse real_module_dirs fixture already sets
    PREPARE_COMMIT_MSG_ENVIRONMENT_CONF in this process, which a subprocess
    would inherit by default regardless of whether --environment-conf works
    -- so that var is explicitly removed from the child's environment here.
    """
    subject = git_subject(repo_path, correct_prefill_sha)
    expected_scope = subject.split(' --- ', 1)[0]
    diff_text = git_diff(repo_path, correct_prefill_sha)

    env = {
        k: v
        for k, v in os.environ.items()
        if k != 'PREPARE_COMMIT_MSG_ENVIRONMENT_CONF'
    }
    result = subprocess.run(
        [
            'python3',
            str(HOOK_PATH),
            '--environment-conf',
            str(repo_path / 'environment.conf'),
        ],
        input=diff_text,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0
    assert result.stdout.rstrip('\n') == f'{expected_scope} --- '


def test_default_environment_conf_path(hook, monkeypatch):
    """Covers the no-override branch of _resolve_environment_conf(), which
    every other test bypasses via the autouse real_module_dirs fixture.
    """
    monkeypatch.delenv('PREPARE_COMMIT_MSG_ENVIRONMENT_CONF', raising=False)
    expected = Path(hook.__file__).resolve().parent.parent / 'environment.conf'
    assert hook._resolve_environment_conf() == expected


@pytest.mark.parametrize(
    ('line', 'expected'),
    [
        # Quoted, fully-qualified -- domain dropped regardless of which one.
        ("node 'foo.example.com' {", 'foo'),
        ('node "foo.example.org" {', 'foo'),
        # Quoted, bare hostname -- nothing to strip.
        ("node 'foo' {", 'foo'),
        # Bare-word (Puppet 3) syntax, both with and without a domain.
        ('node foo.example.com {', 'foo'),
        ('node foo {', 'foo'),
        # Regex node names are left untouched (apart from anchor-stripping),
        # dots and all -- they're patterns, not literal hostnames, so
        # splitting on '.' would mangle the regex rather than strip a domain.
        (
            'node /^foo-\\d+\\.example\\.com$/ {',
            'foo-\\d+\\.example\\.com',
        ),
        ('node /^foo-\\d+/ {', 'foo-\\d+'),
        # Not a node declaration at all.
        ('class foo {', None),
    ],
)
def test_parse_node_name(hook, line, expected):
    assert hook._parse_node_name(line) == expected
