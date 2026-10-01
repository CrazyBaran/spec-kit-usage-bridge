# Usage Bridge v0.1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Spec Kit extension `usage-bridge` v0.1.0 — automatic per-phase, per-feature token and cost audit of
the SDD flow from Claude Code transcripts, written next to each spec.

**Architecture:** A stdlib-only Python package (`scripts/python/usage_bridge/`) runs on the Spec Kit runtime event
`stop`. One request-level pass per transcript (built on vendored token-usage primitives, `parse_session` kept as a test
oracle) feeds pure stages — phases → attribution → metrics → render — that write per-author JSON and a deterministic
merged `token-usage.md` per feature. Runtime state lives in `<git common dir>/usage-bridge/`.

**Tech Stack:** Python ≥ 3.9 stdlib (runtime); pytest, ruff, PyYAML (development only); git; uv/uvx for Spec Kit
v1.0.12 in integration tests; GitHub Actions.

**Spec:** [`docs/superpowers/specs/2026-09-29-usage-bridge-v0.1-design.md`](../specs/2026-09-29-usage-bridge-v0.1-design.md)
— every task implicitly includes the spec sections it cites. Where this plan and the spec disagree, stop and ask.

## Global Constraints

- Runtime code is **stdlib only**; package modules require Python ≥ 3.9; the three entrypoints must parse with the
  Python 3.6 grammar (`ast.parse(src, feature_version=(3, 6))`).
- Vendored token-usage = main **`f4078277e79c007993e0cb595bb95f924a2a8777`**, files byte-identical to upstream and never
  edited; only `usage_bridge/tu_compat.py` imports them; every vendored call runs with **stderr captured** (upstream
  `warn()` always prints to stderr).
- Capture on the hook path prints **nothing** to stdout/stderr and exits **0**; deadline = `min(capture.deadline_seconds,
  15)` seconds; the manifest's `stop` handler timeout is **30**.
- Committed outputs: `specs/<feature>/token-usage.md` and `specs/<feature>/token-usage/<author>.<machine>.json`
  (via `output.dir`, default `{feature_dir}`); no prompt text unless `privacy.prompt_previews: true`; no absolute or
  local paths.
- Schemas: `usage-bridge/feature-usage` v1 (per-author), `usage-bridge/feature-report` v1 and
  `usage-bridge/repo-report` v1 (stdout only).
- Generated files: UTF-8 without BOM, LF line endings, byte-deterministic for the same inputs. Timestamps are
  normalised to `YYYY-MM-DDTHH:MM:SS.mmmZ` (UTC) before any comparison.
- Runtime dir R = `<git -C W rev-parse --git-common-dir>/usage-bridge/`, fallback
  `.specify/extensions/usage-bridge/.runtime/`. Config: `.specify/extensions/usage-bridge/usage-bridge-config.yml` and
  `usage-bridge-config.local.yml`; env `SPECKIT_USAGE_BRIDGE_*`.
