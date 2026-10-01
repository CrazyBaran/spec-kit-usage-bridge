"""Reconciliation with upstream: our digest in upstream mode must equal parse_session (spec §8.3)."""

import pytest

from scenarios import ALL_SCENARIOS, files_for
from usage_bridge import tu_compat
from usage_bridge.digest import digest_session
from usage_bridge.phases import upstream_segments

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("name", sorted(ALL_SCENARIOS))
def test_upstream_mode_matches_parse_session(name, tmp_path):
    mains = ALL_SCENARIOS[name](tmp_path)
    assert mains, name
    for main in mains:
        ours = upstream_segments(digest_session(files_for(main)))
        theirs = [{"label": s["label"], "by_model": s["by_model"]} for s in tu_compat.oracle_segments(main)]
        assert ours == theirs, name
