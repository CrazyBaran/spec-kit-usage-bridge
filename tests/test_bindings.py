from dataclasses import replace

import pytest

from usage_bridge.attribution import attribute_runs
from usage_bridge.phases import Run


@pytest.mark.parametrize('runtime', ['claude', 'codex', 'cursor'])
def test_binding_overrides_old_branch_for_one_invocation(tmp_path, runtime):
    from usage_bridge.bindings import FeatureBinding
    first = Run('s', 'core', 'specify', 'specify', '2026-10-01T08:00:00.000Z', None,
                runtime=runtime, last_branch='001-old')
    second = replace(first, start_ts='2026-10-01T09:00:00.000Z')
    binding = FeatureBinding(runtime, 's', str(tmp_path), 'specs/002-new', 'specify', first.start_ts)
    rows = attribute_runs([first, second], {}, ['specs/001-old', 'specs/002-new'], bindings=[binding])
    assert rows[0].bucket.feature_dir == 'specs/002-new'
    assert rows[0].attributed_by == 'binding'
    assert rows[1].bucket.feature_dir == 'specs/001-old'
    other = replace(first, runtime='cursor' if runtime != 'cursor' else 'claude')
    assert attribute_runs([other], {}, ['specs/001-old', 'specs/002-new'], bindings=[binding])[0].attributed_by == 'branch'


def test_selection_requires_unique_invocation_or_explicit_selector():
    from usage_bridge.bindings import select_run
    runs = [Run('s', 'core', 'specify', 'specify', stamp, None, runtime='codex')
            for stamp in ['2026-10-01T08:00:00.000Z', '2026-10-01T09:00:00.000Z']]
    with pytest.raises(ValueError, match='invocation'):
        select_run(runs, 'codex', 's', 'specify')
    assert select_run(runs, 'codex', 's', 'specify', latest=True) == runs[1]
    assert select_run(runs, 'codex', 's', 'specify', invocation_ts=runs[0].start_ts) == runs[0]


def test_binding_storage_is_stable_and_checkout_scoped(tmp_path):
    from usage_bridge.bindings import FeatureBinding, load_bindings, save_binding
    work = tmp_path / 'work'
    (work / 'specs/002-new').mkdir(parents=True)
    runtime = tmp_path / 'runtime'
    binding = FeatureBinding('codex', 's', str(work), 'specs/002-new', 'specify', '2026-10-01T08:00:00.000Z')
    assert save_binding(runtime, binding)
    assert not save_binding(runtime, binding)
    assert load_bindings(runtime, work) == [binding]
    assert load_bindings(runtime, tmp_path / 'another-worktree') == []


def test_corrupt_binding_file_cannot_be_overwritten(tmp_path):
    from usage_bridge.bindings import FeatureBinding, save_binding
    path = tmp_path / 'feature-bindings.json'
    path.write_text('{broken')
    binding = FeatureBinding('codex', 's', str(tmp_path), 'specs/new', 'specify', '2026-10-01T08:00:00.000Z')
    with pytest.raises(ValueError, match='binding'):
        save_binding(tmp_path, binding)
    assert path.read_text() == '{broken'


def test_binding_rejects_outside_feature_path(tmp_path):
    from usage_bridge.bindings import FeatureBinding
    with pytest.raises(ValueError, match='feature'):
        FeatureBinding('codex', 's', str(tmp_path), '../other', 'specify', '2026-10-01T08:00:00.000Z')


def test_binding_remains_valid_as_run_end_changes(tmp_path):
    from usage_bridge.bindings import FeatureBinding
    run = Run('s', 'core', 'specify', 'specify', '2026-10-01T08:00:00.000Z', None, runtime='codex')
    binding = FeatureBinding('codex', 's', str(tmp_path), 'specs/new', 'specify', run.start_ts)
    delayed = replace(run, end_ts='2026-10-01T08:05:00.000Z')
    assert attribute_runs([delayed], {}, ['specs/new'], bindings=[binding])[0].bucket.feature_dir == 'specs/new'


@pytest.mark.parametrize('runtime', ['claude', 'codex', 'cursor'])
def test_later_phases_and_feature_switch_do_not_inherit(tmp_path, runtime):
    from usage_bridge.bindings import FeatureBinding
    runs = [Run('s', 'core' if phase != 'superspec.brainstorm' else 'extension', phase, phase,
                f'2026-10-01T0{hour}:00:00.000Z', None, runtime=runtime, last_branch='001-old')
            for hour, phase in [(8, 'clarify'), (9, 'superspec.brainstorm'), (9, 'plan')]]
    bindings = [FeatureBinding(runtime, 's', str(tmp_path), destination, run.phase, run.start_ts)
                for run, destination in zip(runs[:2], ['specs/B', 'specs/C'])]
    rows = attribute_runs(runs, {}, ['specs/001-old', 'specs/B', 'specs/C'], bindings=bindings)
    assert [row.bucket.feature_dir for row in rows] == ['specs/B', 'specs/C', 'specs/001-old']
    assert attribute_runs([runs[2]], {}, ['specs/B'], bindings=bindings)[0].bucket.kind == 'unattributed'


def test_selection_rejects_tied_or_missing_starts():
    from usage_bridge.bindings import select_run
    run = Run('s', 'core', 'clarify', 'clarify', '2026-10-01T08:00:00.000Z', None, runtime='codex')
    for args in ({}, {'latest': True}, {'invocation_ts': run.start_ts}):
        with pytest.raises(ValueError, match='invocation'):
            select_run([run, replace(run)], 'codex', 's', 'clarify', **args)
    with pytest.raises(ValueError):
        select_run([replace(run, start_ts=None)], 'codex', 's', 'clarify')
    with pytest.raises(ValueError):
        select_run([run], 'codex', 's', 'clarify', latest=True, invocation_ts=run.start_ts)


@pytest.mark.parametrize('phase,stamp', [('constitution', '2026-10-01T08:00:00Z'), ('clarify', 'bad')])
def test_binding_rejects_invalid_phase_or_timestamp(tmp_path, phase, stamp):
    from usage_bridge.bindings import FeatureBinding
    with pytest.raises(ValueError):
        FeatureBinding('codex', 's', str(tmp_path), 'specs/B', phase, stamp)


def test_duplicate_binding_keys_are_rejected(tmp_path):
    import json
    from dataclasses import asdict
    from usage_bridge.bindings import FeatureBinding, load_bindings
    binding = FeatureBinding('codex', 's', str(tmp_path), 'specs/B', 'clarify', '2026-10-01T08:00:00Z')
    (tmp_path / 'feature-bindings.json').write_text(json.dumps({'version': 1, 'bindings': [asdict(binding)] * 2}))
    with pytest.raises(ValueError, match='binding'):
        load_bindings(tmp_path, tmp_path)
