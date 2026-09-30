"""Layered configuration (spec §5.1): defaults ← committed file ← local file ← environment."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .yamlsub import parse_yaml

CONFIG_REL = Path(".specify/extensions/usage-bridge")
COMMITTED_FILE = "usage-bridge-config.yml"
LOCAL_FILE = "usage-bridge-config.local.yml"
ENV_PREFIX = "SPECKIT_USAGE_BRIDGE_"
MAX_DEADLINE_SECONDS = 15.0
LOG_LEVELS = ("error", "warning", "info", "debug")
ALIAS_WARNING = "author.alias is set in the committed config; move it to usage-bridge-config.local.yml."

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


@dataclass
class Config:
    enabled: bool = True
    output_dir: str = "{feature_dir}"
    author_alias: str = ""
    extra_dirs: list[str] = field(default_factory=list)
    pricing_overrides: dict[str, dict[str, float]] = field(default_factory=dict)
    prompt_previews: bool = False
    deadline_seconds: float = 15.0
    log_level: str = "info"
    warnings: list[str] = field(default_factory=list)


class _Invalid(ValueError):
    pass


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in _TRUE + _FALSE:
        return value.strip().lower() in _TRUE
    raise _Invalid(f"expected true or false, got {value!r}")


def _as_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    raise _Invalid(f"expected a string, got {value!r}")


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part for part in value.split(os.pathsep) if part]
    if isinstance(value, list) and all(isinstance(item, (str, int, float)) for item in value):
        return [str(item) for item in value]
    raise _Invalid(f"expected a list of paths, got {value!r}")


def _as_overrides(value: Any) -> dict[str, dict[str, float]]:
    if value is None:
        return {}
    if isinstance(value, dict) and all(isinstance(rates, dict) for rates in value.values()):
        return {str(model): dict(rates) for model, rates in value.items()}
    raise _Invalid("expected a mapping of model prefixes to {input, output, cache_read} rates")


def _as_seconds(value: Any) -> float:
    if isinstance(value, bool):
        raise _Invalid(f"expected a number of seconds, got {value!r}")
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        raise _Invalid(f"expected a number of seconds, got {value!r}") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise _Invalid(f"expected a positive number of seconds, got {value!r}")
    return seconds


def _as_level(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in LOG_LEVELS:
        return value.strip().lower()
    raise _Invalid(f"expected one of {', '.join(LOG_LEVELS)}, got {value!r}")


# (key path, Config attribute, converter, readable from the environment)
_FIELDS: tuple[tuple[str, str, Callable[[Any], Any], bool], ...] = (
    ("enabled", "enabled", _as_bool, True),
    ("output.dir", "output_dir", _as_str, True),
    ("author.alias", "author_alias", _as_str, True),
    ("transcripts.extra_dirs", "extra_dirs", _as_str_list, True),
    ("pricing.overrides", "pricing_overrides", _as_overrides, False),
    ("privacy.prompt_previews", "prompt_previews", _as_bool, True),
    ("capture.deadline_seconds", "deadline_seconds", _as_seconds, True),
    ("log.level", "log_level", _as_level, True),
)

_MISSING = object()


def _lookup(data: Mapping[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _read_file(path: Path, cfg: Config) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        cfg.warnings.append(f"{path.name}: cannot read ({exc})")
        return {}
    data, warnings = parse_yaml(text)
    cfg.warnings.extend(f"{path.name}: {warning}" for warning in warnings)
    return data


def _apply(cfg: Config, source: str, path: str, attr: str, convert: Callable[[Any], Any], value: Any) -> None:
    try:
        setattr(cfg, attr, convert(value))
    except _Invalid as exc:
        cfg.warnings.append(f"{source}: {path}: {exc}; using {getattr(cfg, attr)!r}")


def load_config(project: Path, env: Mapping[str, str]) -> Config:
    cfg = Config()
    directory = Path(project) / CONFIG_REL
    for name in (COMMITTED_FILE, LOCAL_FILE):
        data = _read_file(directory / name, cfg)
        for path, attr, convert, _ in _FIELDS:
            value = _lookup(data, path)
            if value is not _MISSING:
                _apply(cfg, name, path, attr, convert, value)
        if name == COMMITTED_FILE and _lookup(data, "author.alias") not in (_MISSING, None, ""):
            cfg.warnings.append(ALIAS_WARNING)
    for path, attr, convert, from_env in _FIELDS:
        variable = ENV_PREFIX + path.upper().replace(".", "_")
        if from_env and variable in env:
            _apply(cfg, variable, path, attr, convert, env[variable])
    cfg.deadline_seconds = min(cfg.deadline_seconds, MAX_DEADLINE_SECONDS)
    return cfg
