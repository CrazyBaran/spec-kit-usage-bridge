import pytest

from release.context import promotion_context
from release.policy import ReleasePolicyError
from test_release_publication import OTHER, REPO, SHA, FakeAPI, candidate


def test_promotion_resolves_candidate_tag_and_current_branch_instead_of_target_commitish():
    api = FakeAPI()
    candidate(api)
    result = promotion_context(api, REPO, '0.2.2', 'v0.2.2-rc.1', SHA)
    assert result['status'] == 'ready'
    api.branch_sha = OTHER
    with pytest.raises(ReleasePolicyError):
        promotion_context(api, REPO, '0.2.2', 'v0.2.2-rc.1', SHA)


def test_candidate_metadata_cannot_hide_tag_pointing_at_old_commit():
    api = FakeAPI()
    candidate(api)
    api.releases[0]['target_commitish'] = SHA
    api.tags['v0.2.2-rc.1'] = OTHER
    with pytest.raises(ReleasePolicyError):
        promotion_context(api, REPO, '0.2.2', 'v0.2.2-rc.1', SHA)
