import os

from usage_bridge.config import CONFIG_REL, Config, load_config


def write_cfg(project, name, text):
    d = project / CONFIG_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def test_defaults_without_files(tmp_path):
    assert load_config(tmp_path, {}) == Config()


def test_layers_committed_local_env(tmp_path):
    write_cfg(tmp_path, "usage-bridge-config.yml", "log:\n  level: debug\ncapture:\n  deadline_seconds: 10\n")
    write_cfg(tmp_path, "usage-bridge-config.local.yml", "author:\n  alias: jb\nlog:\n  level: warning\n")
    cfg = load_config(tmp_path, {"SPECKIT_USAGE_BRIDGE_LOG_LEVEL": "error"})
    assert (cfg.log_level, cfg.deadline_seconds, cfg.author_alias) == ("error", 10.0, "jb")


def test_deadline_is_capped(tmp_path):
    write_cfg(tmp_path, "usage-bridge-config.yml", "capture:\n  deadline_seconds: 40\n")
    assert load_config(tmp_path, {}).deadline_seconds == 15.0


def test_env_booleans_and_lists(tmp_path):
    cfg = load_config(tmp_path, {"SPECKIT_USAGE_BRIDGE_ENABLED": "false",
                                 "SPECKIT_USAGE_BRIDGE_TRANSCRIPTS_EXTRA_DIRS": os.pathsep.join(["a", "b"]),
                                 "SPECKIT_USAGE_BRIDGE_PRIVACY_PROMPT_PREVIEWS": "1"})
    assert (cfg.enabled, cfg.extra_dirs, cfg.prompt_previews) == (False, ["a", "b"], True)


def test_alias_in_committed_file_warns(tmp_path):
    write_cfg(tmp_path, "usage-bridge-config.yml", "author:\n  alias: team\n")
    cfg = load_config(tmp_path, {})
    assert cfg.author_alias == "team" and any("author.alias" in w for w in cfg.warnings)


def test_pricing_overrides_are_file_only(tmp_path):
    write_cfg(tmp_path, "usage-bridge-config.yml", "pricing:\n  overrides:\n    m: {input: 5.0, output: 25.0}\n")
    cfg = load_config(tmp_path, {"SPECKIT_USAGE_BRIDGE_PRICING_OVERRIDES": "x"})
    assert cfg.pricing_overrides == {"m": {"input": 5.0, "output": 25.0}}


def test_bad_values_fall_back_with_warning(tmp_path):
    write_cfg(tmp_path, "usage-bridge-config.yml", "capture:\n  deadline_seconds: soon\nlog:\n  level: loud\n")
    cfg = load_config(tmp_path, {})
    assert (cfg.deadline_seconds, cfg.log_level) == (15.0, "info") and len(cfg.warnings) == 2
