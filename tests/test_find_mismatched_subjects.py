"""Unit tests for find-mismatched-subjects.py.

These test generic matching/control-flow logic, not prepare-commit-msg's
scope heuristics themselves (those are covered by test_prepare_commit_msg.py
against real fixture commits). The `real_module_dirs` fixture below shadows
conftest.py's autouse fixture of the same name with a synthetic
environment.conf, so this file doesn't need --repo-path/
PREPARE_COMMIT_MSG_TEST_REPO to run.
"""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / 'find-mismatched-subjects.py'


@pytest.fixture(autouse=True)
def real_module_dirs(tmp_path, monkeypatch):
    conf = tmp_path / 'environment.conf'
    conf.write_text('modulepath = modules\n', encoding='utf-8')
    monkeypatch.setenv('PREPARE_COMMIT_MSG_ENVIRONMENT_CONF', str(conf))


@pytest.fixture(scope='session')
def finder():
    """Import find-mismatched-subjects.py once per test session."""
    loader = importlib.machinery.SourceFileLoader(
        'find_mismatched_subjects', str(SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_file_location(
        'find_mismatched_subjects', SCRIPT_PATH, loader=loader
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _diff(path: str) -> str:
    """A minimal single-file diff, enough for determine_scope() to key off `path`."""
    return (
        f'diff --git a/{path} b/{path}\n'
        'index 1111111..2222222 100644\n'
        f'--- a/{path}\n'
        f'+++ b/{path}\n'
        '@@ -1 +1 @@\n'
        '-old\n'
        '+new\n'
    )


class TestScopeMismatch:
    def test_matching_subject_is_not_a_mismatch(self, finder):
        assert finder.scope_mismatch('README.md', 'README.md --- fix typo') is False

    def test_unrelated_subject_is_a_mismatch(self, finder):
        assert finder.scope_mismatch('README.md', 'unrelated subject') is True

    def test_prefix_without_separator_is_a_mismatch(self, finder):
        assert finder.scope_mismatch('foo', 'foobar') is True


class TestFindMismatches:
    def test_flags_mismatched_subject(self, finder, monkeypatch):
        monkeypatch.setattr(finder, 'git_log_shas', lambda repo, authors: ['sha1'])
        monkeypatch.setattr(finder, 'git_diff', lambda repo, sha: _diff('README.md'))
        monkeypatch.setattr(
            finder, 'git_subject', lambda repo, sha: 'unrelated subject'
        )
        result = finder.find_mismatches(finder.load_hook(), Path('.'), None, count=5)
        assert result == [('sha1', 'README.md')]
        assert result[0].sha == 'sha1'
        assert result[0].scope == 'README.md'

    def test_skips_matching_subject(self, finder, monkeypatch):
        monkeypatch.setattr(finder, 'git_log_shas', lambda repo, authors: ['sha1'])
        monkeypatch.setattr(finder, 'git_diff', lambda repo, sha: _diff('README.md'))
        monkeypatch.setattr(finder, 'git_subject', lambda repo, sha: 'README.md --- ok')
        result = finder.find_mismatches(finder.load_hook(), Path('.'), None, count=5)
        assert result == []

    def test_skips_commit_with_no_diff_content(self, finder, monkeypatch):
        calls = []
        monkeypatch.setattr(finder, 'git_log_shas', lambda repo, authors: ['sha1'])
        monkeypatch.setattr(finder, 'git_diff', lambda repo, sha: '')
        monkeypatch.setattr(finder, 'git_subject', lambda repo, sha: calls.append(sha))
        result = finder.find_mismatches(finder.load_hook(), Path('.'), None, count=5)
        assert result == []
        assert calls == []  # subject never needed to be inspected

    def test_stops_at_count(self, finder, monkeypatch):
        shas = ['sha1', 'sha2', 'sha3']
        monkeypatch.setattr(finder, 'git_log_shas', lambda repo, authors: shas)
        monkeypatch.setattr(finder, 'git_diff', lambda repo, sha: _diff('README.md'))
        monkeypatch.setattr(
            finder, 'git_subject', lambda repo, sha: 'unrelated subject'
        )
        result = finder.find_mismatches(finder.load_hook(), Path('.'), None, count=2)
        assert result == [('sha1', 'README.md'), ('sha2', 'README.md')]

    def test_skips_shas_in_skip_set(self, finder, monkeypatch):
        shas = ['sha1', 'sha2', 'sha3']
        monkeypatch.setattr(finder, 'git_log_shas', lambda repo, authors: shas)
        monkeypatch.setattr(finder, 'git_diff', lambda repo, sha: _diff('README.md'))
        monkeypatch.setattr(
            finder, 'git_subject', lambda repo, sha: 'unrelated subject'
        )
        result = finder.find_mismatches(
            finder.load_hook(), Path('.'), None, count=5, skip=frozenset({'sha2'})
        )
        assert result == [('sha1', 'README.md'), ('sha3', 'README.md')]


class TestContainsSensitiveContent:
    @pytest.mark.parametrize(
        'keyword', ['passw', 'PASSWORD', 'priv', 'PRIVATE', 'cert', 'secret']
    )
    def test_flags_sensitive_keywords(self, finder, keyword):
        assert finder.contains_sensitive_content(_diff('foo') + keyword) is True

    def test_does_not_flag_unrelated_diff(self, finder):
        assert finder.contains_sensitive_content(_diff('README.md')) is False


class TestFindMismatchesSensitiveSkipping:
    def test_skips_sensitive_commit_and_prints_notice(
        self, finder, monkeypatch, capsys
    ):
        monkeypatch.setattr(finder, 'git_log_shas', lambda repo, authors: ['sha1'])
        monkeypatch.setattr(
            finder,
            'git_diff',
            lambda repo, sha: _diff('secrets.pp') + 'password = hunter2',
        )
        monkeypatch.setattr(
            finder, 'git_subject', lambda repo, sha: 'unrelated subject'
        )
        result = finder.find_mismatches(finder.load_hook(), Path('.'), None, count=5)
        assert result == []
        assert 'sha1' in capsys.readouterr().out

    def test_keeps_scanning_past_a_sensitive_commit(self, finder, monkeypatch):
        diffs = {'sha1': _diff('secrets.pp') + 'secret', 'sha2': _diff('README.md')}
        monkeypatch.setattr(
            finder, 'git_log_shas', lambda repo, authors: ['sha1', 'sha2']
        )
        monkeypatch.setattr(finder, 'git_diff', lambda repo, sha: diffs[sha])
        monkeypatch.setattr(
            finder, 'git_subject', lambda repo, sha: 'unrelated subject'
        )
        result = finder.find_mismatches(finder.load_hook(), Path('.'), None, count=5)
        assert result == [('sha2', 'README.md')]


class TestReadSkipShas:
    def test_parses_shas_ignoring_blanks_and_comments(self, finder, tmp_path):
        skip_file = tmp_path / 'skip.txt'
        skip_file.write_text(
            '# comment line\nsha1\n\nsha2  # trailing comment\n',
            encoding='utf-8',
        )
        assert finder.read_skip_shas(skip_file) == frozenset({'sha1', 'sha2'})


class TestGitLogShas:
    def test_builds_repeated_author_flags(self, finder, monkeypatch):
        captured = {}

        def fake_run_git(args):
            captured['args'] = args
            return 'sha1\nsha2\n'

        monkeypatch.setattr(finder, '_run_git', fake_run_git)
        result = finder.git_log_shas(Path('/repo'), ['Alice', 'Bob'])
        assert result == ['sha1', 'sha2']
        assert '--author=Alice' in captured['args']
        assert '--author=Bob' in captured['args']

    def test_no_author_filter_by_default(self, finder, monkeypatch):
        captured = {}

        def fake_run_git(args):
            captured['args'] = args
            return ''

        monkeypatch.setattr(finder, '_run_git', fake_run_git)
        finder.git_log_shas(Path('/repo'), None)
        assert not any(a.startswith('--author=') for a in captured['args'])
