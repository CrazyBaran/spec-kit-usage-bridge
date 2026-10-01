from usage_bridge.yamlsub import parse_yaml


def test_nested_mappings_and_scalars():
    data, warns = parse_yaml('enabled: true\noutput:\n  dir: "{feature_dir}"\ncapture:\n  deadline_seconds: 12.5\n'
                             'log:\n  level: debug\nx: null\ny: ~\nn: 3\n')
    assert data == {"enabled": True, "output": {"dir": "{feature_dir}"}, "capture": {"deadline_seconds": 12.5},
                    "log": {"level": "debug"}, "x": None, "y": None, "n": 3}
    assert warns == []


def test_block_list_and_empty_flow_collections():
    data, _ = parse_yaml("transcripts:\n  extra_dirs:\n    - D:/a b\n    - '~/c'\npricing:\n  overrides: {}\nlst: []\n")
    assert data == {"transcripts": {"extra_dirs": ["D:/a b", "~/c"]}, "pricing": {"overrides": {}}, "lst": []}


def test_flow_mapping_of_scalars():
    data, _ = parse_yaml('pricing:\n  overrides:\n    "claude-opus-5-5": {input: 5.0, output: 25.0, cache_read: 0.5}\n')
    assert data["pricing"]["overrides"] == {"claude-opus-5-5": {"input": 5.0, "output": 25.0, "cache_read": 0.5}}


def test_comments_and_quoted_hash():
    assert parse_yaml("a: 'x # kept'  # dropped\n# full line\nb: \"y\"\n")[0] == {"a": "x # kept", "b": "y"}


def test_crlf_and_bom():
    data = parse_yaml("\ufeffenabled: false\r\nlog:\r\n  level: warning\r\n")[0]
    assert data == {"enabled": False, "log": {"level": "warning"}}


def test_unsupported_constructs_warn_and_skip():
    data, warns = parse_yaml("a: &anchor 1\nb: |\n  text\nc: 2\n---\nd: 3\n")
    assert data == {"c": 2} and len(warns) == 3 and all(w.startswith("line ") for w in warns)


def test_tab_indentation_is_rejected():
    data, warns = parse_yaml("a:\n\tb: 1\nc: 2\n")
    assert data == {"c": 2} and warns
