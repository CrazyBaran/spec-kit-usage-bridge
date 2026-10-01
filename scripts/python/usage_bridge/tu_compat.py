"""The only door to the vendored token-usage module (spec §1.4).

Every upstream function Usage Bridge relies on is reached through these wrappers, so an upstream
change is adapted here and nowhere else. Upstream's ``warn()`` always prints to stderr; every call
below runs with stderr redirected into a sink whose lines ``drain_warnings()`` hands to our log —
the Stop hook must never write to stderr.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "token_usage"
_MODULE_NAME = "_ub_vendored_token_usage"
_MODULE: ModuleType | None = None
_SINK = io.StringIO()
_BUCKET_KEYS = ("input", "output", "cache_read", "cache_5m", "cache_1h")


class VendorError(RuntimeError):
    """The vendored token-usage files are missing or differ from VENDOR.json."""


@dataclass(frozen=True)
class Rates:
    """A resolved pricing table (USD per million tokens) and where it came from."""

    table: dict[str, dict[str, float]]
    label: str
    sha256: str
    warnings: tuple[str, ...] = ()


@contextlib.contextmanager
def _quiet() -> Iterator[None]:
    with contextlib.redirect_stderr(_SINK):
        yield


def drain_warnings() -> list[str]:
    """Return (and forget) everything upstream printed to stderr so far."""
    text = _SINK.getvalue()
    _SINK.seek(0)
    _SINK.truncate(0)
    return [line for line in text.splitlines() if line.strip()]


def vendored_info() -> dict:
    try:
        return json.loads((VENDOR_DIR / "VENDOR.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VendorError(f"cannot read {VENDOR_DIR / 'VENDOR.json'}: {exc}") from exc


def vendored_sha() -> str:
    """SHA-256 of the vendored token_usage.py (part of digest cache keys)."""
    try:
        return hashlib.sha256((VENDOR_DIR / "scripts" / "token_usage.py").read_bytes()).hexdigest()
    except OSError as exc:
        raise VendorError(f"missing vendored token_usage.py: {exc}") from exc


def module() -> ModuleType:
    """Load the vendored module once, after checking every file against VENDOR.json."""
    global _MODULE
    if _MODULE is None:
        for rel, digest in vendored_info().get("files", {}).items():
            path = VENDOR_DIR / rel
            try:
                actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise VendorError(f"missing vendored file {path}") from exc
            if actual != digest:
                raise VendorError(f"vendored file {rel} does not match VENDOR.json")
        source = VENDOR_DIR / "scripts" / "token_usage.py"
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, source)
        if spec is None or spec.loader is None:
            raise VendorError(f"cannot load {source}")
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = loaded
        with _quiet():
            spec.loader.exec_module(loaded)
        _MODULE = loaded
    return _MODULE


# -- transcript primitives -----------------------------------------------------------------------

def iter_entries(path: Path) -> Iterator[dict]:
    """JSON objects of a .jsonl transcript; undecodable or malformed lines are skipped."""
    mod = module()
    with _quiet():
        for entry in mod.iter_jsonl(path):
            if isinstance(entry, dict):
                yield entry


def is_prompt(entry: dict) -> bool:
    return bool(module().is_user_prompt(entry))


def prompt_text(entry: dict) -> str:
    return module().text_of((entry.get("message") or {}).get("content"))


def command_name(text: str) -> str | None:
    match = module().COMMAND_RE.search(text or "")
    return match.group(1).strip() if match else None


def normalize(usage: dict) -> dict[str, int]:
    return module().normalize_usage(usage)


def merge_max(into: dict[str, int], flat: dict[str, int]) -> None:
    module().max_flat(into, flat)


def agent_start(agent_file: Path, first_ts: str | None, meta: dict | None) -> str | None:
    mod = module()
    with _quiet():
        return mod._resolve_agent_ts(agent_file, first_ts, meta)


def projects_root() -> Path:
    return Path(module().projects_dir())


def oracle_segments(path: Path) -> list[dict]:
    """Upstream parse_session — used only by the reconciliation tests."""
    mod = module()
    with _quiet():
        return mod.parse_session(path)


# -- pricing -------------------------------------------------------------------------------------

def _number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _override_entry(rates: Any) -> dict[str, float] | None:
    if not isinstance(rates, Mapping) or not (_number(rates.get("input")) and _number(rates.get("output"))):
        return None
    entry = {"input": float(rates["input"]), "output": float(rates["output"])}
    if "cache_read" in rates:
        if not _number(rates["cache_read"]):
            return None
        entry["cache_read"] = float(rates["cache_read"])
    return entry


def load_rates(overrides: Mapping[str, Mapping[str, float]], runtime: Path) -> Rates:
    """Bundled rates plus team overrides; the personal token-usage overlay is never read."""
    mod = module()
    warnings: list[str] = []
    saved = {name: os.environ.get(name) for name in ("XDG_CONFIG_HOME", "TOKEN_USAGE_LEDGER_DIR")}
    os.environ["XDG_CONFIG_HOME"] = str(Path(runtime) / "no-overlay")
    os.environ["TOKEN_USAGE_LEDGER_DIR"] = str(Path(runtime) / "ledger")
    try:
        with _quiet():
            table = {key: dict(value) for key, value in mod.load_pricing(warnings).items()}
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    applied = False
    for model, rates in (overrides or {}).items():
        entry = _override_entry(rates)
        if entry is None:
            warnings.append(f"pricing override for {model!r} ignored: rates must be finite non-negative numbers "
                            "(input and output required)")
            continue
        table[str(model)] = entry
        applied = True
    digest = hashlib.sha256(json.dumps(table, sort_keys=True).encode("utf-8")).hexdigest()
    return Rates(table, "bundled+overrides" if applied else "bundled", digest, tuple(warnings))


def rate_of(model: str, rates: Rates) -> dict[str, float] | None:
    """Resolved USD/MTok rates for a model (longest-prefix match as upstream), or None."""
    mod = module()
    found = mod.rates_for(model, rates.table)
    if not found:
        return None
    return {"input": float(found["input"]), "output": float(found["output"]),
            "cache_read": float(mod.cache_read_rate(found))}


def _buckets(by_model: Mapping[str, Mapping[str, int]]) -> dict[str, dict[str, int]]:
    return {model: {key: int(bucket.get(key, 0)) for key in _BUCKET_KEYS} for model, bucket in by_model.items()}


def cost(by_model: Mapping[str, Mapping[str, int]], rates: Rates) -> float | None:
    """Upstream cost_usd over vendored-key buckets; None when no model is priceable."""
    return module().cost_usd(_buckets(by_model), rates.table)


def unpriced(by_model: Mapping[str, Mapping[str, int]], rates: Rates) -> list[str]:
    return module().unpriced_models(_buckets(by_model), rates.table)


@contextlib.contextmanager
def _cursor_environment(ledger_root: Path, data_root: Path | None):
    names = ("TOKEN_USAGE_LEDGER_DIR", "TOKEN_USAGE_CURSOR_DIR")
    saved = {name: os.environ.get(name) for name in names}
    os.environ["TOKEN_USAGE_LEDGER_DIR"] = str(ledger_root.parent)
    if data_root is not None:
        os.environ["TOKEN_USAGE_CURSOR_DIR"] = str(data_root)
    try:
        with _quiet():
            yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _cursor_worker_command() -> list[str]:
    return [sys.executable, "-B", str(Path(__file__).resolve().parent / "cursor_worker.py")]


def _cursor_bounded(request: dict[str, Any], timeout: float) -> Any:
    if timeout <= 0:
        raise TimeoutError("Cursor capture deadline reached")
    env = dict(os.environ)
    root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    try:
        result = subprocess.run(_cursor_worker_command(), input=json.dumps(request).encode("utf-8"),
                                capture_output=True, env=env, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Cursor source operation exceeded capture deadline") from exc
    if result.returncode:
        raise RuntimeError("Cursor source worker failed")
    return json.loads(result.stdout)


def cursor_sessions(project: Path, ledger_root: Path, data_root: Path | None,
                    timeout: float | None = None) -> list[object]:
    if timeout is not None:
        rows = _cursor_bounded({"operation": "discover", "project": str(project), "ledger": str(ledger_root),
                                "data": str(data_root) if data_root else None}, timeout)
        return [module().CursorSession(**row) for row in rows]
    # Vendor appends /cursor to its ledger root. Bridge storage is /cursor-ledgers/cursor.
    with _cursor_environment(ledger_root / "cursor", data_root):
        return list(module().get_runtime_adapter("cursor").iter_sessions(project_dir=project))


def cursor_parse(source: object, timeout: float | None = None) -> dict[str, Any]:
    if timeout is not None:
        fields = {key: str(getattr(source, key)) if getattr(source, key) is not None else None
                  for key in module().CursorSession.__slots__}
        return _cursor_bounded({"operation": "parse", "source": fields}, timeout)
    with _quiet():
        return module().get_runtime_adapter("cursor").parse(source)


def cursor_export(path: Path):
    with _quiet():
        return module().get_runtime_adapter("cursor").locate(str(path))
