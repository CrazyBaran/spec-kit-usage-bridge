from codex_builders import context, prompt, tokens, turn, write_rollout
from usage_bridge.config import Config


def parse(tmp_path, events, parent=None):
    from usage_bridge.adapters.codex import CodexAdapter

    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir(exist_ok=True)
    write_rollout(home, repo, events=events, parent=parent)
    reader = CodexAdapter()
    ctx = context(repo, home)
    return reader.parse(list(reader.discover(ctx, Config()))[0], ctx)


def test_cumulative_snapshots_are_not_added_twice(tmp_path):
    snapshot = tokens(180, 70, 35, reasoning=10, stamp="2026-10-01T08:00:04Z")
    digest = parse(tmp_path, [turn(), prompt(), tokens(100, 40, 20), snapshot, snapshot])
    assert sum(r.input for r in digest.requests) == 110
    assert sum(r.cache_read for r in digest.requests) == 70
    assert sum(r.output for r in digest.requests) == 35
    assert len(digest.requests) == 2
    assert digest.measurement == "exact"
    assert digest.requests[0].kind == "counter_delta"


def test_counter_decrease_retains_last_trustworthy_totals(tmp_path):
    digest = parse(tmp_path, [turn(), prompt(), tokens(100, 40, 20), tokens(10, 2, 3)])
    assert sum(r.input for r in digest.requests) == 60
    assert digest.measurement == "partial"
    assert "counter-reset" in digest.reasons


def test_unknown_or_invalid_buckets_are_partial(tmp_path):
    digest = parse(tmp_path, [turn(), prompt(), tokens(10, 20, 5)])
    assert digest.measurement == "activity_only"
    assert "invalid-token-buckets" in digest.reasons
    assert not digest.requests


def test_unsupported_cache_write_is_disclosed(tmp_path):
    digest = parse(tmp_path, [turn(), prompt(), tokens(100, 40, 20, cache_write_input_tokens=10)])
    assert digest.measurement == "partial"
    assert "cache-write-duration-unknown" in digest.reasons


def test_synthetic_total_does_not_create_spend(tmp_path):
    entry = tokens(100, 40, 20, total_tokens=250000)
    digest = parse(tmp_path, [turn(), prompt(), entry])
    assert sum(r.output for r in digest.requests) == 20
    assert digest.measurement == "partial"


def test_missing_usage_is_activity_only(tmp_path):
    digest = parse(tmp_path, [turn(), prompt()])
    assert digest.measurement == "activity_only"
    assert digest.events[0].name == "/speckit.plan"


def test_missing_prefix_has_unassigned_phase(tmp_path):
    digest = parse(tmp_path, [turn(), tokens(100, 40, 20), prompt()])
    assert digest.requests[0].event_index == -1
    assert digest.attribution_confidence == "partial"


def test_model_switch_applies_to_next_increment(tmp_path):
    digest = parse(tmp_path, [turn("model-a"), prompt(), tokens(100, 40, 20),
                              turn("model-b"), tokens(180, 70, 35)])
    assert [r.model for r in digest.requests] == ["model-a", "model-b"]


def test_unproven_child_is_partial(tmp_path):
    digest = parse(tmp_path, [turn(), prompt(), tokens(100, 40, 20)], parent="parent")
    assert digest.parent_identity == ("codex", "parent")
    assert digest.attribution_confidence == "partial"


def test_inherited_prefix_is_removed_only_with_evidence(tmp_path):
    from usage_bridge.adapters.codex_usage import exclude_inherited_prefix

    parent = parse(tmp_path, [turn(), prompt(), tokens(100, 40, 20)])
    child = parse(tmp_path, [turn(), prompt(), tokens(100, 40, 20), tokens(180, 70, 35)], parent="s")
    result = exclude_inherited_prefix(child, parent)
    assert sum(r.input for r in result.requests) == 50
    assert sum(r.output for r in result.requests) == 15