- `requires.speckit_version: ">=1.0.12"`; integration tests call
  `uvx --from git+https://github.com/github/spec-kit.git@v1.0.12 specify` (never the developer's global `specify`).
- Author = slug of `author.alias` → git `user.name` → OS user (≤ 40 chars, `[a-z0-9-]`); machine = first 6 hex of
  SHA-256 of the lower-cased host name.
- Git: implement on branch **`feat/v0.1.0`** in an isolated worktree stacked on `docs/v0.1-implementation-plan`; one
  commit per task; `git push` after each task; no PRs, merges, tags or releases without asking the user. End every
  commit message with the Co-Authored-By line your harness specifies.

## Model assignment (cheapest viable)

Easy = the plan pins the interface, the rules and the tests, so the implementer mostly transcribes. Judgment = edge
cases the tests only sample, cross-module data flow, or external tools. The main session verifies each task's claims
(test output, diff) before starting the next.

| Task | Implementer | Task reviewer | Why |
|---|---|---|---|
| 1 Dev harness and fixture builders | haiku | haiku | config files + builders with fixed shapes |
| 2 Vendoring and `tu_compat` | sonnet | sonnet | must read upstream code; stderr capture; pricing env |
| 3 `yamlsub` | haiku | haiku | fully specified grammar + tests |
| 4 `config` and `log` | haiku | haiku | layering rules pinned |
| 5 `timefmt`, `runtime`, `timeline` | haiku | haiku | small pure functions |
| 6 `paths` | sonnet | sonnet | git worktrees, Windows path semantics |
| 7 `discovery` | sonnet | sonnet | membership rules, recursive layout |
| 8 `digest` and cache | sonnet | sonnet | must mirror upstream request semantics |
| 9 `phases`, scenarios, oracle | sonnet | sonnet | core rules + reconciliation with upstream |
| 10 `attribution` | sonnet | sonnet | timeline/branch resolution edge cases |
| 11 `metrics` | sonnet | sonnet | formulas + session assembly |
| 12 `render`: JSON, formatting, writes | haiku | sonnet | pinned formats; atomic write reviewed carefully |
| 13 `render`: md and report views | sonnet | sonnet | many layout rules, golden output |
| 14 `pipeline` | sonnet | sonnet | orchestration, deadline, lock, worktrees |
| 15 `cli`: capture and report | haiku | sonnet | thin wiring over tested modules |
| 16 `checks` | haiku | sonnet | table-driven checks, exact texts |
| 17 Entrypoints, commands, manifest | haiku | haiku | exact copy from the spec |
| 18 Release builder | haiku | haiku | zip + catalog from pinned fields |
| 19 Spec Kit integration tests | sonnet | sonnet | external CLI behaviour on two OSes |
| 20 `update-vendor` | haiku | haiku | pinned archive flow |
| 21 CI and release workflows | haiku | haiku | YAML with pinned jobs |
| 22 Performance budgets | sonnet | sonnet | may need optimisation |
| 23 Reconcile helper | haiku | haiku | compares two known totals |
| 24 Documentation | haiku | sonnet | prose from the spec; reviewer checks accuracy |
| Final whole-branch review | — | opus | one pass on the most capable model before completion |

## Review Focus

1. **Files written by Windows tools** — `.specify/feature.json` with a UTF-8 BOM and `\` separators (PowerShell), config
   YAML with CRLF/BOM: parsed exactly like clean files. → Task 5 `test_active_feature_reads_feature_json_with_bom_and_backslashes`,
   Task 3 `test_crlf_and_bom`.
2. **Mixed timestamp formats** — `…12Z`, `…12.345Z`, `…+00:00` and epoch numbers from `.meta.json` must order
   chronologically (raw string comparison mis-orders them). → Task 5 `test_normalised_strings_sort_chronologically`,
   Task 8 `test_timestamps_normalised`.
3. **Non-ASCII and spaces in paths** (`C:\Users\Łukasz\my repo`) — slugs, membership and writes still work. →
   Task 6 `test_claude_slug_non_ascii`, Task 7 `test_non_ascii_repo_path`.
4. **A transcript still being written** while capture reads it (truncated last line) — no crash, the partial line is
   ignored. → Task 8 `test_malformed_and_truncated_lines_are_tolerated`.
5. **Feature directory renamed or deleted** after the timeline recorded it — runs fall back to branch/unattributed and
   no file is resurrected. → Task 10 `test_renamed_feature_dir_falls_back_to_branch`, Task 14
   `test_own_file_removed_when_no_runs`.

## Conventions

- `PYTEST` = `uv run --no-project --python 3.9 --with-requirements requirements-dev.txt python -m pytest`
- `RUFF` = `uv run --no-project --with-requirements requirements-dev.txt ruff check .`
- Every "Implement" step ends with `PYTEST <task tests> -q` green **and** `RUFF` clean; the commit step runs the whole
  suite once (`PYTEST -q -m "not integration and not perf"`).
- Tests import the package via `pythonpath = ["scripts/python", "tests"]` (pytest config from Task 1).
- Fixture transcripts are always built with `tests/builders.py` inside the hermetic projects root; never commit real
  transcripts.

## File map

| Path | Task |
|---|---|
| `pyproject.toml`, `requirements-dev.txt`, `.gitattributes`, `.extensionignore`, `.gitignore` (append), `tests/conftest.py`, `tests/builders.py`, `scripts/python/usage_bridge/__init__.py` | 1 |
| `scripts/python/vendor/token_usage/**`, `usage_bridge/tu_compat.py`, `THIRD_PARTY_NOTICES.md` | 2 |
| `usage_bridge/yamlsub.py` | 3 |
| `usage_bridge/config.py`, `usage_bridge/log.py` | 4 |
| `usage_bridge/timefmt.py`, `usage_bridge/runtime.py`, `usage_bridge/timeline.py` | 5 |
| `usage_bridge/paths.py` | 6 |
| `usage_bridge/discovery.py` | 7 |
| `usage_bridge/digest.py` | 8 |
| `usage_bridge/phases.py`, `tests/scenarios.py` | 9 |
| `usage_bridge/attribution.py` | 10 |
| `usage_bridge/metrics.py` | 11 |
| `usage_bridge/render.py` | 12, 13 |
| `usage_bridge/pipeline.py` | 14 |
| `usage_bridge/cli.py` | 15, 16 |
| `usage_bridge/checks.py` | 16 |
| `scripts/python/{capture,report,check}.py`, `commands/*.md`, `extension.yml`, `config-template.yml` | 17 |
| `tools/build_release.py` | 18 |
| `tests/integration/test_speckit.py` | 19 |
| `tools/update-vendor.py` | 20 |
| `.github/workflows/{ci,release}.yml` | 21 |
| `tests/test_perf.py` | 22 |
| `tools/reconcile.py` | 23 |
| `README.md`, `CHANGELOG.md`, `docs/limitations.md`, `docs/release.md` | 24 |

**Before Task 1** (main session): create the worktree per superpowers:using-git-worktrees — branch `feat/v0.1.0` from
`docs/v0.1-implementation-plan` — then `git push -u origin feat/v0.1.0`.

---

### Task 1: Dev harness and fixture builders

**Model:** implementer haiku · reviewer haiku

**Files:**
- Create: `pyproject.toml`, `requirements-dev.txt`, `.gitattributes`, `.extensionignore`, `tests/conftest.py`,
  `tests/builders.py`, `tests/test_harness.py`, `scripts/python/usage_bridge/__init__.py`
- Modify: `.gitignore` (append a section)

**Interfaces:**
- Produces:
  - `usage_bridge.__version__ = "0.1.0"`
  - fixture `hermetic_env` (autouse) → returns the temp home `Path`; fixture `update_golden` → `bool` (`--update-golden`)
  - `builders.projects_root() -> Path` (= `$TOKEN_USAGE_PROJECTS_DIR`), `builders.slug(path) -> str`
    (`re.sub(r"[^A-Za-z0-9]", "-", str(path))`)
  - `builders.make_repo(tmp: Path, name: str = "repo", features: Sequence[str] = ("001-login",), branch: str = "main") -> Path`
    — `git init -b <branch>`, one commit, creates `.specify/` and `specs/<f>/spec.md`
  - `builders.SessionBuilder(session_id: str, cwd: Path, branch: Optional[str] = "main", start: str = "2026-09-29T09:00:00.000Z", sidechain: bool = False)`
    with `tick(seconds=30) -> str`, `at(iso) -> None`, `set_branch(name) -> None`, `command(name, args="")`,
    `prompt(text)`, `reply(request_id, *, model="claude-opus-5-5", input=0, output=0, cache_read=0, cache_5m=0, cache_1h=0, skill=None, stop_reason="end_turn", chunks=1)`,
    `compact(trigger="auto", pre=967128, post=24252)`, `raw(line)`, `subagent(rel, *, agent_type="general-purpose", spawn_depth=1) -> SessionBuilder`
    (a child builder whose clock starts at the parent's current time), `write(root: Optional[Path] = None) -> Path`
    (returns the main transcript path), and `entries: List[dict]` (entries written so far, in order)

- [ ] **Step 1: Write the failing tests** in `tests/test_harness.py`

```python
def test_home_is_isolated(hermetic_env):
    assert Path.home() == hermetic_env

def test_token_usage_env_points_into_tmp(tmp_path):
    for var in ("TOKEN_USAGE_PROJECTS_DIR", "TOKEN_USAGE_LEDGER_DIR", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR"):
        assert Path(os.environ[var]).is_relative_to(tmp_path)

def test_package_version():
    import usage_bridge
    assert usage_bridge.__version__ == "0.1.0"

def test_builder_writes_claude_shaped_session(tmp_path):
    repo = make_repo(tmp_path)
    s = SessionBuilder("s1", cwd=repo, branch="001-login")
    s.command("/speckit-plan")
    s.reply("req_1", input=10, output=5, cache_read=100, cache_5m=20)
    path = s.write()
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert path.parent == projects_root() / slug(repo) and path.name == "s1.jsonl"
    assert "<command-name>/speckit-plan</command-name>" in lines[0]["message"]["content"]
    usage = lines[1]["message"]["usage"]
    assert lines[1]["requestId"] == "req_1" and usage["cache_creation"]["ephemeral_5m_input_tokens"] == 20
    assert usage["cache_creation_input_tokens"] == 20 and usage["input_tokens"] == 10
    assert all(x["gitBranch"] == "001-login" and x["cwd"] == str(repo) and x["sessionId"] == "s1" for x in lines)

def test_builder_streamed_chunks_share_request_id(tmp_path):
    s = SessionBuilder("s1", cwd=make_repo(tmp_path))
    s.reply("r1", output=50, chunks=3)
    lines = [json.loads(x) for x in s.write().read_text(encoding="utf-8").splitlines()]
    assert [x["requestId"] for x in lines] == ["r1"] * 3
    assert [x["message"]["usage"]["output_tokens"] for x in lines][-1] == 50

def test_builder_subagent_layout(tmp_path):
    s = SessionBuilder("s1", cwd=make_repo(tmp_path))
    child = s.subagent("workflows/w1/agent-b2", agent_type="Explore", spawn_depth=2)
    child.reply("rb", output=7, stop_reason="tool_use")
    main = s.write()
    agent = main.parent / "s1" / "subagents" / "workflows" / "w1" / "agent-b2.jsonl"
    meta = json.loads(agent.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert agent.exists() and meta["agentType"] == "Explore" and meta["spawnDepth"] == 2
    assert all(json.loads(x)["isSidechain"] is True for x in agent.read_text(encoding="utf-8").splitlines())
```

- [ ] **Step 2: Run** `PYTEST tests/test_harness.py -q` → Expected: FAIL (`ModuleNotFoundError: builders` / `usage_bridge`).

- [ ] **Step 3: Implement**
  - `requirements-dev.txt`: `pytest>=8.3`, `ruff==0.16.6`, `PyYAML>=6.0`.
  - `pyproject.toml`: `[tool.pytest.ini_options]` with `testpaths = ["tests"]`, `pythonpath = ["scripts/python", "tests"]`,
    `addopts = "-ra"`, markers `contract`, `integration`, `perf`; `[tool.ruff]` `target-version = "py39"`,
    `line-length = 120`, `extend-exclude = ["scripts/python/vendor"]`; `[tool.ruff.lint] select = ["E", "F", "W", "I", "B", "UP"]`.
  - `.gitattributes`: `* text=auto eol=lf` and `scripts/python/vendor/** -text`.
  - `.gitignore` append, with a comment that `specify extension add` copies this file into the installed folder:
    `*.local.yml`, `.runtime/`.
  - `.extensionignore`: `tests/`, `tools/`, `docs/`, `.github/`, `.superpowers/`, `.worktrees/`, `.claude/`, `.venv/`,
    `.pytest_cache/`, `.ruff_cache/`, `**/__pycache__/`, `pyproject.toml`, `requirements-dev.txt`.
  - `tests/conftest.py`: autouse `hermetic_env(tmp_path, monkeypatch)` sets `HOME` and `USERPROFILE` to `tmp/home`,
    `TOKEN_USAGE_PROJECTS_DIR=tmp/home/.claude/projects`, `TOKEN_USAGE_LEDGER_DIR=tmp/ledger`, `XDG_CONFIG_HOME=tmp/xdg`,
    `CLAUDE_CONFIG_DIR=tmp/home/.claude`, `GIT_CONFIG_GLOBAL=tmp/gitconfig` (user.name `Test Author`, email
    `test@example.invalid`, init.defaultBranch `main`), `GIT_CONFIG_NOSYSTEM=1`, and deletes every `SPECKIT_USAGE_BRIDGE_*`
    and `SPECIFY_FEATURE*` variable; `pytest_addoption` adds `--update-golden`.
  - `tests/builders.py`: entries carry `type`, `uuid`, `parentUuid`, `sessionId`, `cwd` (`str(cwd)`), `gitBranch`,
    `timestamp`, `version: "2.1.284"`, `userType: "external"`, `entrypoint: "cli"`, `isSidechain`. A command's content
    is `<command-message>{name without leading / or $} is running…</command-message>\n<command-name>{name}</command-name>\n<command-args>{args}</command-args>`.
    `reply()` writes `message = {id, model, role: "assistant", stop_reason, content: [text block] + [Skill tool_use
    {"id": f"toolu_{request_id}", "name": "Skill", "input": {"skill": skill}}] if skill, usage}`; usage =
    `{input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens: cache_5m + cache_1h,
    cache_creation: {ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}, service_tier: "standard", speed: "standard"}`;
    `chunks > 1` writes that many entries with the same `requestId`, output growing linearly to its final value.
    `compact()` writes a `system` entry `{subtype: "compact_boundary", compactMetadata: {trigger, preTokens, postTokens}}`
    followed by a user entry with `isCompactSummary: true`. Subagents are written to
    `<root>/<slug(cwd)>/<session>/subagents/<rel>.jsonl` plus `<rel>.meta.json`
    (`agentType`, `description`, `model`, `parentAgentId: null`, `spawnDepth`, `toolUseId: "toolu_<rel>"`).
  - `scripts/python/usage_bridge/__init__.py`: `__version__ = "0.1.0"`.

- [ ] **Step 4: Run** `PYTEST tests/test_harness.py -q && RUFF` → Expected: 6 passed, ruff clean.

- [ ] **Step 5: Commit and push**

```bash
git add pyproject.toml requirements-dev.txt .gitattributes .extensionignore .gitignore tests scripts/python/usage_bridge/__init__.py
git commit -m "chore: add dev harness, hermetic test env and transcript builders"
git push
```

---

### Task 2: Vendoring and `tu_compat`

**Model:** implementer sonnet · reviewer sonnet

**Files:**
- Create: `scripts/python/vendor/token_usage/{scripts/token_usage.py,data/pricing.json,LICENSE,VENDOR.json}`,
  `scripts/python/usage_bridge/tu_compat.py`, `THIRD_PARTY_NOTICES.md`, `tests/test_tu_compat.py`

**Interfaces:**
- Consumes: builders (Task 1).
- Produces (`usage_bridge.tu_compat`):
  - `VENDOR_DIR: Path`; `class VendorError(RuntimeError)`
  - `@dataclass(frozen=True) class Rates: table: Dict[str, Dict[str, float]]; label: str; sha256: str; warnings: Tuple[str, ...]`
  - `module() -> ModuleType`, `vendored_info() -> dict`, `vendored_sha() -> str` (sha256 hex of `token_usage.py`)
  - `iter_entries(path: Path) -> Iterator[dict]`, `is_prompt(entry: dict) -> bool`, `prompt_text(entry: dict) -> str`,
    `command_name(text: str) -> Optional[str]`
  - `normalize(usage: dict) -> Dict[str, int]` (keys `input, output, cache_read, cache_5m, cache_1h`),
    `merge_max(into: Dict[str, int], flat: Dict[str, int]) -> None`
  - `agent_start(agent_file: Path, first_ts: Optional[str], meta: Optional[dict]) -> Optional[str]`
  - `load_rates(overrides: Mapping[str, Mapping[str, float]], runtime: Path) -> Rates`,
    `rate_of(model: str, rates: Rates) -> Optional[Dict[str, float]]` (`input`, `output`, `cache_read` resolved),
    `cost(by_model: Mapping[str, Mapping[str, int]], rates: Rates) -> Optional[float]`,
    `unpriced(by_model, rates: Rates) -> List[str]` — buckets use the vendored keys above
  - `projects_root() -> Path`, `oracle_segments(path: Path) -> List[dict]`, `drain_warnings() -> List[str]`

- [ ] **Step 1: Vendor the files** (verbatim bytes; no editing)

```bash
C=f4078277e79c007993e0cb595bb95f924a2a8777; B=https://raw.githubusercontent.com/Wicked-Sick-Ltd/token-usage/$C; V=scripts/python/vendor/token_usage
mkdir -p $V/scripts $V/data
curl -fsSL $B/scripts/token_usage.py -o $V/scripts/token_usage.py
curl -fsSL $B/data/pricing.json -o $V/data/pricing.json
curl -fsSL $B/LICENSE -o $V/LICENSE
```

Write `VENDOR.json` = `{"repo": "https://github.com/Wicked-Sick-Ltd/token-usage", "ref": "main", "commit": "<C>",
"upstream_version": "0.6.1+unreleased-0.7", "files": {"scripts/token_usage.py": "sha256:<hex>", "data/pricing.json":
"sha256:<hex>", "LICENSE": "sha256:<hex>"}}` with the hashes of the downloaded bytes. Write `THIRD_PARTY_NOTICES.md`:
token-usage, repository URL, commit, "MIT License", "Copyright (c) 2026 Craig Fletcher", then the full upstream licence text.

- [ ] **Step 2: Write the failing tests** in `tests/test_tu_compat.py` (mark the module `pytestmark = pytest.mark.contract`)

```python
def test_vendored_hashes_match_vendor_json():
    info = tu_compat.vendored_info()
    assert info["commit"] == "f4078277e79c007993e0cb595bb95f924a2a8777"
    for rel, digest in info["files"].items():
        assert digest == "sha256:" + hashlib.sha256((tu_compat.VENDOR_DIR / rel).read_bytes()).hexdigest()

def test_tampered_vendor_raises(tmp_path, monkeypatch):
    fake = tmp_path / "vendor"; shutil.copytree(tu_compat.VENDOR_DIR, fake)
    (fake / "data" / "pricing.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(tu_compat, "VENDOR_DIR", fake); monkeypatch.setattr(tu_compat, "_MODULE", None)
    with pytest.raises(tu_compat.VendorError):
        tu_compat.module()

def test_iter_entries_skips_bad_lines(tmp_path):
    p = tmp_path / "t.jsonl"; p.write_text('{"a": 1}\n{bad\n{"b": 2}\n', encoding="utf-8")
    assert list(tu_compat.iter_entries(p)) == [{"a": 1}, {"b": 2}]

def test_undecodable_bytes_never_reach_stderr(tmp_path, capfd):
    p = tmp_path / "t.jsonl"; p.write_bytes(b'{"a": 1}\n\xff\xfe\n')
    assert list(tu_compat.iter_entries(p)) == [{"a": 1}]
    assert capfd.readouterr().err == ""
    assert any("undecodable" in w for w in tu_compat.drain_warnings())

def test_normalize_splits_cache_ttl_and_legacy_total():
    u = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 50,
         "cache_creation": {"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 30}}
    assert tu_compat.normalize(u) == {"input": 10, "output": 5, "cache_read": 100, "cache_5m": 20, "cache_1h": 30}
    assert tu_compat.normalize({"cache_creation_input_tokens": 40})["cache_5m"] == 40

def test_prompt_detection_and_command_name(tmp_path):
    s = SessionBuilder("s1", cwd=make_repo(tmp_path)); s.command("/speckit-plan"); s.prompt("more please")
    first, second = tu_compat.iter_entries(s.write())
    assert tu_compat.is_prompt(first) and tu_compat.command_name(tu_compat.prompt_text(first)) == "/speckit-plan"
    assert tu_compat.command_name(tu_compat.prompt_text(second)) is None
    assert not tu_compat.is_prompt({**first, "isMeta": True})

def test_merge_max_keeps_field_maxima():
    a = {"input": 1, "output": 5, "cache_read": 0, "cache_5m": 0, "cache_1h": 0}
    tu_compat.merge_max(a, {"input": 1, "output": 9, "cache_read": 3, "cache_5m": 0, "cache_1h": 0})
    assert a["output"] == 9 and a["cache_read"] == 3

def test_agent_start_prefers_first_ts_then_meta(tmp_path):
    f = tmp_path / "agent-a.jsonl"; f.write_text("", encoding="utf-8")
    assert tu_compat.agent_start(f, "2026-09-29T10:00:00.000Z", None) == "2026-09-29T10:00:00.000Z"
    assert tu_compat.agent_start(f, None, {"timestamp": 1790000000000}).startswith("2026-09-21T14:13:20")

def test_load_rates_ignores_personal_overlay(tmp_path):
    overlay = Path(os.environ["XDG_CONFIG_HOME"]) / "token-usage" / "pricing.json"
    overlay.parent.mkdir(parents=True); overlay.write_text('{"claude-opus-5-5": {"input": 999, "output": 999}}', encoding="utf-8")
    rates = tu_compat.load_rates({}, tmp_path / "rt")
    assert rates.label == "bundled" and tu_compat.rate_of("claude-opus-5-5", rates)["input"] != 999

def test_load_rates_applies_team_overrides(tmp_path):
    base = tu_compat.load_rates({}, tmp_path)
    rates = tu_compat.load_rates({"claude-test-1": {"input": 2.0, "output": 10.0}}, tmp_path)
    assert rates.label == "bundled+overrides" and rates.sha256 != base.sha256
    assert tu_compat.rate_of("claude-test-1", rates) == {"input": 2.0, "output": 10.0, "cache_read": pytest.approx(0.2)}

def test_invalid_override_is_skipped_with_warning(tmp_path):
    rates = tu_compat.load_rates({"claude-test-1": {"input": "cheap"}}, tmp_path)
    assert tu_compat.rate_of("claude-test-1", rates) is None and rates.warnings

def test_cost_matches_upstream_formula(tmp_path):
    rates = tu_compat.load_rates({"claude-test-1": {"input": 2.0, "output": 10.0}}, tmp_path)
    bucket = {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_5m": 1_000_000, "cache_1h": 1_000_000, "requests": 1}
    assert tu_compat.cost({"claude-test-1": bucket}, rates) == pytest.approx(2.0 + 2.5 + 4.0)
    assert tu_compat.cost({"mystery": bucket}, rates) is None and tu_compat.unpriced({"mystery": bucket}, rates) == ["mystery"]

def test_projects_root_honours_env():
    assert tu_compat.projects_root() == Path(os.environ["TOKEN_USAGE_PROJECTS_DIR"])

def test_oracle_segments_labels(tmp_path):
    s = SessionBuilder("s1", cwd=make_repo(tmp_path)); s.command("/speckit-plan"); s.reply("r1", output=3)
    assert [seg["label"] for seg in tu_compat.oracle_segments(s.write())] == ["/speckit-plan"]

def test_vendored_calls_write_nothing(tmp_path):
    tu_compat.load_rates({}, tmp_path / "rt")
    assert not Path(os.environ["TOKEN_USAGE_LEDGER_DIR"]).exists() and not (Path.home() / ".cache").exists()
```

- [ ] **Step 3: Run** `PYTEST tests/test_tu_compat.py -q` → Expected: FAIL (`ModuleNotFoundError: usage_bridge.tu_compat`).

- [ ] **Step 4: Implement `usage_bridge/tu_compat.py`**
  - Load `VENDOR_DIR / "scripts" / "token_usage.py"` once with `importlib.util.spec_from_file_location("_ub_vendored_token_usage", …)`
    after verifying every `VENDOR.json` hash (mismatch or missing file → `VendorError`); cache in `_MODULE`.
  - Wrap every vendored call in `contextlib.redirect_stderr(_SINK)` (a module-level `io.StringIO`); `drain_warnings()`
    returns the captured non-empty lines and clears the sink. `iter_entries` keeps the redirect active while iterating.
  - Map: `iter_entries`→`iter_jsonl`; `is_prompt`→`is_user_prompt`; `prompt_text(e)`→`text_of((e.get("message") or {}).get("content"))`;
    `command_name`→`COMMAND_RE.search(text).group(1).strip()`; `normalize`→`normalize_usage`; `merge_max`→`max_flat`;
    `agent_start`→`_resolve_agent_ts(path, first_ts, meta)`; `projects_root`→`projects_dir()`; `oracle_segments`→`parse_session`;
    `cost`/`unpriced`→`cost_usd`/`unpriced_models` over `rates.table`; `rate_of`→`rates_for` plus
    `cache_read = rates.get("cache_read", input * 0.1)`.
  - `load_rates`: call `load_pricing(warnings)` with `XDG_CONFIG_HOME` temporarily set to `runtime / "no-overlay"` (never
    created) and `TOKEN_USAGE_LEDGER_DIR` set to `runtime / "ledger"`, both restored afterwards; merge overrides whose
    `input` and `output` are numbers (optional numeric `cache_read`), skip others with a warning; `label` = `bundled` or
    `bundled+overrides`; `sha256` = hex digest of `json.dumps(table, sort_keys=True)`.

- [ ] **Step 5: Run** `PYTEST tests/test_tu_compat.py -q && RUFF` → Expected: all pass, ruff clean.

- [ ] **Step 6: Commit and push**

```bash
git add scripts/python/vendor scripts/python/usage_bridge/tu_compat.py THIRD_PARTY_NOTICES.md tests/test_tu_compat.py
git commit -m "feat: vendor token-usage f407827 behind tu_compat"
git push
```

---

### Task 3: `yamlsub` — stdlib YAML subset

**Model:** implementer haiku · reviewer haiku

**Files:** Create `scripts/python/usage_bridge/yamlsub.py`, `tests/test_yamlsub.py`

**Interfaces:**
- Produces: `parse_yaml(text: str) -> Tuple[Dict[str, Any], List[str]]` — mapping plus warnings (each warning names its
  line as `line N: …`). Supported subset = spec §5.2.

- [ ] **Step 1: Write the failing tests**

```python
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
    assert parse_yaml("\ufeffenabled: false\r\nlog:\r\n  level: warning\r\n")[0] == {"enabled": False, "log": {"level": "warning"}}

def test_unsupported_constructs_warn_and_skip():
    data, warns = parse_yaml("a: &anchor 1\nb: |\n  text\nc: 2\n---\nd: 3\n")
    assert data == {"c": 2} and len(warns) == 3 and all(w.startswith("line ") for w in warns)

def test_tab_indentation_is_rejected():
    data, warns = parse_yaml("a:\n\tb: 1\nc: 2\n")
    assert data == {"c": 2} and warns
```

- [ ] **Step 2: Run** `PYTEST tests/test_yamlsub.py -q` → Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `parse_yaml`** — strip a leading BOM, split lines on `\r?\n`, drop comments outside quotes,
  build block mappings from space indentation (a key with no value opens a nested block: mapping or `- ` list);
  scalars: `true/false`, `null/~`, int, float, quoted strings (single quotes double `''` as escape), else plain string.
  Anchors/aliases (`&`, `*`), block scalars (`|`, `>`), tabs in indentation and nested flow collections produce one
  warning each and the affected key is skipped (with its indented block). A second `---` document ends parsing with one
  warning.

- [ ] **Step 4: Run** `PYTEST tests/test_yamlsub.py -q && RUFF` → Expected: 7 passed.

- [ ] **Step 5: Commit and push** — `git add scripts/python/usage_bridge/yamlsub.py tests/test_yamlsub.py` ·
  `git commit -m "feat: add stdlib YAML subset parser"` · `git push`

---

### Task 4: `config` and `log`

**Model:** implementer haiku · reviewer haiku

**Files:** Create `scripts/python/usage_bridge/config.py`, `scripts/python/usage_bridge/log.py`, `tests/test_config.py`,
`tests/test_log.py`

**Interfaces:**
- Consumes: `parse_yaml` (Task 3).
- Produces:
  - `CONFIG_REL = Path(".specify/extensions/usage-bridge")`, `MAX_DEADLINE_SECONDS = 15.0`
  - `@dataclass class Config: enabled: bool = True; output_dir: str = "{feature_dir}"; author_alias: str = ""; extra_dirs: List[str] = []; pricing_overrides: Dict[str, Dict[str, float]] = {}; prompt_previews: bool = False; deadline_seconds: float = 15.0; log_level: str = "info"; warnings: List[str] = []`
    (mutable defaults via `field(default_factory=…)`)
  - `load_config(project: Path, env: Mapping[str, str]) -> Config`
  - `get_logger(runtime: Path, level: str) -> logging.Logger` — logger `usage_bridge`, file `runtime/logs/usage-bridge.log`

- [ ] **Step 1: Write the failing tests**

```python
def write_cfg(project, name, text):
    d = project / CONFIG_REL; d.mkdir(parents=True, exist_ok=True); (d / name).write_text(text, encoding="utf-8")

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

def test_logger_writes_only_to_file(tmp_path, capfd):
    get_logger(tmp_path, "info").info("hello")
    assert "hello" in (tmp_path / "logs" / "usage-bridge.log").read_text(encoding="utf-8")
    assert capfd.readouterr() == ("", "")

def test_logger_rotates(tmp_path):
    log = get_logger(tmp_path, "info")
    for _ in range(3000):
        log.info("x" * 500)
    assert (tmp_path / "logs" / "usage-bridge.log.1").exists()
```

- [ ] **Step 2: Run** `PYTEST tests/test_config.py tests/test_log.py -q` → Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**
  - `load_config`: defaults ← committed ← local ← env. Key paths: `enabled`, `output.dir`, `author.alias`,
    `transcripts.extra_dirs`, `pricing.overrides`, `privacy.prompt_previews`, `capture.deadline_seconds`, `log.level`
    (`error|warning|info|debug`). Env name = `SPECKIT_USAGE_BRIDGE_` + key path upper-cased with `.` → `_`; booleans
    accept `1/true/yes/on` and `0/false/no/off`; `TRANSCRIPTS_EXTRA_DIRS` splits on `os.pathsep`; `pricing.overrides` is
    never read from env. Invalid values keep the default and add a warning naming the key; `yamlsub` warnings are
    copied into `Config.warnings`; `deadline_seconds = min(value, MAX_DEADLINE_SECONDS)`.
  - `get_logger`: `RotatingFileHandler(maxBytes=1_000_000, backupCount=2, encoding="utf-8")`, format
    `%(asctime)s %(levelname)s %(message)s`, `propagate = False`, no stream handler; repeated calls reuse the handler.

- [ ] **Step 4: Run** `PYTEST tests/test_config.py tests/test_log.py -q && RUFF` → Expected: 9 passed.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add layered config and rotating log"` · `git push`

---

### Task 5: `timefmt`, `runtime`, `timeline`

**Model:** implementer haiku · reviewer haiku

**Files:** Create `usage_bridge/timefmt.py`, `usage_bridge/runtime.py`, `usage_bridge/timeline.py`, `tests/test_timefmt.py`,
`tests/test_runtime.py`, `tests/test_timeline.py`

**Interfaces:**
- Produces:
  - `timefmt.norm_ts(value: Any) -> Optional[str]` → `YYYY-MM-DDTHH:MM:SS.mmmZ`; accepts ISO strings with `Z` or an
    offset, with or without fractions, and epoch seconds/milliseconds (> 1e11 = ms); anything else → `None`.
    `timefmt.parse_ts(value: str) -> datetime` (aware UTC), `timefmt.iso(dt: datetime) -> str`.
  - `@dataclass(frozen=True) class Detected: kind: str; payload: Dict[str, Any]` and `runtime.detect(raw: str) -> Detected`
    (kinds `claude | cursor | manual | unknown`).
  - `@dataclass(frozen=True) class TimelineEntry: ts: str; session_id: str; work_root: str; feature_dir: Optional[str]; feature_source: str; branch: Optional[str]`
  - `timeline.active_feature(work: Path, env: Mapping[str, str]) -> Tuple[Optional[str], str]` (relative POSIX dir,
    source `env|feature.json|none`), `timeline.make_entry(session_id, work, env, branch, now) -> TimelineEntry`,
    `timeline.append(runtime: Path, entry) -> None`, `timeline.read(runtime: Path) -> List[TimelineEntry]`,
    `timeline.by_session(entries) -> Dict[str, List[TimelineEntry]]` (each list sorted by `ts`)

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("raw,expected", [
    ("2026-09-29T10:40:12Z", "2026-09-29T10:40:12.000Z"),
    ("2026-09-29T10:40:12.345Z", "2026-09-29T10:40:12.345Z"),
    ("2026-09-29T12:40:12.345+02:00", "2026-09-29T10:40:12.345Z"),
    ("2026-09-29T10:40:12.345678+00:00", "2026-09-29T10:40:12.345Z"),
    (1790000000, "2026-09-21T14:13:20.000Z"), (1790000000000, "2026-09-21T14:13:20.000Z"),
    ("garbage", None), (None, None)])
def test_norm_ts(raw, expected):
    assert norm_ts(raw) == expected

def test_normalised_strings_sort_chronologically():
    raw = ["2026-09-29T10:40:12Z", "2026-09-29T10:40:11.999Z", "2026-09-29T10:40:12.345+00:00"]
    assert sorted(map(norm_ts, raw)) == ["2026-09-29T10:40:11.999Z", "2026-09-29T10:40:12.000Z", "2026-09-29T10:40:12.345Z"]

CLAUDE = '{"session_id":"s1","transcript_path":"C:/p/s1.jsonl","cwd":"C:/r","hook_event_name":"Stop"}'
@pytest.mark.parametrize("raw,kind", [
    (CLAUDE, "claude"), ("\ufeff" + CLAUDE, "claude"), ('{"conversation_id":"c","generation_id":"g"}', "cursor"),
    ("", "manual"), ("  \n", "manual"), ("{}", "manual"),
    ("not json", "unknown"), ("[1, 2]", "unknown"), ('{"session_id": 5, "transcript_path": "x"}', "unknown")])
def test_detect(raw, kind):
    assert detect(raw).kind == kind

def test_active_feature_prefers_env(tmp_path):
    (tmp_path / ".specify").mkdir(); (tmp_path / ".specify" / "feature.json").write_text('{"feature_directory": "specs/001-a"}', encoding="utf-8")
    assert active_feature(tmp_path, {"SPECIFY_FEATURE_DIRECTORY": str(tmp_path / "specs" / "002-b")}) == ("specs/002-b", "env")

def test_active_feature_reads_feature_json_with_bom_and_backslashes(tmp_path):
    (tmp_path / ".specify").mkdir()
    (tmp_path / ".specify" / "feature.json").write_bytes(codecs.BOM_UTF8 + b'{"feature_directory": "specs\\\\003-c"}')
    assert active_feature(tmp_path, {}) == ("specs/003-c", "feature.json")

def test_active_feature_absolute_inside_work_and_none(tmp_path):
    (tmp_path / ".specify").mkdir()
    (tmp_path / ".specify" / "feature.json").write_text(json.dumps({"feature_directory": str(tmp_path / "specs" / "004-d")}), encoding="utf-8")
    assert active_feature(tmp_path, {}) == ("specs/004-d", "feature.json")
    assert active_feature(tmp_path / "empty", {}) == (None, "none")

def test_append_read_roundtrip_skips_garbage(tmp_path):
    now = datetime(2026, 9, 29, 10, 40, 12, 345000, tzinfo=timezone.utc)
    e = make_entry("s1", tmp_path, {}, "001-login", now)
    append(tmp_path, e)
    with (tmp_path / "timeline.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{garbage\n")
    append(tmp_path, make_entry("s2", tmp_path, {}, None, now))
    assert [x.session_id for x in read(tmp_path)] == ["s1", "s2"] and e.ts == "2026-09-29T10:40:12.345Z"

def test_by_session_sorts(tmp_path):
    a = TimelineEntry("2026-09-29T10:05:00.000Z", "s1", "w", None, "none", None)
    b = TimelineEntry("2026-09-29T10:01:00.000Z", "s1", "w", None, "none", None)
    assert by_session([a, b])["s1"] == [b, a]
```

- [ ] **Step 2: Run** `PYTEST tests/test_timefmt.py tests/test_runtime.py tests/test_timeline.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — `detect` strips a BOM and whitespace; claude requires a JSON object with string
  `transcript_path` and `session_id`; cursor = object with `conversation_id` or `generation_id`; empty/`{}` → manual.
  `active_feature` reads `feature.json` with `encoding="utf-8-sig"`, converts `\` to `/`, makes absolute paths
  relative to `work` (outside `work` → `(None, "none")`). `append` writes `json.dumps({"v": 1, **asdict(entry)}) + "\n"`
  with a single `write()` in append mode (creates the file); `read` skips undecodable/invalid lines.

- [ ] **Step 4: Run** the three test files `-q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add timestamp normalisation, runtime detection and timeline"` · `git push`

---

### Task 6: `paths`

**Model:** implementer sonnet · reviewer sonnet

**Files:** Create `usage_bridge/paths.py`, `tests/test_paths.py`

**Interfaces:**
- Consumes: builders `make_repo`, `slug`.
- Produces: `claude_slug(path) -> str`, `slugify(text: str, max_len: int = 40) -> str`,
  `project_root(cwd: Path) -> Optional[Path]`, `git(args: Sequence[str], cwd: Path, timeout: float = 5.0) -> Optional[str]`,
  `worktrees(project: Path) -> List[Path]`, `work_root(payload_cwd: Optional[str], project: Path) -> Path`,
  `runtime_dir(work: Path, project: Path) -> Path` (creates it), `current_branch(work: Path) -> Optional[str]`,
  `git_user_name(work: Path) -> Optional[str]`, `author_slug(alias: str, git_name: Optional[str], os_user: str) -> str`,
  `machine_id(hostname: str) -> str`, `same_path(a, b) -> bool`, `is_inside(child, roots: Iterable[Path]) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
def test_claude_slug_matches_observed_names():
    assert claude_slug(PureWindowsPath(r"D:\spec-kit-usage-bridge")) == "D--spec-kit-usage-bridge"
    assert claude_slug(PureWindowsPath(r"D:\socialschools-spec-store\.claude\skills")) == "D--socialschools-spec-store--claude-skills"
    assert claude_slug(PurePosixPath("/home/a/my repo")) == "-home-a-my-repo"

def test_claude_slug_non_ascii():
    assert claude_slug(PureWindowsPath(r"C:\Users\Łukasz\proj")) == "C--Users--ukasz-proj"

def test_slug_and_author_precedence():
    assert slugify("  Jakub Baranowski!! ") == "jakub-baranowski" and len(slugify("x" * 99)) == 40
    assert author_slug("JB", "Git Name", "os") == "jb"
    assert author_slug("", "Git Name", "os") == "git-name"
    assert author_slug("", None, "cr4zy") == "cr4zy" and author_slug("", "ŁŁ", "") == "unknown"

def test_machine_id():
    assert machine_id("JAKUB-PC") == machine_id("jakub-pc") and re.fullmatch(r"[0-9a-f]{6}", machine_id("x"))

def test_project_root_walks_up(tmp_path):
    (tmp_path / ".specify").mkdir(); sub = tmp_path / "a" / "b"; sub.mkdir(parents=True)
    assert project_root(sub) == tmp_path

def test_worktrees_work_root_and_runtime_dir(tmp_path):
    repo = make_repo(tmp_path); wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt), "-b", "002-x"], check=True, capture_output=True)
    assert {p.name for p in worktrees(repo)} == {"repo", "wt"}
    assert same_path(work_root(str(wt / "sub"), repo), wt)
    assert same_path(work_root(str(tmp_path / "elsewhere"), repo), repo) and same_path(work_root(None, repo), repo)
    assert same_path(runtime_dir(wt, repo), repo / ".git" / "usage-bridge") and (repo / ".git" / "usage-bridge").is_dir()

def test_runtime_dir_without_git(tmp_path):
    (tmp_path / ".specify").mkdir()
    assert same_path(runtime_dir(tmp_path, tmp_path), tmp_path / ".specify" / "extensions" / "usage-bridge" / ".runtime")

def test_branch_and_user(tmp_path):
    repo = make_repo(tmp_path)
    assert current_branch(repo) == "main" and git_user_name(repo) == "Test Author"
    subprocess.run(["git", "-C", str(repo), "checkout", "--detach"], check=True, capture_output=True)
    assert current_branch(repo) is None

def test_git_missing_is_tolerated(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert git(["status"], tmp_path) is None and worktrees(tmp_path) == []

@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths")
def test_is_inside_case_insensitive_on_windows():
    assert is_inside(r"d:\REPO\x", [Path(r"D:\repo")]) and not is_inside(r"D:\repo-other", [Path(r"D:\repo")])
```

- [ ] **Step 2: Run** `PYTEST tests/test_paths.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — `claude_slug` = `re.sub(r"[^A-Za-z0-9]", "-", str(path))`. `git()` runs
  `["git", *args]` with `cwd`, `timeout`, `capture_output`, `text=True, encoding="utf-8"`; returns stripped stdout or
  `None` on non-zero exit / `OSError` / timeout. `worktrees` parses `git worktree list --porcelain` `worktree <path>`
  lines. `work_root` = `git -C <cwd> rev-parse --show-toplevel` if it `same_path`s P or a worktree, else P.
  `runtime_dir` = `(<work> / <git rev-parse --git-common-dir>).resolve() / "usage-bridge"`, fallback per Global
  Constraints. `same_path`/`is_inside` compare `os.path.normcase(os.path.abspath(...))` with a separator-aware prefix.
  `author_slug` falls back to `"unknown"` when every candidate slugs to empty.

- [ ] **Step 4: Run** `PYTEST tests/test_paths.py -q && RUFF` → Expected: all pass (the Windows-only test skips elsewhere).

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add path, git and identity helpers"` · `git push`

---

### Task 7: `discovery`

**Model:** implementer sonnet · reviewer sonnet

**Files:** Create `usage_bridge/discovery.py`, `tests/test_discovery.py`

**Interfaces:**
- Consumes: `paths.claude_slug`, `paths.is_inside`, `paths.same_path`; `tu_compat.iter_entries`, `tu_compat.projects_root`.
- Produces:
  - `@dataclass(frozen=True) class SubagentFile: path: Path; meta: Optional[Path]`
  - `@dataclass(frozen=True) class SessionFiles: session_id: str; main: Path; subagents: Tuple[SubagentFile, ...]` with
    `key() -> List[Tuple[str, int, int]]` (`(str(path), size, mtime_ns)` for main then each subagent, sorted)
  - `projects_roots(payload: Mapping[str, Any], env: Mapping[str, str]) -> List[Path]`
  - `session_cwd(main: Path, max_lines: int = 50) -> Optional[str]`
  - `discover(checkouts: Sequence[Path], roots: Sequence[Path], extra_dirs: Sequence[Path]) -> List[SessionFiles]`
    (sorted by `str(main)`)

- [ ] **Step 1: Write the failing tests**

```python
def ids(found): return [s.session_id for s in found]

def test_repo_sessions_found_and_prefix_collision_rejected(tmp_path):
    repo = make_repo(tmp_path, "spec-kit"); other = make_repo(tmp_path, "spec-kit-usage-bridge")
    for sid, cwd in (("s1", repo), ("s2", other)):
        b = SessionBuilder(sid, cwd=cwd); b.reply(f"r-{sid}", output=1); b.write()
    assert ids(discover([repo], [projects_root()], [])) == ["s1"]

def test_subdir_and_external_worktree_sessions(tmp_path):
    repo = make_repo(tmp_path); wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt), "-b", "002-x"], check=True, capture_output=True)
    (repo / "sub").mkdir()
    for sid, cwd in (("a", repo / "sub"), ("b", wt)):
        b = SessionBuilder(sid, cwd=cwd); b.reply(f"r{sid}", output=1); b.write()
    assert ids(discover([repo, wt], [projects_root()], [])) == ["a", "b"]

def test_worktree_session_started_in_main_checkout(tmp_path):
    repo = make_repo(tmp_path); wt = tmp_path / "wt"; wt.mkdir()
    b = SessionBuilder("c", cwd=wt); b.reply("rc", output=1)
    b.write(projects_root())                       # written under slug(wt) …
    (projects_root() / slug(wt)).rename(projects_root() / slug(repo))   # … moved to the main checkout's folder
    assert ids(discover([repo, wt], [projects_root()], [])) == ["c"]

def test_extra_dirs_skip_membership(tmp_path):
    repo = make_repo(tmp_path); elsewhere = make_repo(tmp_path, "clone")
    b = SessionBuilder("x", cwd=elsewhere); b.reply("rx", output=1); main = b.write()
    assert ids(discover([repo], [projects_root()], [main.parent])) == ["x"]

def test_recursive_subagents_with_meta(tmp_path):
    b = SessionBuilder("s1", cwd=make_repo(tmp_path)); b.reply("r1", output=1)
    b.subagent("agent-a1").reply("ra", output=1); b.subagent("workflows/w1/agent-b2").reply("rb", output=1)
    b.write()
    (found,) = discover([tmp_path / "repo"], [projects_root()], [])
    assert sorted(p.path.name for p in found.subagents) == ["agent-a1.jsonl", "agent-b2.jsonl"]
    assert all(p.meta is not None and p.meta.exists() for p in found.subagents)

def test_projects_roots_from_payload_and_env(tmp_path):
    root = projects_root(); (root / "d").mkdir(parents=True)
    roots = projects_roots({"transcript_path": str(root / "d" / "s.jsonl")}, dict(os.environ))
    assert roots[0] == root and len(roots) == len({str(r).lower() for r in roots})

def test_non_ascii_repo_path(tmp_path):
    repo = make_repo(tmp_path, "łukasz repo")
    b = SessionBuilder("s1", cwd=repo); b.reply("r1", output=1); b.write()
    assert ids(discover([repo], [projects_root()], [])) == ["s1"]

def test_key_changes_when_subagent_grows(tmp_path):
    b = SessionBuilder("s1", cwd=make_repo(tmp_path)); b.reply("r1", output=1); child = b.subagent("agent-a1")
    child.reply("ra", output=1); b.write()
    (f1,) = discover([tmp_path / "repo"], [projects_root()], [])
    with f1.subagents[0].path.open("a", encoding="utf-8") as fh:
        fh.write("{}\n")
    (f2,) = discover([tmp_path / "repo"], [projects_root()], [])
    assert f1.key() != f2.key()
```

- [ ] **Step 2: Run** `PYTEST tests/test_discovery.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — `projects_roots`: payload `transcript_path` grandparent (when present), `tu_compat.projects_root()`,
  `$CLAUDE_CONFIG_DIR/projects`; keep existing dirs, dedup with `same_path`, preserve order. Candidates: every dir in
  each root whose name equals `claude_slug(c)` or starts with `claude_slug(c) + "-"` for `c` in checkouts. For each
  `*.jsonl` in a candidate, keep it if `session_cwd` is inside any checkout (`is_inside`); files in `extra_dirs` are kept
  without the check. `session_cwd` returns the first `cwd` string among the first `max_lines` entries. Subagents:
  `<dir>/<stem>/subagents/**/agent-*.jsonl` (`rglob`), meta = sibling `.meta.json` if it exists.

- [ ] **Step 4: Run** `PYTEST tests/test_discovery.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: discover this repository's Claude transcripts"` · `git push`

---

### Task 8: `digest` and cache

**Model:** implementer sonnet · reviewer sonnet

**Files:** Create `usage_bridge/digest.py`, `tests/test_digest.py`

**Interfaces:**
- Consumes: `SessionFiles` (Task 7); `tu_compat.iter_entries, is_prompt, prompt_text, command_name, normalize, merge_max, agent_start`;
  `timefmt.norm_ts`.
- Produces (all dataclasses with `to_json() -> dict` and `from_json(d) -> Self`):
  - `Event(kind: str, ts: Optional[str], name: Optional[str] = None, trigger: Optional[str] = None, pre_tokens: Optional[int] = None, post_tokens: Optional[int] = None, prompt: Optional[str] = None)`
    — kinds `command | prompt | skill | compact`
  - `Request(request_id: str, ts: Optional[str], model: str, input: int, output: int, cache_read: int, cache_5m: int, cache_1h: int, event_index: int)`
    — `event_index` = index of the last event before the request's first appearance, `-1` if none
  - `SubagentDigest(rel_path: str, agent_type: str, spawn_depth: int, first_ts, last_ts, start_ts: Optional[str], finished: bool, requests: List[Request])`
  - `SessionDigest(session_id: str, main_path: str, first_ts, last_ts, last_main_ts, cwds: List[str], branches: List[Tuple[Optional[str], Optional[str]]], events: List[Event], requests: List[Request], subagents: List[SubagentDigest])`
  - `DIGEST_VERSION = 1`; `digest_session(files: SessionFiles, keep_previews: bool = False) -> SessionDigest`
  - `DigestCache(runtime: Path, vendored_sha: str)` with `load(files, keep_previews) -> Optional[SessionDigest]` and
    `store(files, keep_previews, digest) -> None` (file `runtime/cache/<sha1(str(main))>.json`)

- [ ] **Step 1: Write the failing tests**

```python
def files_of(repo): return discover([repo], [projects_root()], [])[0]

def test_events_and_requests_in_order(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo)
    b.prompt("hi"); b.command("/speckit-plan"); b.reply("r1", output=5, skill="speckit-git-commit"); b.reply("r2", output=6); b.write()
    d = digest_session(files_of(repo))
    assert [e.kind for e in d.events] == ["prompt", "command", "skill"]
    assert [(r.request_id, r.event_index) for r in d.requests] == [("r1", 2), ("r2", 2)]

def test_streamed_duplicates_take_field_maxima(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo); b.reply("r1", output=50, cache_read=7, chunks=3); b.write()
    (r,) = digest_session(files_of(repo)).requests
    assert (r.output, r.cache_read) == (50, 7)

def test_requests_without_id_count_per_entry(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo); b.reply(None, output=1); b.reply(None, output=2); b.write()
    reqs = digest_session(files_of(repo)).requests
    assert [r.output for r in reqs] == [1, 2] and all(r.request_id.startswith("noreq:") for r in reqs)

def test_compaction_event(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo); b.compact("manual", 493564, 29942); b.write()
    (e,) = [e for e in digest_session(files_of(repo)).events if e.kind == "compact"]
    assert (e.trigger, e.pre_tokens, e.post_tokens) == ("manual", 493564, 29942)

def test_subagents_flat_and_nested(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo); b.reply("r1", output=1)
    b.subagent("agent-a1").reply("ra", output=2)
    b.subagent("workflows/w1/agent-b2", spawn_depth=2).reply("rb", output=3, stop_reason="tool_use"); b.write()
    subs = sorted(digest_session(files_of(repo)).subagents, key=lambda s: s.rel_path)
    assert [(s.rel_path, s.finished, s.spawn_depth) for s in subs] == [
        ("agent-a1.jsonl", True, 1), ("workflows/w1/agent-b2.jsonl", False, 2)]
    assert subs[0].start_ts == subs[0].first_ts

def test_malformed_and_truncated_lines_are_tolerated(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo)
    b.reply("r1", output=1); b.raw("{not json"); b.reply("r2", output=2)
    b.raw('{"type": "assistant", "requestId": "r9", "message": {"usa'); b.write()
    assert [r.request_id for r in digest_session(files_of(repo)).requests] == ["r1", "r2"]

def test_branch_changes_and_cwds(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo, branch="main")
    b.reply("r1", output=1); b.set_branch("001-login"); b.reply("r2", output=1); b.write()
    d = digest_session(files_of(repo))
    assert [br for _, br in d.branches] == ["main", "001-login"] and d.cwds == [str(repo)]

def test_previews_only_when_enabled(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo); b.prompt("x" * 300); b.reply("r1", output=1); b.write()
    assert digest_session(files_of(repo)).events[0].prompt is None
    assert digest_session(files_of(repo), keep_previews=True).events[0].prompt == "x" * 120

def test_timestamps_normalised(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo); b.at("2026-09-29T10:40:12Z"); b.reply("r1", output=1); b.write()
    assert digest_session(files_of(repo)).requests[0].ts == "2026-09-29T10:40:12.000Z"

def test_cache_roundtrip_and_invalidation(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo); b.reply("r1", output=1); main = b.write()
    files = files_of(repo); d = digest_session(files); cache = DigestCache(tmp_path / "rt", "sha-a")
    cache.store(files, False, d)
    assert cache.load(files, False).to_json() == d.to_json()
    assert cache.load(files, True) is None and DigestCache(tmp_path / "rt", "sha-b").load(files, False) is None
    with main.open("a", encoding="utf-8") as fh:
        fh.write("{}\n")
    assert cache.load(files_of(repo), False) is None
```

- [ ] **Step 2: Run** `PYTEST tests/test_digest.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement `digest_session`** — one pass per file, mirroring upstream `parse_session`/`sum_transcript`:
  1. normalise `timestamp`; track `first_ts`/`last_ts`; collect `cwd`s (unique, in order); append `(ts, gitBranch)`
     whenever the branch differs from the previous one;
  2. `is_prompt(entry)` → `command` event when `command_name` matches, else `prompt` event (preview = first 120 chars
     only when `keep_previews` and not `isCompactSummary`);
  3. `system` + `subtype == "compact_boundary"` → `compact` event from `compactMetadata`;
  4. `assistant`: first a `skill` event per `Skill` tool_use block (dedup by block `id`, else `f"{requestId}:{skill}"`),
     then, if `message.usage` exists: `flat = normalize(usage)`; a known `requestId` → `merge_max`; a new one →
     `Request(event_index=len(events) - 1)`; no `requestId` → a new `Request` with id `f"noreq:{line_number}"`; model
     defaults to `"unknown"`.
  `last_main_ts` = last timestamp in the main file (the spec's unreadable-line count is not kept — nothing consumes
  it). Subagent files use the same request logic (no events), plus
  `finished` = last assistant entry's `message.stop_reason == "end_turn"`, `start_ts = norm_ts(agent_start(path,
  first_ts, meta))`, `agent_type`/`spawn_depth` from meta (defaults `"agent"`, 1), `rel_path` = POSIX path relative to
  `<session>/subagents/`. `last_ts` of the session = max over main and subagents.
  **Cache:** JSON `{"v": DIGEST_VERSION, "vendored_sha", "keep_previews", "key": files.key(), "digest"}`, written to a
  temp file and `os.replace`d; `load` returns `None` on any mismatch or unreadable file.

- [ ] **Step 4: Run** `PYTEST tests/test_digest.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add request-level session digests with cache"` · `git push`

---

### Task 9: `phases`, scenarios and the oracle

**Model:** implementer sonnet · reviewer sonnet

**Files:** Create `usage_bridge/phases.py`, `tests/scenarios.py`, `tests/test_phases.py`, `tests/test_oracle.py`

**Interfaces:**
- Consumes: `SessionDigest`, `Request`, `SubagentDigest` (Task 8); builders; `discovery.discover`; `tu_compat.oracle_segments`.
- Produces:
  - `CORE_PHASES = ("constitution", "specify", "clarify", "plan", "checklist", "tasks", "analyze", "implement", "taskstoissues")`
  - `BUILTIN_COMMANDS: FrozenSet[str]` = exactly the spec §3.1 list
  - `@dataclass(frozen=True) class Invocation: kind: str; phase: str` (kinds `core | extension | builtin | other`)
  - `classify_command(name: str, extension_ids: Sequence[str]) -> Invocation`, `skill_phase(skill: str) -> Optional[str]`
  - `@dataclass class Run: session_id: str; kind: str; phase: str; label: str; start_ts: Optional[str]; end_ts: Optional[str]; requests: List[Request]; subagents: List[SubagentDigest]; skills: List[str]; last_branch: Optional[str]; prompt_preview: Optional[str]; after_clear: bool`
  - `build_runs(digest: SessionDigest, extension_ids: Sequence[str]) -> List[Run]`
  - `upstream_segments(digest: SessionDigest) -> List[Dict[str, Any]]` → `[{"label": str, "by_model": {model: {input, output, cache_read, cache_5m, cache_1h, requests}}}]`
  - `installed_extension_ids(project: Path) -> List[str]` (sorted keys of `.specify/extensions/.registry` `extensions`; `[]` on any error)
  - `tests/scenarios.py`: `ALL_SCENARIOS: Dict[str, Callable[[Path], List[Path]]]` (each writes sessions and returns
    main paths) and `files_for(main: Path) -> SessionFiles`

- [ ] **Step 1: Write the failing tests** — `tests/test_phases.py`

```python
@pytest.mark.parametrize("name,kind,phase", [
    ("/speckit-plan", "core", "plan"), ("/speckit.plan", "core", "plan"), ("$speckit-plan", "core", "plan"),
    ("/spec-kit:speckit-plan", "core", "plan"), ("/speckit-git-commit", "extension", "git.commit"),
    ("/speckit.git.commit", "extension", "git.commit"),
    ("/speckit-multi-repo-sync-analyze", "extension", "multi-repo-sync.analyze"),
    ("/speckit-unknown-thing", "extension", "speckit-unknown-thing"),
    ("/model", "builtin", "/model"), ("/compact", "builtin", "/compact"), ("/init", "other", "other"), ("/review", "other", "other")])
def test_classify_command(name, kind, phase):
    assert classify_command(name, ["git", "multi", "multi-repo-sync"]) == Invocation(kind, phase)

def test_skill_phase():
    assert skill_phase("speckit-tasks") == "tasks" and skill_phase("superpowers:brainstorming") is None
    assert skill_phase("speckit-git-commit") is None

def test_builtin_list_is_exact():
    assert BUILTIN_COMMANDS == frozenset("/add-dir /agents /bug /clear /compact /config /context /cost /doctor /effort "
        "/exit /export /fast /help /hooks /ide /login /logout /mcp /memory /model /permissions /release-notes /resume "
        "/rewind /status /statusline /terminal-setup /theme /upgrade /usage /vim".split())

def runs_of(tmp_path, build, ext=()):
    repo = make_repo(tmp_path); b = SessionBuilder("s1", cwd=repo); build(b); b.write()
    return build_runs(digest_session(discover([repo], [projects_root()], [])[0]), list(ext))

def test_sticky_prompts_and_transparent_model(tmp_path):
    def build(b):
        b.command("/speckit-plan"); b.reply("r1", output=1); b.prompt("more"); b.command("/model"); b.reply("r2", output=1)
    (run,) = runs_of(tmp_path, build)
    assert (run.phase, [r.request_id for r in run.requests]) == ("plan", ["r1", "r2"])

def test_hook_skill_folds_core_skill_starts(tmp_path):
    def build(b):
        b.command("/speckit-plan"); b.reply("r1", output=1, skill="speckit-git-commit")
        b.reply("r2", output=1, skill="speckit-tasks"); b.reply("r3", output=1)
    plan, tasks = runs_of(tmp_path, build)
    assert (plan.phase, plan.skills, [r.request_id for r in plan.requests]) == ("plan", ["speckit-git-commit"], ["r1"])
    assert (tasks.phase, [r.request_id for r in tasks.requests]) == ("tasks", ["r2", "r3"])

def test_other_runs_and_extension_rows(tmp_path):
    def build(b):
        b.prompt("hi"); b.reply("r0", output=1); b.command("/review"); b.reply("r1", output=1)
        b.command("/speckit-superspec-brainstorm"); b.reply("r2", output=1)
    runs = runs_of(tmp_path, build, ext=["superspec"])
    assert [(r.kind, r.phase, r.label) for r in runs] == [
        ("other", "other", "(no command)"), ("other", "other", "/review"),
        ("extension", "superspec.brainstorm", "/speckit-superspec-brainstorm")]

def test_request_before_any_event_starts_other_run(tmp_path):
    (run,) = runs_of(tmp_path, lambda b: b.reply("r0", output=1))
    assert (run.kind, run.label, run.start_ts) == ("other", "(no command)", run.requests[0].ts)

def test_subagent_assigned_to_run_active_at_start(tmp_path):
    def build(b):
        b.command("/speckit-plan"); b.reply("r1", output=1); b.subagent("agent-a1").reply("ra", output=1)
        b.tick(600); b.command("/speckit-tasks"); b.reply("r2", output=1)
    plan, tasks = runs_of(tmp_path, build)
    assert [s.rel_path for s in plan.subagents] == ["agent-a1.jsonl"] and tasks.subagents == []

def test_runs_without_requests_are_dropped_and_after_clear(tmp_path):
    def build(b):
        b.command("/clear"); b.command("/speckit-plan"); b.command("/speckit-tasks"); b.reply("r1", output=1)
    (run,) = runs_of(tmp_path, build)
    assert (run.phase, run.after_clear) == ("tasks", True)

def test_last_branch_is_branch_at_last_request(tmp_path):
    def build(b):
        b.command("/speckit-specify"); b.reply("r1", output=1); b.set_branch("001-login"); b.reply("r2", output=1)
    assert runs_of(tmp_path, build)[0].last_branch == "001-login"

def test_installed_extension_ids(tmp_path):
    reg = tmp_path / ".specify" / "extensions" / ".registry"; reg.parent.mkdir(parents=True)
    reg.write_text('{"schema_version": "1.0", "extensions": {"superspec": {}, "git": {}}}', encoding="utf-8")
    assert installed_extension_ids(tmp_path) == ["git", "superspec"] and installed_extension_ids(tmp_path / "x") == []
```

`tests/test_oracle.py`:

```python
pytestmark = pytest.mark.contract

@pytest.mark.parametrize("name", sorted(ALL_SCENARIOS))
def test_upstream_mode_matches_parse_session(name, tmp_path):
    for main in ALL_SCENARIOS[name](tmp_path):
        ours = upstream_segments(digest_session(files_for(main)))
        theirs = [{"label": s["label"], "by_model": s["by_model"]} for s in tu_compat.oracle_segments(main)]
        assert ours == theirs, name
```

`ALL_SCENARIOS` keys (spec §8.2): `specify_plan_one_session`, `split_sessions`, `fork_duplicate_requests`,
`branch_created_mid_specify`, `subagents_flat_and_nested`, `compact_manual_and_auto`, `clear_in_file`, `clear_new_file`,
`sticky_followups`, `two_features_one_session`, `non_speckit_work`, `malformed_lines`, `spaces_in_dir`,
`no_git_extension`, `feature_switched_mid_session`, `all_invocation_forms`, `hook_and_plugin_skills`, `model_mid_phase`,
`constitution_then_specify`, `background_subagent_running`, `requests_without_id`.

- [ ] **Step 2: Run** `PYTEST tests/test_phases.py tests/test_oracle.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement**
  - `classify_command`: strip, drop leading `/` or `$`, drop a `<namespace>:` prefix; `speckit.<p>` / `speckit-<p>` with
    `p ∈ CORE_PHASES` → core; `speckit.<ext>.<cmd…>` → extension `"<ext>.<cmd…>"`; `speckit-<rest>` → the longest
    extension id `e` with `rest.startswith(e + "-")` → `"<e>.<rest after e->"`, none → extension with the name without
    its leading `/`/`$`; original name in `BUILTIN_COMMANDS` → builtin (phase = name); else other/"other".
  - `build_runs`: walk events keeping a current run — core/extension commands and core-phase skills open a run
    (label = raw name, `"/" + skill` for skills); other commands open `other` runs labelled with the command; builtins
    are ignored except that a `/clear` before the session's first request sets `after_clear` on all its runs; a prompt
    with no current run opens an `other` run labelled `"(no command)"` (first preview kept); other skills are added to
    the current run's `skills` (opening an `other` run labelled `"/" + skill` if none). Each request joins the run
    current at its `event_index` (`-1` → an `other` `"(no command)"` run starting at the request). Each subagent joins
    the latest run with `start_ts <= subagent.start_ts`, else the last run, else a new `other` run. `end_ts` = max of
    request and subagent timestamps; `last_branch` = branch in effect at the last main request; drop runs with no
    requests in the run or its subagents.
  - `upstream_segments`: the same walk with upstream rules — every command and every skill opens a segment (label =
    command name / `"/" + skill`), a prompt opens `"(no command)"` only when there is no segment yet, requests at
    `event_index -1` open `"(no command)"`, subagents join by start as above; `by_model` sums each request once with
    `requests` counting requests.
  - `tests/scenarios.py`: one builder function per key, using `SessionBuilder` in fresh repos under `tmp_path`.

- [ ] **Step 4: Run** `PYTEST tests/test_phases.py tests/test_oracle.py -q && RUFF` → Expected: all pass (21 oracle cases).

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add phase rules and parse_session reconciliation oracle"` · `git push`

---

### Task 10: `attribution`

**Model:** implementer sonnet · reviewer sonnet

**Files:** Create `usage_bridge/attribution.py`, `tests/test_attribution.py`

**Interfaces:**
- Consumes: `Run` (Task 9), `SessionDigest` (Task 8), `TimelineEntry` (Task 5).
- Produces:
  - `@dataclass(frozen=True) class Bucket: kind: str; feature_dir: Optional[str]` (kinds `feature | project | unattributed`)
  - `@dataclass class AttributedRun: run: Run; bucket: Bucket; attributed_by: str` (`timeline | branch | none`)
  - `dedup_across_sessions(digests: Sequence[SessionDigest]) -> Tuple[List[SessionDigest], int]`
  - `existing_feature_dirs(work: Path, timeline: Sequence[TimelineEntry]) -> List[str]` (sorted relative POSIX dirs)
  - `resolve_branch(branch: Optional[str], known: Sequence[str]) -> Optional[str]`
  - `attribute_runs(runs: Sequence[Run], timeline_by_session: Mapping[str, List[TimelineEntry]], known: Sequence[str]) -> List[AttributedRun]`

- [ ] **Step 1: Write the failing tests**

```python
def entry(ts, sid="s1", fd=None): return TimelineEntry(ts, sid, "w", fd, "feature.json" if fd else "none", None)
def run(phase="plan", end="2026-09-29T10:05:00.000Z", branch=None, sid="s1"):
    return Run(sid, "core", phase, "/speckit-" + phase, end, end, [], [], [], branch, None, False)

def test_dedup_keeps_earliest_session():
    d1 = make_digest("s1", "2026-09-29T09:00:00.000Z", ["r1", "r2"])      # helper in the test module
    d2 = make_digest("s2", "2026-09-29T10:00:00.000Z", ["r2", "r3"], subagent_ids=["r1"])
    (a, b), dropped = dedup_across_sessions([d2, d1])
    assert [r.request_id for r in b.requests] == ["r3"] and b.subagents[0].requests == [] and dropped == 2

def test_dedup_ignores_synthetic_ids():
    d1 = make_digest("s1", "2026-09-29T09:00:00.000Z", ["noreq:1"]); d2 = make_digest("s2", "2026-09-29T10:00:00.000Z", ["noreq:1"])
    assert dedup_across_sessions([d1, d2])[1] == 0

def test_timeline_first_entry_at_or_after_run_end():
    tl = {"s1": [entry("2026-09-29T10:03:00.000Z", fd="specs/001-a"), entry("2026-09-29T10:06:00.000Z", fd="specs/002-b")]}
    (a,) = attribute_runs([run()], tl, ["specs/001-a", "specs/002-b"])
    assert (a.bucket, a.attributed_by) == (Bucket("feature", "specs/002-b"), "timeline")

@pytest.mark.parametrize("branch,known,expected", [
    ("001-login", ["specs/001-login"], "specs/001-login"),
    ("feature/001-login", ["specs/001-login"], "specs/001-login"),
    ("jb/myapp/001-login", ["specs/001-login"], "specs/001-login"),
    ("20260929-140211-login", ["specs/20260929-140211-login-flow"], "specs/20260929-140211-login-flow"),
    ("001-x", ["specs/001-login"], "specs/001-login"),
    ("001-x", ["specs/001-login", "specs/001-logout"], None),
    ("main", ["specs/001-login"], None), (None, ["specs/001-login"], None),
    ("feature/login", ["specs/001-login"], None)])
def test_resolve_branch(branch, known, expected):
    assert resolve_branch(branch, known) == expected

def test_branch_fallback_and_unattributed():
    got = attribute_runs([run(branch="001-login"), run(branch="main")], {}, ["specs/001-login"])
    assert [(a.bucket.kind, a.attributed_by) for a in got] == [("feature", "branch"), ("unattributed", "none")]

def test_constitution_is_project():
    tl = {"s1": [entry("2026-09-29T10:06:00.000Z", fd="specs/001-a")]}
    (a,) = attribute_runs([run("constitution")], tl, ["specs/001-a"])
    assert a.bucket == Bucket("project", None)

def test_renamed_feature_dir_falls_back_to_branch():
    tl = {"s1": [entry("2026-09-29T10:06:00.000Z", fd="specs/001-login")]}      # renamed since
    (a,) = attribute_runs([run(branch="001-login")], tl, ["specs/001-user-login"])
    assert (a.bucket.feature_dir, a.attributed_by) == ("specs/001-user-login", "branch")

def test_existing_feature_dirs(tmp_path):
    for d in ("specs/001-a", "specs/002-b", "custom/x"):
        (tmp_path / d).mkdir(parents=True)
    tl = [entry("t", fd="custom/x"), entry("t", fd="gone/y")]
    assert existing_feature_dirs(tmp_path, tl) == ["custom/x", "specs/001-a", "specs/002-b"]
```

`make_digest(session_id, first_ts, request_ids, subagent_ids=())` builds a `SessionDigest` directly from dataclasses
(zero usage, one subagent when `subagent_ids` is given).

- [ ] **Step 2: Run** `PYTEST tests/test_attribution.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — `dedup_across_sessions` orders by `(first_ts or "", session_id)`, drops main and subagent
  requests whose id (not starting with `noreq:`) was seen in an earlier session, returns copies and the drop count.
  `attribute_runs`: constitution → `project`; timeline = first entry of the run's session with `ts >= run.end_ts` whose
  `feature_dir` is in `known`; else `resolve_branch(run.last_branch, known)` → `branch`; else `unattributed`/`none`.
  `resolve_branch` implements spec §3.2 rules 1–3 in order; a rule with several matches → `None`.

- [ ] **Step 4: Run** `PYTEST tests/test_attribution.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: attribute runs to features via timeline and branch"` · `git push`

---

### Task 11: `metrics`

**Model:** implementer sonnet · reviewer sonnet

**Files:** Create `usage_bridge/metrics.py`, `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Request`, `SessionDigest` (Task 8), `Run` (Task 9), `AttributedRun` (Task 10), `tu_compat.Rates/cost/unpriced/rate_of`.
- Produces:
  - `USAGE_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")`
  - `run_summary(run: Run, rates: Rates) -> Dict[str, Any]` → `{"calls", "usage", "tokens", "cost_usd", "models", "subagents", "skills"}`
  - `session_facts(digest: SessionDigest) -> Dict[str, Any]` → `{"dominant_model", "main_calls", "final_context_tokens", "used_1h_cache"}`
  - `repriming(digest: SessionDigest, feature_runs: Sequence[Run], rates: Rates) -> Optional[Dict[str, Any]]` → `{"tokens", "cost_usd"}`;
    `None` when the session's first main request is not in `feature_runs`
  - `verdict(prev: SessionDigest, cur: SessionDigest, repriming_cost: Optional[float], rates: Rates) -> Dict[str, Any]`
    → `{"previous_session_id", "carried_tokens", "calls", "gap_seconds", "avoided_cost_usd", "net_usd"}`
  - `compactions(digest: SessionDigest, rates: Rates) -> List[Dict[str, Any]]`
  - `completeness(digests: Sequence[SessionDigest], deadline_hit: bool) -> Tuple[str, List[str]]` (reasons `deadline`, `subagent-in-progress`)
  - `session_entry(digest: SessionDigest, runs: Sequence[AttributedRun], rates: Rates, prev: Optional[SessionDigest], keep_previews: bool) -> Dict[str, Any]`
    — one §4.2 session object (runs numbered per phase in start order)

- [ ] **Step 1: Write the failing tests** — fixture `rates` = `load_rates({"claude-test-1": {"input": 2.0, "output": 10.0}}, tmp_path)`
  (cache read 0.2, 5-minute write 2.5, 1-hour write 4.0 USD/MTok). Test-module helpers construct the Task 8/9
  dataclasses directly: `req(request_id, model="claude-test-1", **usage)` (timestamps one second apart),
  `mk_sub(requests, last_ts=None, finished=True)`, `mk_digest(requests, first_ts=..., last_ts=..., last_main_ts=...,
  subagents=(), compact_before_index=None)` (the compact event — `auto`, 967128 → 24252 — is inserted before the
  request at that index) and `mk_run(main=(), subagents=())` (a `plan` run).

```python
def test_run_summary_sums_main_and_subagents(rates):
    run = mk_run(main=[req("r1", input=1000, output=500, cache_read=10000, cache_5m=2000)],
                 subagents=[mk_sub([req("ra", input=100, output=50)])])
    s = run_summary(run, rates)
    assert (s["calls"], s["tokens"]) == (2, 13650)
    assert s["usage"] == {"input": 1100, "output": 550, "cache_read": 10000, "cache_write_5m": 2000, "cache_write_1h": 0}
    assert s["subagents"]["count"] == 1 and s["subagents"]["usage"]["input"] == 100
    assert s["cost_usd"] == pytest.approx((1100 * 2 + 550 * 10 + 10000 * 0.2 + 2000 * 2.5) / 1e6)

def test_unpriced_models_listed_and_excluded(rates):
    s = run_summary(mk_run(main=[req("r1", model="mystery", input=5)]), rates)
    assert s["cost_usd"] is None and list(s["models"]) == ["mystery"]

def test_repriming_first_request(rates):
    d = mk_digest([req("r1", input=20, cache_5m=30000)]); run = mk_run(main=d.requests)
    assert repriming(d, [run], rates) == {"tokens": 30020, "cost_usd": pytest.approx((20 * 2 + 30000 * 2.5) / 1e6)}
    assert repriming(d, [], rates) is None

def test_verdict_within_ttl(rates):
    prev = mk_digest([req("p1", input=1000, cache_read=170000, cache_5m=9000)], last_ts="2026-09-29T10:00:00.000Z")
    cur = mk_digest([req(f"c{i}") for i in range(38)], first_ts="2026-09-29T10:02:00.000Z")
    v = verdict(prev, cur, 0.1, rates)
    assert (v["carried_tokens"], v["calls"], v["gap_seconds"]) == (180000, 38, 120)
    assert v["avoided_cost_usd"] == pytest.approx(180000 * 38 * 0.2 / 1e6) and v["net_usd"] == pytest.approx(v["avoided_cost_usd"] - 0.1)

def test_verdict_rewrite_after_5_minute_ttl(rates):
    prev = mk_digest([req("p1", cache_read=180000)], last_ts="2026-09-29T10:00:00.000Z")
    cur = mk_digest([req("c1")], first_ts="2026-10-01T12:20:00.000Z")
    assert verdict(prev, cur, 0.0, rates)["avoided_cost_usd"] == pytest.approx(180000 * 1 * 0.2 / 1e6 + 180000 * 2.5 / 1e6)

def test_verdict_1_hour_rules(rates):
    prev = mk_digest([req("p1", cache_read=100000, cache_1h=1)], last_ts="2026-09-29T10:00:00.000Z")
    near = mk_digest([req("c1")], first_ts="2026-09-29T10:50:00.000Z"); far = mk_digest([req("c1")], first_ts="2026-09-29T11:10:00.000Z")
    assert verdict(prev, near, 0.0, rates)["avoided_cost_usd"] == pytest.approx(100001 * 0.2 / 1e6)
    assert verdict(prev, far, 0.0, rates)["avoided_cost_usd"] == pytest.approx(100001 * 0.2 / 1e6 + 100001 * 4.0 / 1e6)

def test_dominant_model_and_final_context(rates):
    d = mk_digest([req("a", model="m1"), req("b", model="m2"), req("c", model="m2", input=5, cache_read=7, cache_5m=11)])
    f = session_facts(d)
    assert (f["dominant_model"], f["main_calls"], f["final_context_tokens"]) == ("m2", 3, 23)

def test_compaction_reload(rates):
    d = mk_digest([req("a"), req("b", input=100, cache_5m=43842)], compact_before_index=1)
    (c,) = compactions(d, rates)
    assert (c["trigger"], c["pre_tokens"], c["post_tokens"], c["reload_tokens"]) == ("auto", 967128, 24252, 43942)

def test_completeness_reasons():
    running = mk_digest([req("a")], last_main_ts="2026-09-29T10:00:00.000Z",
                        subagents=[mk_sub([req("s")], last_ts="2026-09-29T10:09:00.000Z", finished=False)])
    assert completeness([running], False) == ("partial", ["subagent-in-progress"])
    assert completeness([mk_digest([req("a")])], True) == ("partial", ["deadline"])
    assert completeness([mk_digest([req("a")])], False) == ("complete", [])

def test_session_entry_shape(rates):
    d = mk_digest([req("a", input=5)]); ar = AttributedRun(mk_run(main=d.requests), Bucket("feature", "specs/001-a"), "timeline")
    e = session_entry(d, [ar], rates, None, keep_previews=False)
    assert list(e) == ["session_id", "first_ts", "last_ts", "after_clear", "dominant_model", "main_calls",
                       "final_context_tokens", "repriming", "splitting", "compactions", "runs"]
    assert e["splitting"] is None and e["runs"][0]["run"] == 1 and "prompt_preview" not in e["runs"][0]
```

- [ ] **Step 2: Run** `PYTEST tests/test_metrics.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — formulas from spec §3.3–3.5 exactly: `tokens` = sum of the five buckets; `cost_usd` via
  `tu_compat.cost` on per-model buckets (vendored keys); re-priming and reload = `input + cache_5m + cache_1h` of one
  request priced alone; verdict `read_rate`/`input` from `tu_compat.rate_of(cur dominant model)` (unpriced → costs
  `None`), `write_rate = input × (2.0 if prev.used_1h_cache else 1.25)`, `ttl = 3600 if prev.used_1h_cache else 300`,
  `gap_seconds` = whole seconds between `prev.last_ts` and `cur.first_ts`. `session_entry` emits keys in the order the
  test pins; each run object has keys `phase, kind, label, run, start_ts, end_ts, attributed_by, calls, usage,
  cost_usd, models, subagents, skills` (+ `prompt_preview` only when `keep_previews`); `splitting` =
  `verdict(prev, digest, repriming cost, rates)` when `prev` is given and `repriming` is not `None`, else `None`.

- [ ] **Step 4: Run** `PYTEST tests/test_metrics.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add usage, re-priming, verdict and completeness metrics"` · `git push`

---

### Task 12: `render` — per-author JSON, formatting, safe writes

**Model:** implementer haiku · reviewer sonnet

**Files:** Create `usage_bridge/render.py`, `tests/test_render_json.py`

**Interfaces:**
- Produces:
  - `SCHEMA_FEATURE = "usage-bridge/feature-usage"`, `SCHEMA_REPORT = "usage-bridge/feature-report"`, `SCHEMA_REPO = "usage-bridge/repo-report"`
  - `fmt_tokens(n: int) -> str`, `fmt_cost(x: Optional[float]) -> str`, `fmt_ts(iso: str) -> str`
  - `dump_json(obj: Any) -> str` (floats rounded to 6 decimals, `indent=2`, `ensure_ascii=False`, trailing `"\n"`)
  - `author_file(feature_id: str, feature_dir: str, author: str, machine: str, generator: Dict[str, str], sessions: List[Dict[str, Any]], completeness: str, partial_reasons: List[str], unpriced: List[str]) -> Dict[str, Any]`
  - `write_if_changed(path: Path, text: str) -> bool` — `True` when written

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("n,s", [(0, "0"), (999, "999"), (1000, "1.0k"), (4149, "4.1k"), (5000, "5.0k"),
    (10000, "10k"), (212044, "212k"), (1_000_000, "1.0M"), (17_062_000, "17.1M")])
def test_fmt_tokens(n, s):
    assert fmt_tokens(n) == s

def test_fmt_cost_and_ts():
    assert (fmt_cost(3.9), fmt_cost(None), fmt_cost(0.004)) == ("$3.90", "—", "$0.00")
    assert fmt_ts("2026-10-01T13:00:02.000Z") == "10-01 13:00"

def test_dump_json_is_stable_lf_and_rounded():
    assert dump_json({"b": 1.23456789, "a": "ł"}) == '{\n  "b": 1.234568,\n  "a": "ł"\n}\n'

def test_author_file_shape_and_sorting():
    s1 = {"session_id": "b", "first_ts": "2026-09-30T08:00:00.000Z", "last_ts": "2026-09-30T09:00:00.000Z"}
    s0 = {"session_id": "a", "first_ts": "2026-09-29T08:00:00.000Z", "last_ts": "2026-09-29T09:00:00.000Z"}
    f = author_file("001-a", "specs/001-a", "jakub", "a1b2c3", {"usage_bridge": "0.1.0"}, [s1, s0], "complete", [], [])
    assert list(f) == ["schema", "schema_version", "feature", "author", "generator", "runtime", "completeness",
                       "partial_reasons", "data_as_of", "unpriced_models", "sessions"]
    assert (f["schema"], f["schema_version"], f["runtime"]) == ("usage-bridge/feature-usage", 1, "claude")
    assert [s["session_id"] for s in f["sessions"]] == ["a", "b"] and f["data_as_of"] == "2026-09-30T09:00:00.000Z"

def test_write_if_changed(tmp_path):
    p = tmp_path / "d" / "f.md"
    assert write_if_changed(p, "a\nb\n") is True and p.read_bytes() == b"a\nb\n"
    assert write_if_changed(p, "a\nb\n") is False
    p.write_bytes(b"a\r\nb\r\n"); before = p.stat().st_mtime_ns
    assert write_if_changed(p, "a\nb\n") is False and p.stat().st_mtime_ns == before
    assert write_if_changed(p, "c\n") is True

def test_write_if_changed_keeps_original_on_failure(tmp_path, monkeypatch):
    p = tmp_path / "f.md"; p.write_text("old\n", encoding="utf-8")
    def locked(*args): raise PermissionError("locked")
    monkeypatch.setattr(os, "replace", locked)
    assert write_if_changed(p, "new\n") is False
    assert p.read_text(encoding="utf-8") == "old\n" and list(tmp_path.iterdir()) == [p]
```

- [ ] **Step 2: Run** `PYTEST tests/test_render_json.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — number rules from spec §4.1 (`< 1000` integer, `< 10_000` one-decimal `k`,
  `< 1_000_000` whole `k`, else one-decimal `M`); `write_if_changed` compares `existing.replace("\r\n", "\n")` with
  `text`, writes a temp file in the same directory (`newline="\n"`, UTF-8), `os.replace`s it, retries once on
  `PermissionError`/`OSError`, then removes the temp file and returns `False`.

- [ ] **Step 4: Run** `PYTEST tests/test_render_json.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add JSON rendering, formatting and safe writes"` · `git push`

---

### Task 13: `render` — merged md and report views

**Model:** implementer sonnet · reviewer sonnet

**Files:** Modify `usage_bridge/render.py`; create `tests/test_render_md.py`,
`tests/golden/feature/sources/jakub.a1b2c3.json`, `tests/golden/feature/sources/anna.d4e5f6.json`,
`tests/golden/feature/token-usage.md`

**Interfaces:**
- Consumes: Task 12 helpers; per-author source dicts (§4.2).
- Produces:
  - `merge_feature(sources: Sequence[Dict[str, Any]]) -> Dict[str, Any]` (schema `usage-bridge/feature-report` v1)
  - `render_feature_md(sources: Sequence[Dict[str, Any]]) -> str`
  - `merge_all(features: Sequence[Dict[str, Any]], project: Dict[str, Any], unattributed: Dict[str, Any]) -> Dict[str, Any]` (schema `usage-bridge/repo-report` v1)
  - `render_all_md(report: Dict[str, Any]) -> str`

- [ ] **Step 1: Create the golden files** — `tests/golden/feature/token-usage.md` is the spec §4.1 example, byte for byte
  (the fenced markdown block only). The two source files hold per-author data (jakub: sessions `3f9a2c1e…` with the
  other-work, specify and plan runs, and `9c2e11f0…` with the branch-attributed implement run, its compaction and
  `splitting`; anna: session `b71d04aa…` with the tasks run and re-priming 54k/$0.20), with token and cost values chosen
  so that every formatted number matches the example.

- [ ] **Step 2: Write the failing tests**

```python
GOLD = Path(__file__).parent / "golden" / "feature"
def sources(): return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((GOLD / "sources").glob("*.json"))]

def test_md_matches_golden(update_golden):
    out = render_feature_md(sources())
    if update_golden:
        (GOLD / "token-usage.md").write_text(out, encoding="utf-8", newline="\n")
    assert out == (GOLD / "token-usage.md").read_text(encoding="utf-8")

def test_md_is_order_independent():
    a, b = sources()
    assert render_feature_md([a, b]) == render_feature_md([b, a])

def test_md_has_lf_and_generated_comment():
    out = render_feature_md(sources())
    assert out.startswith("<!-- Generated by Usage Bridge — do not edit.") and "\r" not in out

def test_run_numbers_recounted_across_authors():
    a, b = two_authors_with_plan_runs()        # local helper: two sources, one plan run each at 10:00 and 11:00
    rows = [line for line in render_feature_md([a, b]).splitlines() if line.startswith("| plan |")]
    assert [row.split("|")[2].strip() for row in rows[1:]] == ["1", "2"]   # rows[0] is the summary row

def test_phase_order_extension_rows_and_no_constitution():
    md = render_feature_md([source_with_phases(["implement", "superspec.brainstorm", "specify", "other"])])
    summary = [l.split("|")[1].strip() for l in md.split("## Runs")[0].splitlines() if l.startswith("| ") and "Phase" not in l]
    assert summary == ["specify", "implement", "superspec.brainstorm", "other work"] and "constitution" not in md

def test_pricing_groups_and_partial_header():
    a, b = sources(); b = {**b, "generator": {**b["generator"], "pricing": "bundled+overrides", "pricing_sha256": "ffff"},
                             "completeness": "partial", "partial_reasons": ["deadline"]}
    head = render_feature_md([a, b]).splitlines()[3]
    assert "pricing: bundled (anna) · bundled+overrides (jakub)" in head and "partial (deadline)" in head

def test_merge_feature_totals():
    rep = merge_feature(sources())
    assert (rep["schema"], rep["schema_version"]) == ("usage-bridge/feature-report", 1)
    assert rep["totals"]["tokens"] == sum(p["tokens"] for p in rep["phases"]) and all("author" in r for r in rep["runs"])

def test_all_report():
    rep = merge_all([merge_feature(sources())], project={"tokens": 5}, unattributed={"tokens": 7})
    md = render_all_md(rep)
    assert rep["schema"] == "usage-bridge/repo-report" and "project" in md and "unattributed (this machine only)" in md
```

(`two_authors_with_plan_runs` and `source_with_phases` are small local builders of source dicts in the test module.)

- [ ] **Step 3: Run** `PYTEST tests/test_render_md.py -q` → Expected: FAIL.

- [ ] **Step 4: Implement** — layout and rules from spec §4.1 (header line fields in the example's order; headline;
  summary table rows in SDD order, then extension rows alphabetically, then "other work"; runs sorted by
  `(start_ts, session_id)` with run numbers re-counted per phase; `†` after branch-attributed session ids plus the
  footnote; "Session splitting" table for every session after the feature's first; verdict sum line and the
  assumptions sentence; compactions line; unpriced and partial footnotes; disclaimer). `merge_feature` sums runs across
  sources (runs gain `author` and `session_id`); `merge_all` adds `phase_averages` = mean tokens and cost per phase over
  features having that phase; `render_all_md` renders a features table, the phase averages, and `project` /
  `unattributed (this machine only)` rows.

- [ ] **Step 5: Run** `PYTEST tests/test_render_md.py -q && RUFF` → Expected: all pass.

- [ ] **Step 6: Commit and push** — `git commit -m "feat: render deterministic merged markdown and report views"` · `git push`

---

### Task 14: `pipeline`

**Model:** implementer sonnet · reviewer sonnet

**Files:** Create `usage_bridge/pipeline.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything from Tasks 2–13.
- Produces:
  - `@dataclass class CaptureResult: mode: str; status: str; features_written: List[str]; summary: str; duration_ms: int; error: Optional[str]; local: Dict[str, Any]`
    — `status ∈ ok | partial | error | skipped | noop`; `local` = `{"project": {...}, "unattributed": {...}}` summaries
    (sessions, calls, usage, tokens, cost_usd) for `report --all`
  - `run_capture(raw_stdin: str, cwd: Path, env: Mapping[str, str], now: Optional[datetime] = None, clock: Callable[[], float] = time.monotonic, lock_wait: float = 5.0) -> CaptureResult`
  - `feature_sources(work: Path, cfg: Config, feature_dir: str) -> List[Dict[str, Any]]` (loads `token-usage/*.json`
    from the feature's output dir, skipping unreadable files)

- [ ] **Step 1: Write the failing tests** — helpers: `payload(sid, main, cwd) = json.dumps({"session_id": sid,
  "transcript_path": str(main), "cwd": str(cwd), "hook_event_name": "Stop"})`;
  `own = f"test-author.{machine_id(socket.gethostname())}.json"`; `single_session(tmp_path) -> Tuple[Path, str]` added to
  `tests/builders.py` (repo with `specs/001-login`, one `/speckit-plan` session `s1` on branch `001-login`; returns the
  repo and that session's Stop payload); `three_sessions(tmp_path)` (module helper: the same repo with three sessions,
  returning the payload of the newest); `GOLDEN_ANNA = tests/golden/feature/sources/anna.d4e5f6.json` (Task 13).

```python
def test_hook_capture_writes_feature_files(tmp_path):
    repo = make_repo(tmp_path, features=("001-login",)); b = SessionBuilder("s1", cwd=repo, branch="001-login")
    b.command("/speckit-specify"); b.reply("r1", output=10); b.command("/speckit-plan"); b.reply("r2", output=20)
    res = run_capture(payload("s1", b.write(), repo), repo, dict(os.environ))
    feat = repo / "specs" / "001-login"
    data = json.loads((feat / "token-usage" / own).read_text(encoding="utf-8"))
    assert res.status == "ok" and res.features_written == ["specs/001-login"]
    assert [r["phase"] for s in data["sessions"] for r in s["runs"]] == ["specify", "plan"]
    assert "| plan |" in (feat / "token-usage.md").read_text(encoding="utf-8")

def test_timeline_entry_is_appended_and_used(tmp_path):
    repo = make_repo(tmp_path); (repo / ".specify" / "feature.json").write_text('{"feature_directory": "specs/001-login"}', encoding="utf-8")
    b = SessionBuilder("s1", cwd=repo, branch="main"); b.command("/speckit-plan"); b.reply("r1", output=1)
    run_capture(payload("s1", b.write(), repo), repo, dict(os.environ))
    data = json.loads((repo / "specs/001-login/token-usage" / own).read_text(encoding="utf-8"))
    assert len(read(repo / ".git" / "usage-bridge")) == 1 and data["sessions"][0]["runs"][0]["attributed_by"] == "timeline"

def test_unchanged_second_capture_writes_nothing(tmp_path):
    repo, raw = single_session(tmp_path); run_capture(raw, repo, dict(os.environ))
    md = repo / "specs/001-login/token-usage.md"; before = md.stat().st_mtime_ns
    assert run_capture(raw, repo, dict(os.environ)).features_written == [] and md.stat().st_mtime_ns == before

@pytest.mark.parametrize("raw", ["{bad", "x" * 2_000_000, '{"conversation_id": "c"}'])
def test_non_claude_input_is_silent_noop(raw, tmp_path, capfd):
    repo = make_repo(tmp_path)
    assert run_capture(raw, repo, dict(os.environ)).status == "noop" and capfd.readouterr() == ("", "")

def test_disabled_config_is_noop(tmp_path):
    repo, raw = single_session(tmp_path); cfg = repo / ".specify/extensions/usage-bridge"; cfg.mkdir(parents=True)
    (cfg / "usage-bridge-config.yml").write_text("enabled: false\n", encoding="utf-8")
    assert run_capture(raw, repo, dict(os.environ)).status == "noop"
    assert not (repo / "specs/001-login/token-usage.md").exists()

def test_deadline_marks_partial(tmp_path):
    repo, raw = three_sessions(tmp_path); ticks = itertools.count(0, 10.0)
    res = run_capture(raw, repo, dict(os.environ), clock=lambda: next(ticks))
    last = json.loads((repo / ".git/usage-bridge/last-capture.json").read_text(encoding="utf-8"))
    assert res.status == "partial" and last["status"] == "partial"
    assert (repo / "specs/001-login/token-usage.md").exists()      # the active session is always digested

def test_lock_contention_skips_but_records_timeline(tmp_path):
    repo, raw = single_session(tmp_path); rt = repo / ".git" / "usage-bridge"; rt.mkdir(parents=True); (rt / "lock").write_text("x")
    assert run_capture(raw, repo, dict(os.environ), lock_wait=0.2).status == "skipped" and len(read(rt)) == 1

def test_stale_lock_is_broken(tmp_path):
    repo, raw = single_session(tmp_path); rt = repo / ".git" / "usage-bridge"; rt.mkdir(parents=True)
    lock = rt / "lock"; lock.write_text("x"); old = time.time() - 120; os.utime(lock, (old, old))
    assert run_capture(raw, repo, dict(os.environ), lock_wait=0.2).status == "ok"

def test_worktree_payload_writes_into_worktree(tmp_path):
    repo = make_repo(tmp_path, features=()); wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt), "-b", "002-x"], check=True, capture_output=True)
    (wt / "specs" / "002-x").mkdir(parents=True)
    b = SessionBuilder("s1", cwd=wt, branch="002-x"); b.command("/speckit-plan"); b.reply("r1", output=1)
    run_capture(payload("s1", b.write(), wt), repo, dict(os.environ))
    assert (wt / "specs/002-x/token-usage.md").exists() and not (repo / "specs" / "002-x").exists()

def test_own_file_removed_when_no_runs(tmp_path):
    repo = make_repo(tmp_path); stale = repo / "specs/001-login/token-usage" / own
    stale.parent.mkdir(parents=True); stale.write_text("{}", encoding="utf-8")
    run_capture("", repo, dict(os.environ))
    assert not stale.exists() and not (repo / "specs/001-login/token-usage.md").exists()

def test_other_authors_sources_are_kept_and_merged(tmp_path):
    repo, raw = single_session(tmp_path); src = repo / "specs/001-login/token-usage" / "anna.d4e5f6.json"
    data = json.loads(GOLDEN_ANNA.read_text(encoding="utf-8")); data["feature"] = {"id": "001-login", "directory": "specs/001-login"}
    src.parent.mkdir(parents=True); src.write_text(dump_json(data), encoding="utf-8"); before = src.read_bytes()
    run_capture(raw, repo, dict(os.environ))
    assert src.read_bytes() == before and "anna" in (repo / "specs/001-login/token-usage.md").read_text(encoding="utf-8")

def test_manual_mode_summary(tmp_path):
    repo, _ = single_session(tmp_path)
    res = run_capture("", repo, dict(os.environ))
    assert res.mode == "manual" and res.summary.startswith("Usage Bridge: ")

def test_exception_is_logged_not_raised(tmp_path, monkeypatch):
    repo, raw = single_session(tmp_path)
    monkeypatch.setattr(pipeline, "digest_session", lambda *a, **k: 1 / 0)
    res = run_capture(raw, repo, dict(os.environ))
    assert res.status == "error" and "ZeroDivisionError" in (repo / ".git/usage-bridge/logs/usage-bridge.log").read_text(encoding="utf-8")
```


- [ ] **Step 2: Run** `PYTEST tests/test_pipeline.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement `run_capture`** — spec §2.1–2.7 in order:
  detect → `P = project_root(cwd) or cwd` → `load_config(P, env)` (disabled → noop) → `W = work_root(payload cwd, P)` →
  `R = runtime_dir(W, P)` → logger → cursor/unknown → log + noop (cursor message `Cursor capture is not supported in v0.1`)
  → deadline `clock() + min(cfg.deadline_seconds, 15)` → claude: `timeline.append` → lock (`R/lock` via
  `os.open(O_CREAT | O_EXCL)`, stale when mtime > 60 s old, poll every 0.1 s up to `lock_wait`, else `skipped`) →
  `discover(worktrees(P) or [P], projects_roots(payload, env), extra_dirs)` → the payload's own session is always
  loaded or digested first; every other session is `DigestCache.load`ed, else `digest_session` + `store` while the
  deadline has not passed, else skipped (deadline hit) →
  `dedup_across_sessions` → `build_runs(…, installed_extension_ids(P))` → `attribute_runs(…, by_session(read(R)),
  existing_feature_dirs(W, read(R)))` → `load_rates(cfg.pricing_overrides, R)` → author/machine from `paths` →
  per feature dir `fd` in the existing list, with output dir `W / cfg.output_dir.format(feature_dir=fd,
  feature_id=PurePosixPath(fd).name)`: this author's sessions (ordered by `first_ts`; `prev` = previous one) →
  `session_entry` list → `author_file` → `write_if_changed` own file, or delete it when there are no sessions →
  merged md from `feature_sources` (`write_if_changed`), or delete the md when no source remains →
  `last-capture.json` → summary `Usage Bridge: {n} features updated — {feature_id} {tokens} tokens (est. {cost})`
  (active feature, if any; `Usage Bridge: no changes` when n = 0). Release the lock in `finally`; any exception →
  logged traceback, `status="error"`.

- [ ] **Step 4: Run** `PYTEST tests/test_pipeline.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add capture pipeline"` · `git push`

---

### Task 15: `cli` — capture and report

**Model:** implementer haiku · reviewer sonnet

**Files:** Create `usage_bridge/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_capture`, `feature_sources`, `CaptureResult` (Task 14); `render.*` (Tasks 12–13); `timeline.active_feature/read`.
- Produces: `MAX_STDIN_BYTES = 1 << 20`, `read_stdin(stream: BinaryIO) -> str`,
  `capture_main(argv: Sequence[str], stdin: BinaryIO, stdout: TextIO, env: Mapping[str, str], cwd: Path) -> int`,
  `report_main(argv: Sequence[str], stdout: TextIO, env: Mapping[str, str], cwd: Path) -> int`,
  `capture_entry() -> int`, `report_entry() -> int` (wire `sys.stdin.buffer`, `sys.stdout`, `os.environ`, `Path.cwd()`)

- [ ] **Step 1: Write the failing tests**

```python
def test_capture_main_hook_is_silent(tmp_path):
    repo, raw = single_session(tmp_path); out = io.StringIO()
    assert capture_main([], io.BytesIO(raw.encode()), out, dict(os.environ), repo) == 0 and out.getvalue() == ""

def test_capture_main_manual_prints_one_line(tmp_path):
    repo, _ = single_session(tmp_path); out = io.StringIO()
    assert capture_main([], io.BytesIO(b""), out, dict(os.environ), repo) == 0
    assert out.getvalue().startswith("Usage Bridge: ") and out.getvalue().count("\n") == 1

@pytest.mark.parametrize("raw", [b"x" * (2 << 20), b"\xff\xfe{"])
def test_capture_main_bad_stdin(raw, tmp_path):
    repo = make_repo(tmp_path); out = io.StringIO()
    assert capture_main([], io.BytesIO(raw), out, dict(os.environ), repo) == 0 and out.getvalue() == ""

def test_report_default_feature_prints_md(tmp_path):
    repo, raw = single_session(tmp_path); capture_main([], io.BytesIO(raw.encode()), io.StringIO(), dict(os.environ), repo)
    out = io.StringIO()
    assert report_main([], out, dict(os.environ), repo) == 0
    assert out.getvalue() == (repo / "specs/001-login/token-usage.md").read_text(encoding="utf-8")

def test_report_named_feature_json(tmp_path):
    repo, _ = single_session(tmp_path); out = io.StringIO()
    assert report_main(["001-login", "--json"], out, dict(os.environ), repo) == 0
    assert json.loads(out.getvalue())["schema"] == "usage-bridge/feature-report"

def test_report_all(tmp_path):
    repo, _ = single_session(tmp_path); out = io.StringIO()
    assert report_main(["--all"], out, dict(os.environ), repo) == 0 and "001-login" in out.getvalue()

def test_report_unknown_feature(tmp_path):
    repo, _ = single_session(tmp_path); out = io.StringIO()
    assert report_main(["nope"], out, dict(os.environ), repo) == 1 and "Features: 001-login" in out.getvalue()

def test_report_refreshes_first(tmp_path):
    repo, _ = single_session(tmp_path); report_main([], io.StringIO(), dict(os.environ), repo)
    more = SessionBuilder("s2", cwd=repo, branch="001-login"); more.command("/speckit-tasks"); more.reply("r9", output=5); more.write()
    out = io.StringIO(); report_main([], out, dict(os.environ), repo)
    assert "| tasks |" in out.getvalue()
```

(`single_session` is the `tests/builders.py` helper from Task 14.)

- [ ] **Step 2: Run** `PYTEST tests/test_cli.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — `read_stdin` reads at most `MAX_STDIN_BYTES + 1` bytes, returns `""` when over the cap,
  decodes UTF-8 with `errors="replace"` and strips a BOM. `capture_main` never raises and always returns 0; it writes
  `result.summary + "\n"` only when `result.mode == "manual"`. `report_main` parses `[feature] [--all] [--json]` by
  hand (unknown flag → usage line, return 1), runs `run_capture("", cwd, env)` first, picks the feature (argument
  matching a feature dir name or path; else `active_feature`; else the latest timeline entry with a feature dir; else
  error), prints `render_feature_md` / `dump_json(merge_feature(...))`, or for `--all` `render_all_md(merge_all(...))`
  / its JSON. Errors print `No feature found for '<arg>'. Features: <comma-separated names>` and return 1.

- [ ] **Step 4: Run** `PYTEST tests/test_cli.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add capture and report command handlers"` · `git push`

---

### Task 16: `checks`

**Model:** implementer haiku · reviewer sonnet

**Files:** Create `usage_bridge/checks.py`, `tests/test_checks.py`; modify `usage_bridge/cli.py` (add `check_main`, `check_entry`)

**Interfaces:**
- Consumes: `paths`, `discovery`, `config`, `last-capture.json` (Task 14).
- Produces:
  - `@dataclass(frozen=True) class CheckResult: id: str; level: str; ok: bool; message: str; remediation: str`
    — ids `python, integration, stop-hook, dispatcher, git, transcripts, runtime-dir, last-capture, config`; levels `FAIL | WARN`
  - `run_checks(project: Path, env: Mapping[str, str], now: datetime, python_version: Tuple[int, int] = sys.version_info[:2]) -> List[CheckResult]`
  - `format_results(results: Sequence[CheckResult], verbose: bool, now: datetime, last_capture_ts: Optional[str]) -> str`
  - `cli.check_main(argv: Sequence[str], stdout: TextIO, env: Mapping[str, str], cwd: Path, now: Optional[datetime] = None) -> int`
    (flags `--verbose`, `--json`; `now` defaults to the current UTC time), `cli.check_entry() -> int`

Exact remediation texts (spec §6.3):

| id | text |
|---|---|
| python | `Install Python 3.9+ with python3 or python on PATH (or in the project .venv), then run specify extension add usage-bridge again.` |
| integration | `Run specify integration install claude, or specify extension disable usage-bridge if this project does not use Claude Code.` (Cursor-only projects additionally get WARN `Cursor capture is not supported in v0.1.`) |
| stop-hook / dispatcher | `Runtime events are disabled or were removed. Run: specify integration upgrade claude --integration-options="--events true"` |
| git | `git not found: branch fallback and worktree discovery are off.` |
| transcripts | `No Claude Code transcripts for this repository yet — run one agent turn, then check again.` / `No Claude projects directory found — set TOKEN_USAGE_PROJECTS_DIR or CLAUDE_CONFIG_DIR.` |
| runtime-dir | `Cannot write <path>: <OS error>` |
| last-capture | `Last capture failed at <ts>: <error> — see <log path>` / `Transcripts are newer than the last capture by more than a day — check the Stop hook.` |
| config | each config warning, e.g. `author.alias is set in the committed config; move it to usage-bridge-config.local.yml.` |

- [ ] **Step 1: Write the failing tests** — fixture `healthy(tmp_path) -> Path` builds a repo with
  `.specify/integration.json` `{"installed_integrations": ["claude"], "default_integration": "claude"}`,
  `.specify/events.py`, `.claude/settings.json`
  `{"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "\"python\" \"${CLAUDE_PROJECT_DIR}/.specify/events.py\" speckit.usage-bridge.capture stop 30", "__speckit_event__": true}]}]}}`,
  one transcript and `last-capture.json` with status `ok` 12 minutes before `now`.

```python
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

def test_healthy_prints_ok_line(tmp_path):
    p = healthy(tmp_path); out = io.StringIO()
    assert check_main([], out, dict(os.environ), p, now=NOW) == 0
    assert out.getvalue() == "Usage Bridge: ok (last capture 12 min ago)\n"

@pytest.mark.parametrize("break_it,check_id", [
    (lambda p: (p / ".specify/integration.json").write_text('{"installed_integrations": ["cursor-agent"]}'), "integration"),
    (lambda p: (p / ".claude/settings.json").write_text('{"hooks": {}}'), "stop-hook"),
    (lambda p: (p / ".specify/events.py").unlink(), "dispatcher")])
def test_failures_exit_1_with_remediation(break_it, check_id, tmp_path):
    p = healthy(tmp_path); break_it(p); out = io.StringIO()
    assert check_main([], out, dict(os.environ), p, now=NOW) == 1 and f"FAIL {check_id}:" in out.getvalue()

def test_events_disabled_remediation_text(tmp_path):
    p = healthy(tmp_path); (p / ".claude/settings.json").write_text('{"hooks": {}}')
    (r,) = [r for r in run_checks(p, dict(os.environ), NOW) if r.id == "stop-hook"]
    assert '--integration-options="--events true"' in r.remediation

def test_cursor_only_also_warns(tmp_path):
    p = healthy(tmp_path); (p / ".specify/integration.json").write_text('{"installed_integrations": ["cursor-agent"]}')
    assert any(r.level == "WARN" and "Cursor capture is not supported in v0.1" in r.message for r in run_checks(p, dict(os.environ), NOW))

def test_old_python_fails(tmp_path):
    assert not next(r for r in run_checks(healthy(tmp_path), dict(os.environ), NOW, python_version=(3, 8)) if r.id == "python").ok

def test_warnings_do_not_fail(tmp_path, monkeypatch):
    p = healthy(tmp_path); monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    out = io.StringIO()
    assert check_main([], out, dict(os.environ), p, now=NOW) == 0 and "WARN git:" in out.getvalue()

def test_last_capture_error_warns(tmp_path):
    p = healthy(tmp_path)
    (p / ".git/usage-bridge/last-capture.json").write_text(json.dumps({"ts": "2026-09-29T11:00:00.000Z", "status": "error", "error": "boom"}))
    (r,) = [r for r in run_checks(p, dict(os.environ), NOW) if r.id == "last-capture"]
    assert r.level == "WARN" and not r.ok and "boom" in r.remediation

def test_captures_not_running_warns(tmp_path):
    p = healthy(tmp_path)
    (p / ".git/usage-bridge/last-capture.json").write_text(json.dumps({"ts": "2026-09-27T12:00:00.000Z", "status": "ok"}))
    for t in (projects_root() / slug(p)).glob("*.jsonl"):
        os.utime(t, (NOW.timestamp(), NOW.timestamp()))
    (r,) = [r for r in run_checks(p, dict(os.environ), NOW) if r.id == "last-capture"]
    assert r.level == "WARN" and not r.ok and "check the Stop hook" in r.remediation

def test_alias_in_committed_config_warns(tmp_path):
    p = healthy(tmp_path); d = p / ".specify/extensions/usage-bridge"; d.mkdir(parents=True, exist_ok=True)
    (d / "usage-bridge-config.yml").write_text("author:\n  alias: team\n", encoding="utf-8")
    (r,) = [r for r in run_checks(p, dict(os.environ), NOW) if r.id == "config"]
    assert r.level == "WARN" and not r.ok and "usage-bridge-config.local.yml" in r.remediation

def test_json_and_verbose(tmp_path):
    p = healthy(tmp_path); out = io.StringIO(); check_main(["--json"], out, dict(os.environ), p, now=NOW)
    doc = json.loads(out.getvalue())
    assert doc["ok"] is True and [c["id"] for c in doc["checks"]] == ["python", "integration", "stop-hook", "dispatcher",
        "git", "transcripts", "runtime-dir", "last-capture", "config"]
    out = io.StringIO(); check_main(["--verbose"], out, dict(os.environ), p, now=NOW)
    assert out.getvalue().count("\n") == 9
```

(`check_main` accepts an optional keyword `now` for tests; production passes the current UTC time.)

- [ ] **Step 2: Run** `PYTEST tests/test_checks.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — Claude counts as installed when `"claude"` is in `installed_integrations`, or is
  `default_integration`, or the legacy `integration` key; the Stop check scans `hooks.Stop[*].hooks[*].command` for both
  `.specify/events.py` and `speckit.usage-bridge.capture`. Output: all ok → `Usage Bridge: ok (last capture N min ago)`
  (`(no capture yet)` when missing); otherwise one `FAIL <id>: <remediation>` / `WARN <id>: <message or remediation>`
  line per finding; `--verbose` prints one line per check; exit 1 iff any FAIL is not ok.

- [ ] **Step 4: Run** `PYTEST tests/test_checks.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add integration and environment checks"` · `git push`

---

### Task 17: Entrypoints, command files, manifest, config template

**Model:** implementer haiku · reviewer haiku

**Files:** Create `scripts/python/capture.py`, `scripts/python/report.py`, `scripts/python/check.py`, `commands/capture.md`,
`commands/report.md`, `commands/check.md`, `extension.yml`, `config-template.yml`, `tests/test_package_files.py`

**Interfaces:**
- Consumes: `cli.capture_entry`, `cli.report_entry`, `cli.check_entry`; spec §5.1 (config), §6.1 (manifest), §6.2 (commands).

- [ ] **Step 1: Write the failing tests**

```python
ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize("name", ["capture.py", "report.py", "check.py"])
def test_entrypoints_parse_with_python36_grammar(name):
    ast.parse((ROOT / "scripts/python" / name).read_text(encoding="utf-8"), feature_version=(3, 6))

def test_capture_entrypoint_is_silent_on_garbage(tmp_path):
    repo = make_repo(tmp_path)
    p = subprocess.run([sys.executable, str(ROOT / "scripts/python/capture.py")], input=b"garbage", cwd=repo,
                       capture_output=True, env=dict(os.environ))
    assert (p.returncode, p.stdout, p.stderr) == (0, b"", b"")

def test_manifest_matches_spec():
    assert yaml.safe_load((ROOT / "extension.yml").read_text(encoding="utf-8")) == EXPECTED_MANIFEST   # dict literal of spec §6.1

@pytest.mark.parametrize("cmd", ["capture", "report", "check"])
def test_command_files(cmd):
    text = (ROOT / "commands" / f"{cmd}.md").read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---")[1])
    manifest = {c["name"]: c for c in yaml.safe_load((ROOT / "extension.yml").read_text(encoding="utf-8"))["provides"]["commands"]}
    assert front["description"] == manifest[f"speckit.usage-bridge.{cmd}"]["description"]
    assert front["scripts"] == {"py": f"scripts/python/{cmd}.py"} and "{SCRIPT}" in text
    assert text.split("---", 2)[2].strip() == SPEC_BODIES[cmd]      # bodies of spec §6.2, verbatim

def test_config_template_yields_defaults(tmp_path):
    d = tmp_path / ".specify/extensions/usage-bridge"; d.mkdir(parents=True)
    shutil.copy(ROOT / "config-template.yml", d / "usage-bridge-config.yml")
    assert load_config(tmp_path, {}) == Config()
```

- [ ] **Step 2: Run** `PYTEST tests/test_package_files.py -q` → Expected: FAIL.

- [ ] **Step 3: Create the files** — `extension.yml`, `commands/*.md` and `config-template.yml` exactly as spec §6.1,
  §6.2 and §5.1. Each entrypoint follows this template (report/check print one line and return 1 on old Python):

```python
"""Usage Bridge — capture entrypoint (see commands/capture.md)."""
import os
import sys

sys.dont_write_bytecode = True


def _run():
    if sys.version_info < (3, 9):
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from usage_bridge import cli
    except Exception:
        return 0
    return cli.capture_entry()


if __name__ == "__main__":
    sys.exit(_run())
```

- [ ] **Step 4: Run** `PYTEST tests/test_package_files.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "feat: add entrypoints, command files, manifest and config template"` · `git push`

---

### Task 18: Release builder

**Model:** implementer haiku · reviewer haiku

**Files:** Create `tools/build_release.py`, `tests/test_build_release.py`

**Interfaces:**
- Produces: `build(repo: Path, version: str, out_dir: Path, base_url: str) -> Tuple[Path, Path]` (zip, catalog) and CLI
  `python tools/build_release.py --version X.Y.Z --out dist --base-url https://github.com/<owner>/<repo>`; also writes
  `dist/RELEASE_NOTES.md` (the CHANGELOG section of that version, empty if absent).

- [ ] **Step 1: Write the failing tests**

```python
BASE = "https://github.com/CrazyBaran/spec-kit-usage-bridge"

def test_zip_layout(tmp_path):
    z, _ = build(ROOT, "0.1.0", tmp_path, BASE)
    names = zipfile.ZipFile(z).namelist()
    assert z.name == "usage-bridge-v0.1.0.zip" and all(n.startswith("usage-bridge/") for n in names)
    for required in ("extension.yml", "THIRD_PARTY_NOTICES.md", "scripts/python/vendor/token_usage/LICENSE", "commands/report.md"):
        assert f"usage-bridge/{required}" in names
    assert not any(n.startswith(("usage-bridge/tests/", "usage-bridge/tools/", "usage-bridge/docs/", "usage-bridge/.github/")) for n in names)

def test_catalog_entry(tmp_path):
    _, c = build(ROOT, "0.1.0", tmp_path, BASE)
    cat = json.loads(c.read_text(encoding="utf-8")); e = cat["extensions"]["usage-bridge"]
    assert cat["schema_version"] == "1.0" and cat["catalog_url"] == f"{BASE}/releases/latest/download/catalog.json"
    assert e["download_url"] == f"{BASE}/releases/download/v0.1.0/usage-bridge-v0.1.0.zip"
    assert (e["version"], e["requires"]["speckit_version"], e["license"]) == ("0.1.0", ">=1.0.12", "MIT")

def test_version_must_match_manifest(tmp_path):
    with pytest.raises(SystemExit):
        build(ROOT, "9.9.9", tmp_path, BASE)
```

- [ ] **Step 2: Run** `PYTEST tests/test_build_release.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — file list = `git ls-files -z` minus `.extensionignore` patterns (dir patterns `name/` match
  any path component, `**/name/` likewise, plain names match a file or directory component); zip entries under
  `usage-bridge/`; catalog fields per spec §7.4 taken from `extension.yml` parsed with PyYAML (a development
  dependency — `tools/` is never shipped, so the stdlib-only rule does not apply); `created_at`/`updated_at` = UTC now;
  version mismatch → `SystemExit` with a message.

- [ ] **Step 4: Run** `PYTEST tests/test_build_release.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "build: add release zip and catalog builder"` · `git push`

---

### Task 19: Spec Kit integration tests

**Model:** implementer sonnet · reviewer sonnet

**Files:** Create `tests/integration/test_speckit.py`; modify `usage_bridge/checks.py` only if the pinned remediation
command does not re-enable events (then update the text and its unit test).

**Interfaces:**
- Consumes: builders; `tools/build_release.build`; the whole extension.
- Produces: `SPECIFY = ["uvx", "--from", "git+https://github.com/github/spec-kit.git@v1.0.12", "specify"]`; tests are
  `@pytest.mark.integration`, skipped when `uvx` is missing unless `UB_REQUIRE_INTEGRATION=1` (then they fail).

- [ ] **Step 1: Write the tests**

```python
def init(tmp_path, *extra):
    proj = tmp_path / "proj"
    run(SPECIFY + ["init", str(proj), "--integration", "claude", "--ignore-agent-tools", "--non-interactive", *extra])
    if not (proj / ".git").exists():
        subprocess.run(["git", "init", "-b", "main", str(proj)], check=True, capture_output=True)
    return proj

def stop_commands(proj):
    s = json.loads((proj / ".claude/settings.json").read_text(encoding="utf-8"))
    return [h["command"] for e in s.get("hooks", {}).get("Stop", []) for h in e["hooks"]]

def test_add_info_capture_remove(tmp_path):
    proj = init(tmp_path); run(SPECIFY + ["extension", "add", str(ROOT), "--dev"], cwd=proj)
    assert any(".specify/events.py" in c and "speckit.usage-bridge.capture" in c for c in stop_commands(proj))
    info = run(SPECIFY + ["extension", "info", "usage-bridge"], cwd=proj).stdout
    assert "speckit.usage-bridge.report" in info and "stop" in info
    (proj / "specs/001-login").mkdir(parents=True)
    (proj / ".specify/feature.json").write_text('{"feature_directory": "specs/001-login"}', encoding="utf-8")
    b = SessionBuilder("s1", cwd=proj); b.command("/speckit-specify"); b.reply("r1", output=10); main = b.write()
    p = subprocess.run([sys.executable, str(proj / ".specify/events.py"), "speckit.usage-bridge.capture", "stop", "30"],
                       input=json.dumps({"session_id": "s1", "transcript_path": str(main), "cwd": str(proj),
                                         "hook_event_name": "Stop"}).encode(), cwd=proj, capture_output=True)
    assert (p.returncode, p.stdout) == (0, b"") and (proj / "specs/001-login/token-usage.md").exists()
    run(SPECIFY + ["extension", "remove", "usage-bridge", "--force"], cwd=proj)
    assert not any("usage-bridge" in c for c in stop_commands(proj))
    assert not (proj / ".claude/skills/speckit-usage-bridge-report").exists()

def test_check_flags_disabled_events_and_remediation_restores(tmp_path):
    proj = init(tmp_path, "--integration-options=--events false"); run(SPECIFY + ["extension", "add", str(ROOT), "--dev"], cwd=proj)
    check = [sys.executable, str(proj / ".specify/extensions/usage-bridge/scripts/python/check.py")]
    p = subprocess.run(check, cwd=proj, capture_output=True, text=True)
    assert p.returncode == 1 and "FAIL stop-hook:" in p.stdout
    remedy = p.stdout.split("Run: ", 1)[1].splitlines()[0]
    run(["uvx", "--from", "git+https://github.com/github/spec-kit.git@v1.0.12", *shlex.split(remedy)], cwd=proj)
    assert subprocess.run(check, cwd=proj, capture_output=True, text=True).returncode == 0

def test_check_flags_missing_claude_integration(tmp_path):
    proj = init(tmp_path); run(SPECIFY + ["extension", "add", str(ROOT), "--dev"], cwd=proj)
    run(SPECIFY + ["integration", "uninstall", "claude"], cwd=proj)
    p = subprocess.run([sys.executable, str(proj / ".specify/extensions/usage-bridge/scripts/python/check.py")], cwd=proj, capture_output=True, text=True)
    assert p.returncode == 1 and "FAIL integration:" in p.stdout

def test_install_from_release_zip(tmp_path):
    zip_path, _ = build(ROOT, "0.1.0", tmp_path / "dist", "https://example.invalid")
    with serve(zip_path.parent) as base:                       # http.server thread on 127.0.0.1
        proj = init(tmp_path); run(SPECIFY + ["extension", "add", "usage-bridge", "--from", f"{base}/{zip_path.name}"], cwd=proj)
    assert (proj / ".specify/extensions/usage-bridge/extension.yml").exists()
```

`run(cmd, cwd=None)` = `subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, env=dict(os.environ))`;
`serve(directory)` = a context manager running `http.server.ThreadingHTTPServer` on `127.0.0.1:0` for `directory` in
a daemon thread and yielding its base URL.

- [ ] **Step 2: Run** `PYTEST tests/integration -m integration -q` → Expected: all pass. If a Spec Kit flag or the
  remediation command differs in v1.0.12, fix the test command or the `checks.py` text (and its unit test) — never the
  assertions of intent (Stop entry present/removed, files written, check fails then passes).

- [ ] **Step 3: Commit and push** — `git commit -m "test: add Spec Kit v1.0.12 integration tests"` · `git push`

---

### Task 20: `update-vendor`

**Model:** implementer haiku · reviewer haiku

**Files:** Create `tools/update-vendor.py`, `tests/test_update_vendor.py`

**Interfaces:**
- Produces: `update(repo: Path, ref: str, is_commit: bool, fetch: Callable[[str], bytes]) -> Dict[str, Any]` (the new
  `VENDOR.json`) and CLI `python tools/update-vendor.py <tag>` | `--commit <sha>`; archive URL
  `https://codeload.github.com/Wicked-Sick-Ltd/token-usage/zip/refs/tags/<tag>` or `/zip/<sha>`; commit id = the zip
  comment GitHub writes into archives. Tests load the script with `runpy`/`importlib` (hyphenated file name).

- [ ] **Step 1: Write the failing tests** — `mod` = `tools/update-vendor.py` loaded with
  `importlib.util.spec_from_file_location`; `copy_repo_vendor(tmp)` copies `scripts/python/vendor/token_usage` to
  `tmp/scripts/python/vendor/token_usage` and returns `tmp`; `fake_archive(files: Dict[str, bytes], comment: bytes) -> bytes`
  builds a zip with a `token-usage-x/` top folder.

```python
def test_update_replaces_only_vendored_files(tmp_path):
    repo = copy_repo_vendor(tmp_path)               # copies scripts/python/vendor/token_usage into tmp
    archive = fake_archive({"scripts/token_usage.py": b"print(1)\n", "data/pricing.json": b"{}\n", "LICENSE": b"MIT\n",
                            "CHANGELOG.md": b"## [0.7.0]\n- new\n", "README.md": b"x"}, comment=b"a" * 40)
    info = mod.update(repo, "v0.7.0", False, lambda url: archive)
    v = repo / "scripts/python/vendor/token_usage"
    assert (v / "scripts/token_usage.py").read_bytes() == b"print(1)\n" and not (v / "README.md").exists()
    assert (info["ref"], info["commit"]) == ("v0.7.0", "a" * 40)
    assert info["files"]["LICENSE"] == "sha256:" + hashlib.sha256(b"MIT\n").hexdigest()

def test_refuses_when_local_files_drifted(tmp_path):
    repo = copy_repo_vendor(tmp_path); (repo / "scripts/python/vendor/token_usage/LICENSE").write_bytes(b"edited")
    with pytest.raises(SystemExit):
        mod.update(repo, "v0.7.0", False, lambda url: b"")

def test_urls_for_tag_and_commit():
    assert mod.archive_url("v0.7.0", False).endswith("/zip/refs/tags/v0.7.0") and mod.archive_url("abc", True).endswith("/zip/abc")
```

- [ ] **Step 2: Run** `PYTEST tests/test_update_vendor.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** — verify current hashes first; extract only `scripts/token_usage.py`, `data/pricing.json`,
  `LICENSE`; rewrite `VENDOR.json` (`ref`, `commit`, `upstream_version` from the archive's CHANGELOG top section,
  `files`); print the CHANGELOG sections newer than the previous `upstream_version`; remind to run
  `PYTEST -m contract`. Network only through `fetch` (default `urllib.request.urlopen`).

- [ ] **Step 4: Run** `PYTEST tests/test_update_vendor.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "build: add vendor update tool"` · `git push`

---

### Task 21: CI and release workflows

**Model:** implementer haiku · reviewer haiku

**Files:** Create `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `tests/test_workflows.py`

- [ ] **Step 1: Write the failing tests**

```python
def wf(name): return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))

def test_ci_matrix_and_jobs():
    ci = wf("ci.yml"); jobs = ci["jobs"]
    assert ci["permissions"] == {"contents": "read"} and "workflow_call" in ci[True]      # PyYAML parses `on:` as True
    assert jobs["test"]["strategy"]["matrix"] == {"os": ["ubuntu-latest", "windows-latest"], "python": ["3.9", "3.x"]}
    assert jobs["integration"]["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest"]
    steps = json.dumps(jobs)
    assert "ruff check" in steps and "-m contract" in steps and "UB_REQUIRE_INTEGRATION" in steps and "setup-uv" in steps

def test_release_builds_and_publishes():
    rel = wf("release.yml")
    assert rel[True]["push"]["tags"] == ["v*"] and rel["jobs"]["release"]["needs"] == "ci"
    assert rel["jobs"]["release"]["permissions"] == {"contents": "write"}
    assert "tools/build_release.py" in json.dumps(rel) and "gh release create" in json.dumps(rel)
```

- [ ] **Step 2: Run** `PYTEST tests/test_workflows.py -q` → Expected: FAIL.

- [ ] **Step 3: Create the workflows** — `ci.yml` (`on: push, pull_request, workflow_call`; jobs `lint` = ruff + vendored
  hashes via `python -m pytest -m contract -k vendored_hashes`; `test` = matrix above, `pip install -r
  requirements-dev.txt`, `python -m pytest -m "not integration" -q` with `UB_PERF_MARGIN: "3"`; `integration` = matrix
  os, Python 3.12, `astral-sh/setup-uv`, `python -m pytest -m integration -q` with `UB_REQUIRE_INTEGRATION: "1"`).
  `release.yml` (`on: push: tags: ["v*"]`; job `ci` uses `./.github/workflows/ci.yml`; job `release` needs `ci`,
  `permissions: contents: write`, runs `python tools/build_release.py --version "${GITHUB_REF_NAME#v}" --out dist
  --base-url "https://github.com/${{ github.repository }}"` then `gh release create "$GITHUB_REF_NAME" dist/*.zip
  dist/catalog.json --notes-file dist/RELEASE_NOTES.md` with `GH_TOKEN`). Pin every action to its latest major tag at
  implementation time (`gh release view -R <owner>/<action> --json tagName`).

- [ ] **Step 4: Run** `PYTEST tests/test_workflows.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "ci: add test matrix, integration and release workflows"` · `git push`
  — then check the first run with `gh run list --branch feat/v0.1.0 --limit 1` and fix any red job before Task 22.

---

### Task 22: Performance budgets

**Model:** implementer sonnet · reviewer sonnet

**Files:** Create `tests/test_perf.py`; modify `digest.py` / `pipeline.py` only if a budget fails.

- [ ] **Step 1: Write the tests**

```python
pytestmark = pytest.mark.perf
MARGIN = float(os.environ.get("UB_PERF_MARGIN", "1"))

def test_cold_and_warm_capture(tmp_path):
    repo = make_repo(tmp_path, features=("001-login",))
    for i in range(200):
        b = SessionBuilder(f"s{i:03d}", cwd=repo, branch="001-login"); b.command("/speckit-implement")
        for j in range(50):
            b.reply(f"r{i}-{j}", input=100, output=200, cache_read=50_000, cache_5m=1_000)
        b.write()
    t = time.perf_counter(); run_capture("", repo, dict(os.environ)); cold = time.perf_counter() - t
    b = SessionBuilder("s199", cwd=repo, branch="001-login"); b.reply("extra", output=1)
    with (projects_root() / slug(repo) / "s199.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(b.entries[-1]) + "\n")
    t = time.perf_counter(); run_capture("", repo, dict(os.environ)); warm = time.perf_counter() - t
    assert cold < 5.0 * MARGIN and warm < 1.5 * MARGIN

def test_large_active_session_warm_path(tmp_path):
    repo = make_repo(tmp_path); b = SessionBuilder("big", cwd=repo, branch="001-login"); b.command("/speckit-implement")
    for j in range(40_000):
        b.reply(f"r{j}", input=10, output=20, cache_read=900_000)
    main = b.write(); run_capture("", repo, dict(os.environ))
    with main.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({**b.entries[-1], "requestId": "late"}) + "\n")
    t = time.perf_counter(); run_capture("", repo, dict(os.environ))
    assert time.perf_counter() - t < 1.5 * MARGIN
```

- [ ] **Step 2: Run** `PYTEST tests/test_perf.py -q` → Expected: PASS, or a failing budget to optimise (profile with
  `python -X importtime` / `cProfile`, then optimise the hot path without changing behaviour; all other tests stay green).

- [ ] **Step 3: Commit and push** — `git commit -m "test: add capture performance budgets"` · `git push`

---

### Task 23: Reconcile helper

**Model:** implementer haiku · reviewer haiku

**Files:** Create `tools/reconcile.py`, `tests/test_reconcile.py`

**Interfaces:**
- Produces: `upstream_usage(path: Path) -> Dict[str, int]` (`total.usage` of the vendored CLI
  `python <vendor>/scripts/token_usage.py json <transcript>`, run with `TOKEN_USAGE_LEDGER_DIR` pointing at a temp dir)
  and `reconcile(transcripts: Sequence[Path]) -> List[Dict[str, Any]]` → per transcript
  `{"transcript", "ours": {usage}, "upstream": {usage}, "equal": bool}` where `ours` sums `digest_session` requests
  (main + subagents); the CLI prints a table and exits 1 when any row differs. Tests load the script as `mod` via
  `importlib.util.spec_from_file_location`.

- [ ] **Step 1: Write the failing tests**

```python
def test_reconcile_matches_upstream_on_scenarios(tmp_path):
    mains = [m for name in ("split_sessions", "subagents_flat_and_nested", "requests_without_id") for m in ALL_SCENARIOS[name](tmp_path / name)]
    rows = mod.reconcile(mains)
    assert rows and all(r["equal"] for r in rows)

def test_reconcile_reports_difference(tmp_path, monkeypatch):
    (main,) = ALL_SCENARIOS["specify_plan_one_session"](tmp_path)
    monkeypatch.setattr(mod, "upstream_usage", lambda path: {"input": -1})
    assert mod.reconcile([main])[0]["equal"] is False
```

- [ ] **Step 2: Run** `PYTEST tests/test_reconcile.py -q` → Expected: FAIL.

- [ ] **Step 3: Implement** as described; usage keys compared: `input, output, cache_read, cache_5m, cache_1h`.

- [ ] **Step 4: Run** `PYTEST tests/test_reconcile.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "build: add upstream reconciliation helper"` · `git push`

---

### Task 24: Documentation

**Model:** implementer haiku · reviewer sonnet

**Files:** Modify `README.md`; create `CHANGELOG.md`, `docs/limitations.md`, `docs/release.md`, `tests/test_docs.py`

- [ ] **Step 1: Write the failing tests**

```python
def read(p): return (ROOT / p).read_text(encoding="utf-8")

def test_readme_sections():
    r = read("README.md")
    assert "specify extension catalog add --name usage-bridge --install-allowed https://github.com/CrazyBaran/spec-kit-usage-bridge/releases/latest/download/catalog.json" in r
    assert "specify extension add usage-bridge" in r and "--from" in r
    for name in ("token-analyzer", "Cost Tracker", "token-budget"):
        assert name in r
    assert "transcript parsing, segmenting and pricing" in r and "docs/limitations.md" in r
    assert "not affiliated" in r and "WARNING" not in r

def test_limitations_list():
    lim = read("docs/limitations.md")
    assert len(re.findall(r"^\d+\. ", lim, flags=re.M)) == 15 and "Upstream candidates" in lim

def test_changelog_and_release_doc():
    assert "## [0.1.0]" in read("CHANGELOG.md") and "f4078277e79c007993e0cb595bb95f924a2a8777" in read("CHANGELOG.md")
    rel = read("docs/release.md")
    assert "tools/update-vendor.py" in rel and "catalog.json" in rel and "specify extension update usage-bridge" in rel
```

- [ ] **Step 2: Run** `PYTEST tests/test_docs.py -q` → Expected: FAIL.

- [ ] **Step 3: Write the docs** from spec §10 (README contents list, credit wording, relation table, setup snippets
  for bash and PowerShell running `check.py` and failing on exit 1), the limitations list and upstream candidates
  (spec "Limitations and assumptions"), the release/update flow (§7), and a `CHANGELOG.md` 0.1.0 entry naming the
  vendored commit. Remove the README "work in progress" warning and mark the status table rows done.

- [ ] **Step 4: Run** `PYTEST tests/test_docs.py -q && RUFF` → Expected: all pass.

- [ ] **Step 5: Commit and push** — `git commit -m "docs: add README, changelog, limitations and release guide"` · `git push`

---

### Final: whole-branch review and verification (main session)

- [ ] Dispatch the whole-branch reviewer (model **opus**) per superpowers:requesting-code-review over
  `docs/v0.1-implementation-plan..feat/v0.1.0` with the spec and this plan; act on findings per
  superpowers:receiving-code-review.
- [ ] superpowers:verification-before-completion — run and record: `PYTEST -q` (all markers),
  `PYTEST -m integration -q`, `RUFF`, CI green on both OSes (`gh run list --branch feat/v0.1.0`).
- [ ] Acceptance real run with the user (spec §9): scratch Spec Kit project, session 1 `/speckit-specify` +
  `/speckit-plan`, session 2 `/speckit-tasks`, in the desktop Code tab and in the CLI, plus a real `/clear` and a
  `--fork-session`; verify 3 phases, 2 sessions, re-priming and verdict for session 2, `last-capture.json` duration
  < 5 s, and `python tools/reconcile.py <both transcripts>` equal.
- [ ] superpowers:finishing-a-development-branch — present merge/PR options (nothing merged, tagged or released
  without the user's explicit OK).
