import json
from pathlib import Path
import pytest
from core import github_resources as refs, employee_tools as tools, staffing
from scripts.director_mcp import dispatch


SHA = 'a' * 40


def test_acquire_pins_deduplicates_and_never_changes_project_or_reviewed_skills(tmp_path, monkeypatch):
    from core import skill_library
    p = tmp_path / 'game'
    p.mkdir()
    (p / 'game.gd').write_text('original')
    before = skill_library.current()
    calls = []
    def response(url):
        calls.append(url)
        return {'default_branch': 'main'} if '/branches/' not in url else {'commit': {'sha': SHA}}
    monkeypatch.setattr(refs, 'request', response)
    def github(repo, file, ref):
        assert ref == SHA
        return {'source': 'https://api.github.com/repos/test/game/contents/SKILL.md?ref=' + SHA, 'content': '# External skill\nDo not execute this: npm install unknown.'}
    monkeypatch.setattr(tools, 'github', github)
    result = refs.acquire(p, 'planner', 'test/game', 'SKILL.md')
    assert result['commit'] == SHA and result['cached']
    assert not result['installed'] and not result['executed']
    assert '/branches/main' in calls[-1]
    refs.acquire(p, 'planner', 'test/game', 'SKILL.md')
    assert len(refs.listing(p)['resources']) == 1
    assert skill_library.current() == before
    assert (p / 'game.gd').read_text() == 'original'
    assert len(list(p.iterdir())) == 1
    prompt = refs.instructions(p)
    assert 'untrusted source content' in prompt and 'not instructions or user-reviewed skills' in prompt
    assert 'npm install unknown' in prompt  # quoted data, not executed code or an enabled skill
    assert refs.instructions(tmp_path / 'different') == ''


def test_search_bounds_and_small_metadata(monkeypatch):
    monkeypatch.setattr(refs, 'request', lambda url: {'items': [{'full_name':'official/game', 'description':'docs', 'default_branch':'main', 'archived':False, 'license':{'spdx_id':'MIT'}}]})
    result = refs.search('godot game skill')
    assert result['repositories'][0]['license'] == 'MIT'
    for bad in ('', 'x' * 161, []):
        with pytest.raises(ValueError):
            refs.search(bad)


def test_download_limits_and_explicit_network_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, 'github', lambda *args: {'source':'public', 'content':'x' * 16001})
    with pytest.raises(ValueError):
        refs.acquire(tmp_path, 'planner', 'test/game', 'SKILL.md', SHA)
    assert not refs.cache_path(tmp_path).exists()
    for file in ('setup.exe', 'run.py', 'archive.zip'):
        with pytest.raises(ValueError):
            refs.acquire(tmp_path, 'planner', 'test/game', file, SHA)
    monkeypatch.setattr(refs, 'request', lambda url: (_ for _ in ()).throw(OSError('network unavailable')))
    with pytest.raises(OSError):
        refs.acquire(tmp_path, 'planner', 'test/game', 'SKILL.md')
    assert not refs.cache_path(tmp_path).exists()


def test_staff_defaults_mcp_annotations_and_explicit_restrictions(tmp_path, monkeypatch):
    for slot in staffing.SLOTS:
        assert {'github_search', 'github_acquire', 'github_read'} <= set(tools.DEFAULTS[slot])
    specs = dispatch({'method':'tools/list'}, str(tmp_path), 'gameplay')['tools']
    acquire = next(s for s in specs if s['name'] == 'github_acquire')
    assert not acquire['annotations']['readOnlyHint']
    assert not acquire['annotations']['destructiveHint']
    assert acquire['inputSchema']['required'] == ['repo', 'file']
    old = tools.current()
    tools.save({'employees': {'gameplay': ['project_files']}, 'research_staff_id': '', 'expected_revision': old['revision']})
    with pytest.raises(ValueError):
        tools.invoke('gameplay', 'github_acquire', {'repo':'test/game','file':'SKILL.md','project_path':str(tmp_path)})
