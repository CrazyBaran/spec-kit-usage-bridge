# Usage Bridge implementation: architecture and Python practice references

Research date: **2026-10-02**. Scope: developing and maintaining **Usage Bridge itself**, including work by different coding assistants. These recommendations are not instructions for projects installing the extension.

## Findings and evidence quality

The recommended approach is a concise shared development contract, explicit module boundaries, and executable checks in CI. Agent instructions help communicate intent; they cannot guarantee architecture or accounting correctness. Preserve the existing standard-library runtime and extension installation model while improving development tooling.

This is a curated selection, not an exhaustive survey or a claim that one architecture is universally best. Official documentation establishes tool behavior; original architecture articles explain principles; research papers provide bounded empirical evidence. The adoption decisions below are project-specific judgments. Research-paper summaries are based on the inspected abstracts and metadata, not independent reproduction. Repository links are implementation resources, not evidence that a tool has been tested here. No proposed tools were installed or benchmarked during this research.

All numbered sources were opened during research. Dates appear where verified; living documentation is identified as such. For collective documentation, the organization or project is credited instead of inventing an individual author. Summaries are paraphrases. Links may redirect as documentation moves.

## Repository context

The inspected implementation already has:

- Python 3.9 compatibility and a standard-library-only runtime requirement in its design documents.
- A runtime-neutral `RuntimeAdapter` protocol and provider implementations under `scripts/python/usage_bridge/adapters/`.
- A shared capture orchestrator in `pipeline.py`, with some explicit provider-specific integration imports. A stricter boundary would therefore need migration, not merely a new failing rule.
- A declared vendor boundary in `tu_compat.py`, which dynamically loads the pinned upstream implementation.
- Measurement-quality handling in `measurement.py`; missing usage remains distinct from a measured zero.
- Source-schema normalization in `schema.py`, synthetic fixtures, golden reports, and a hermetic environment fixture in `tests/conftest.py`.
- Ruff linting, pytest, vendor hash checks, and Windows/Linux CI with Python 3.9 and a floating latest Python version.
- A custom extension layout rather than a Python distribution. Development docs are already excluded by `.extensionignore`.

These observations identify useful adoption targets; they are not a complete architecture or security audit. The existing tests were inspected, not executed for this documentation-only task.

## Recommended adoption order

| Priority | Practice | Bridge application | Evidence |
|---|---|---|---|
| First | One concise shared agent contract | Add root `AGENTS.md`; use provider compatibility files only where needed; keep long research outside startup context | 1–7 |
| First | Document responsibilities and decisions | `docs/architecture.md` plus small ADRs for runtime dependencies, accounting, privacy, and provider boundaries | 10–13 |
| First | Enforce selected import boundaries | Start with forbidden imports and vendor isolation; map existing dependencies before imposing layers | 12, 13 |
| First | Consistent lint and formatting | Retain Ruff; baseline formatting separately; add check mode after reviewing the diff | 14 |
| Next | Gradual static typing | Start at adapter interfaces and normalized models; prevent new errors in selected modules | 15–17 |
| Next | Property and contract testing | Duplicate requests, missing counts, schema upgrades, provider capabilities, and deterministic merging | 18–20 |
| Next | Reliability and privacy contracts | Bounded subprocesses, safe report replacement, explicit logging/redaction, silent hook behavior | 23–26 |
| Next | Development and CI reproducibility | Optional pre-commit, least-privilege CI, action SHA pins, deliberate Python support policy | 22, 27, 28 |
| Later | Targeted mutation testing | Test accounting assertions on Linux or WSL before considering a broader job | 21 |
| Optional | Custom semantic lint rules | Only if an important rule cannot be expressed with existing tools or small architecture tests | 29, 30 |

## Agent instructions and evidence

### 1. AGENTS.md: open format and examples

- **Author/maintainer:** AGENTS.md community; stewarded by the Agentic AI Foundation under the Linux Foundation.
- **Type:** Living specification-style guidance and examples.
- **Links:** [Format and examples](https://agents.md/); [source repository](https://github.com/agentsmd/agents.md).
- **Summary:** A predictable Markdown location for repository commands, conventions, and agent guidance, with support across multiple coding tools. Nested files can scope instructions, but actual loading behavior is tool-specific.
- **Adopt:** Make root `AGENTS.md` the canonical development contract. Include exact validation commands and unusual constraints: stdlib runtime, vendor isolation, silent capture, privacy, and missing-versus-zero accounting. Keep detailed explanations in linked documentation.
- **Caution:** An open format does not make every assistant's precedence, import syntax, or enforcement identical.

### 2. Codex: custom instructions with AGENTS.md

- **Author:** OpenAI documentation team.
- **Type:** Living official documentation.
- **Link:** [Codex AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md).
- **Summary:** Describes how Codex discovers repository and directory guidance, including override and fallback mechanisms.
- **Adopt:** Use the standard filename and test discovery in the actual coding environment. State which checks are required for source, adapter, schema, and release changes.
- **Caution:** Do not assume a filename such as `agent.md` is automatically recognized. Avoid putting the entire references catalogue into automatically loaded instructions.

### 3. Claude Code: project memory and shared AGENTS.md

- **Author:** Anthropic documentation team.
- **Type:** Living official documentation.
- **Link:** [How Claude remembers your project](https://code.claude.com/docs/en/memory).
- **Summary:** Covers `CLAUDE.md`, imports, scoped rules, and direct `AGENTS.md` support. The inspected docs state that direct support requires v2.1.277 or later and depends on instruction settings and the presence of Claude instruction files.
- **Adopt:** Keep one canonical `AGENTS.md`. For compatibility, a root `CLAUDE.md` containing `@AGENTS.md` is supported. Verify loading in the deployed Claude version. Prefer this import to symlinks in a Windows repository.
- **Caution:** A Claude instruction file can change which AGENTS files load. Imports consume context too. Plain prose telling Claude to read another file is weaker than a supported import.

### 4. Claude Code: best practices

- **Author:** Anthropic documentation team.
- **Type:** Living official workflow guidance.
- **Links:** [Current best practices](https://code.claude.com/docs/en/best-practices); [original engineering article, 2025-04-18](https://www.anthropic.com/engineering/claude-code-best-practices).
- **Summary:** Emphasizes giving agents a way to verify their work, managing context, and keeping instructions useful and specific.
- **Adopt:** Describe expected outcomes and how to check them: contract fixtures for adapters, golden reports for rendering, and timeout/exit behavior for hook changes. Link canonical examples rather than repeat large code samples.
- **Caution:** Adapt workflow advice to task size; do not require a heavyweight process for every documentation edit.

### 5. Cursor: rules and AGENTS.md

- **Author:** Cursor documentation team.
- **Type:** Living official documentation.
- **Link:** [Cursor rules](https://cursor.com/docs/rules).
- **Summary:** Supports `AGENTS.md` and scoped project rules. Recommends focused, actionable guidance, references to canonical files, and using lint tools for style rules.
- **Adopt:** Use the shared contract for common bridge requirements. Add scoped rules only when a repeated adapter or release mistake justifies them.
- **Caution:** Avoid maintaining a second full architecture policy in `.cursor/rules/`; duplicated instructions become inconsistent.

### 6. Gemini CLI: context files

- **Author:** Google/Gemini CLI contributors.
- **Type:** Living official documentation.
- **Link:** [Provide context with GEMINI.md files](https://geminicli.com/docs/cli/gemini-md/).
- **Summary:** Explains hierarchical context files, imports, and configurable context filenames.
- **Adopt:** Configure a shared filename where supported, or use a minimal Gemini entry point referencing the canonical contract. Verify loading with the installed CLI.
- **Caution:** Do not assume Claude's import or precedence behavior applies to Gemini.

### 7. GitHub Copilot: repository custom instructions

- **Author:** GitHub documentation team.
- **Type:** Living official documentation.
- **Link:** [Repository instructions](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions).
- **Summary:** Documents repository-wide, path-specific, and agent instruction mechanisms, with support differing by Copilot surface.
- **Adopt:** If Copilot is used to develop the bridge, select its supported mechanism for that environment and reference the same project contract. Keep critical rules in CI regardless of surface.
- **Caution:** Do not promise universal AGENTS loading across chat, review, IDE, and coding-agent features.

### 8. Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?

- **Authors:** Thibaud Gloaguen, Niels Mündler-Sasahara, Mark Niklas Müller, Veselin Raychev, Martin Vechev.
- **Date/type:** Research preprint; first submitted 2026-02-12; inspected revision v3, 2026-09-29.
- **Link:** [Paper and metadata](https://arxiv.org/abs/2602.11988v3).
- **Summary:** The abstract reports that context files did not generally improve task success and increased inference cost by over 20% on average in the studied settings. Instructions were followed; generic repository overviews were not useful. The authors identify non-standard practices as a useful role for context files.
- **Adopt:** Prioritize requirements an assistant cannot safely infer: accounting semantics, vendor constraints, privacy defaults, and hook behavior. Evaluate instructions against representative bridge tasks.
- **Caution:** This is study-specific evidence, not proof that all instruction files are harmful. Abstract-level review only.

### 9. On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents

- **Authors:** Jai Lal Lulla, Seyedmoein Mohsenimofidi, Matthias Galster, Jie M. Zhang, Sebastian Baltes, Christoph Treude.
- **Date/type:** Research preprint; submitted 2026-01-28; inspected revision v2, 2026-03-30.
- **Link:** [Paper and metadata](https://arxiv.org/abs/2601.20404v2).
- **Summary:** Studies 124 pull requests across ten repositories. The abstract reports lower median runtime and output-token consumption with context files, with comparable completion behavior.
- **Adopt:** Judge the bridge's contract by both correctness and cost/time, comparing similar tasks across assistants where practical.
- **Caution:** Its efficiency findings and reference 8's findings use different settings and measures. Neither establishes a universal recipe or a guaranteed improvement for this repository. Abstract-level review only.

## Architecture and enforceable boundaries

### 10. Hexagonal architecture / ports and adapters

- **Author:** Alistair Cockburn.
- **Type:** Original architecture article.
- **Link:** [Hexagonal architecture](https://alistair.cockburn.us/hexagonal-architecture).
- **Summary:** Separates application behavior from external interfaces through ports and adapters, allowing the same application to be exercised through different technologies and tests.
- **Adopt:** Treat `RuntimeAdapter` as the provider seam. Normalize external events before shared attribution, measurement, and reporting. Keep provider format details near the corresponding adapter.
- **Caution:** This does not require an elaborate framework, new package tree, or one class per function. Existing provider-specific orchestration needs deliberate handling before enforcing an idealized boundary.

### 11. Architecture Patterns with Python / Cosmic Python

- **Authors:** Harry Percival and Bob Gregory.
- **Type:** Open-access book and example repository; book published 2020.
- **Links:** [Book](https://www.cosmicpython.com/); [dependency inversion and repository chapter](https://www.cosmicpython.com/book/chapter_02_repository); [example code](https://github.com/cosmicpython/code).
- **Summary:** Explains dependency inversion and testable application boundaries using Python examples, including repositories, service layers, and domain models.
- **Adopt:** Separate pure accounting transformations from filesystem, provider discovery, environment, and subprocess operations. Make clocks and external inputs explicit where tests need control.
- **Caution:** The bridge is not the book's database application. Do not introduce an ORM, unit of work, or event bus simply to reproduce its examples.

### 12. Import Linter: architecture contracts

- **Author/maintainer:** Import Linter project, repository owner `seddonym`; collective project credit used here.
- **Type:** Official documentation and implementation repository.
- **Links:** [Contract types](https://import-linter.readthedocs.io/en/stable/contract_types/); [forbidden contracts](https://import-linter.readthedocs.io/en/stable/contract_types/forbidden/); [layers](https://import-linter.readthedocs.io/en/stable/contract_types/layers/); [repository](https://github.com/seddonym/import-linter).
- **Summary:** Turns allowed dependency relationships into checks, including forbidden imports and ordered layers. Forbidden contracts distinguish direct and indirect dependency policies.
- **Adopt:** Begin with a few justified rules: adapters must not depend on CLI orchestration; provider implementations should not depend on one another; core computations should not acquire provider discovery responsibilities. Map the current graph and explain narrow exceptions.
- **Caution:** Dynamic vendor loading in `tu_compat.py` needs supplementary checks. Import-graph contracts do not validate runtime behavior, imports hidden in strings, or all third-party dependency policy. Choose direct versus transitive restrictions intentionally.

### 13. Documenting Architecture Decisions

- **Author:** Michael Nygard.
- **Date/type:** 2011-11-15; original article.
- **Links:** [Article](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions); [ADR community resources](https://adr.github.io/).
- **Summary:** Advocates small records explaining the context, decision, status, and consequences of consequential architectural choices.
- **Adopt:** Record why runtime dependencies are constrained, why vendor changes are isolated, how incomplete measurements are represented, and why hook errors do not interrupt agent work. Reference these decisions from the architecture guide.
- **Caution:** Record real tradeoffs; avoid creating a decision record for every routine edit. Supersede old decisions rather than erase their rationale.

## Python tooling and contracts

### 14. Ruff: linting and formatting

- **Author/maintainer:** Astral and Ruff contributors.
- **Type:** Official documentation and repository.
- **Links:** [Overview](https://docs.astral.sh/ruff/); [formatter](https://docs.astral.sh/ruff/formatter/); [rules](https://docs.astral.sh/ruff/rules/); [repository](https://github.com/astral-sh/ruff).
- **Summary:** Provides linting and formatting in one tool, with configurable rules and a non-mutating formatter check.
- **Adopt:** Keep existing `E/F/W/I/B/UP` checks. Evaluate focused additional rules for accidental prints, subprocess safety, and exception handling. Review the formatter baseline separately, then require `ruff format --check` in CI.
- **Caution:** Do not enable every rule. Preserve entry-point compatibility exceptions, vendor exclusion, line length, and Python target settings until intentionally changed. Formatting alone does not prove correctness.

### 15. Python typing best practices

- **Author:** Python typing documentation contributors.
- **Type:** Living official typing guidance.
- **Link:** [Typing best practices](https://typing.python.org/en/latest/reference/best_practices.html).
- **Summary:** Gives guidance on annotations, useful abstractions, and writing types that express intent clearly.
- **Adopt:** Type shared provider contracts and accounting data first. Use named normalized structures instead of expanding loosely specified `dict[str, Any]` throughout the pipeline. Keep external raw data distinct from validated internal data.
- **Caution:** Type annotations do not validate transcript JSON at runtime. Avoid type complexity that makes accounting rules harder to read.

### 16. mypy: adopting typing in an existing codebase

- **Author/maintainer:** mypy contributors, Python organization repository.
- **Type:** Official migration guidance and repository.
- **Links:** [Existing-codebase guide](https://mypy.readthedocs.io/en/stable/existing_code.html); [repository](https://github.com/python/mypy).
- **Summary:** Describes incremental checking and gradual tightening rather than requiring a fully typed codebase immediately.
- **Adopt:** Start with adapter interfaces, measurement models, and selected pure modules. Establish a baseline, require selected modules to stay clean, and expand coverage. Run development tools on a supported interpreter while separately testing runtime compatibility.
- **Caution:** Avoid blanket ignores that hide errors. Check tool-version compatibility before pinning; latest tool releases need not run on the bridge's oldest supported Python.

### 17. Python Protocol and TypedDict contracts

- **Author:** Python documentation contributors / Python Software Foundation.
- **Type:** Official standard-library documentation.
- **Link:** [typing documentation](https://docs.python.org/3/library/typing.html).
- **Summary:** Documents structural typing with `Protocol` and typed dictionary shapes with `TypedDict`; these provide static descriptions rather than runtime input validation.
- **Adopt:** Extend the existing `RuntimeAdapter` protocol where genuinely shared behavior is required. Consider `TypedDict` for serialized payloads and dataclasses for internal values, with explicit normalization between them.
- **Caution:** Use syntax and APIs available on the supported runtime. Do not copy newer `type` statement syntax or APIs from current docs into Python 3.9 code.

## Testing accounting and provider behavior

### 18. pytest: good integration practices

- **Author:** pytest contributors.
- **Type:** Official documentation.
- **Link:** [Good integration practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html).
- **Summary:** Explains test discovery, import behavior, layouts, and integration with development workflows.
- **Adopt:** Preserve hermetic fixtures and separate integration markers. Parameterize common provider contract tests; test output behavior and normalization rather than mirror private implementation steps.
- **Caution:** Generic packaging/layout advice must fit this extension. Moving to a conventional distributable `src/` package is not necessary merely because other Python projects use one.

### 19. Hypothesis: property-based testing

- **Author/maintainer:** HypothesisWorks and contributors.
- **Type:** Official tutorial and repository.
- **Links:** [Introduction](https://hypothesis.readthedocs.io/en/latest/tutorial/introduction.html); [repository](https://github.com/hypothesisworks/hypothesis).
- **Summary:** Generates many inputs from strategies and reduces failing cases to smaller examples, complementing example-based tests.
- **Adopt:** Test explicit properties: deduplicating an already deduplicated set changes nothing; adding repeated observations cannot double-charge a request; absent counts remain unknown; schema normalization does not mutate caller data. Check permutation invariance only where chronology and snapshot selection permit it.
- **Caution:** Bound generated filesystem scenarios and runtime. Keep concrete provider fixtures and golden reports; generated tests do not replace them. Confirm current properties before encoding them as requirements.

### 20. Coverage.py: branch coverage

- **Author/maintainer:** Coverage.py project and contributors.
- **Type:** Official documentation.
- **Link:** [Branch coverage measurement](https://coverage.readthedocs.io/en/latest/branch.html).
- **Summary:** Measures whether alternative control-flow destinations execute, revealing gaps that line coverage can miss.
- **Adopt:** Inspect branches for malformed provider events, incomplete measurements, schema rejection, deadline expiration, and lock contention. Use gaps to choose meaningful tests.
- **Caution:** Coverage is not an assertion-quality measure. Avoid a blanket 100% gate that encourages tests with little behavioral value.

### 21. mutmut: mutation testing

- **Author/maintainer:** mutmut contributors; repository owner `boxed`.
- **Type:** Tool repository and usage documentation.
- **Link:** [mutmut repository](https://github.com/boxed/mutmut).
- **Summary:** Alters code and runs tests to identify changes that assertions fail to detect. The inspected documentation requires fork support; Windows use requires WSL.
- **Adopt:** Pilot on small pure accounting functions: deduplication, quality selection, attribution fallbacks, and pricing. Run on Linux CI or WSL, with a limited budget.
- **Caution:** Do not impose it on the native Windows fast loop or the entire repository initially. Inspect survivors; not all indicate a useful missing test.

### 22. pre-commit: repeatable local checks

- **Author/maintainer:** pre-commit contributors.
- **Type:** Official documentation and hook framework.
- **Link:** [pre-commit](https://pre-commit.com/).
- **Summary:** Manages versioned hooks and isolated tool environments so teams can run consistent checks before submitting changes.
- **Adopt:** Offer fast Ruff and whitespace/configuration checks locally. Pin versions and keep the same essential checks in CI.
- **Caution:** Hooks can be skipped and are not the enforcement boundary. Keep network-heavy integration tests out of every commit. Exclude vendored code and development files from extension distribution as appropriate.

## Reliability, privacy, and maintenance

### 23. Python os.replace: report replacement

- **Author:** Python documentation contributors / Python Software Foundation.
- **Type:** Official API documentation.
- **Link:** [os.replace](https://docs.python.org/3/library/os.html#os.replace).
- **Summary:** Describes replacing a destination with a source file; cross-filesystem replacement may fail, and atomic renaming guarantees have platform qualifications.
- **Adopt:** Review report/checkpoint writing for temporary files in the destination directory followed by replacement. Test interrupted writes, cleanup, Windows open-file failures, and permissions.
- **Caution:** Atomic replacement is not a multi-file transaction or a durability guarantee. It does not replace locking or guarantee consistent simultaneous updates of all report files.

### 24. Python subprocess: security and timeouts

- **Author:** Python documentation contributors / Python Software Foundation.
- **Type:** Official API documentation.
- **Link:** [subprocess documentation](https://docs.python.org/3/library/subprocess.html).
- **Summary:** Covers argument handling, timeout behavior, output capture, and shell-related security considerations, including Windows differences.
- **Adopt:** Prefer explicit argument lists for git and helper calls; bound subprocess work by the remaining capture deadline. Test unavailable commands, failure status, output volume, and path quoting.
- **Caution:** Windows batch execution has special shell behavior. Do not assume one quoting rule covers every executable or shell. Handle timeout cleanup deliberately.

### 25. OWASP Logging Cheat Sheet

- **Author:** OWASP Cheat Sheet Series contributors.
- **Type:** Primary security guidance.
- **Link:** [Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).
- **Summary:** Explains useful event logging while excluding sensitive data, handling untrusted input, and protecting logs.
- **Adopt:** Log provider identity, failure category, and capture status without transcript bodies, credentials, or unintended local paths. Use sanitized fixtures to verify preview defaults and failure logging.
- **Caution:** Bridge logs and committed reports have different audiences and retention. Avoid copying entire malformed payloads into exceptions or logs just to aid debugging.

### 26. Python logging: explicit diagnostics

- **Author:** Python documentation contributors / Python Software Foundation.
- **Type:** Official standard-library documentation.
- **Link:** [logging documentation](https://docs.python.org/3/library/logging.html).
- **Summary:** Describes logging levels, handlers, formatting, and exception information.
- **Adopt:** Define where exceptions may be caught to preserve silent capture, which failures become partial results, and which diagnostics enter status files. Keep module imports free of logging-configuration side effects.
- **Caution:** Broad catches may be appropriate at the hook boundary, but swallowing errors inside pure accounting logic can conceal bad data. Exception messages require the same privacy review as normal logs.

### 27. GitHub Actions: secure use

- **Author:** GitHub documentation team.
- **Type:** Official CI security guidance.
- **Link:** [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use).
- **Summary:** Explains least-privilege permissions, untrusted-input handling, and pinning actions to full commit SHAs.
- **Adopt:** Retain read-only default permissions; review release-job permissions separately. Consider SHA pins with readable version comments and an update process. Avoid inserting pull-request metadata directly into shell scripts.
- **Caution:** SHA pins require maintenance. Recommendations here do not constitute an audit of every existing workflow or release permission.

### 28. Python support lifecycle

- **Author:** Python Developer's Guide contributors; Python core development team.
- **Type:** Official living version-status reference.
- **Link:** [Status of Python versions](https://devguide.python.org/versions/).
- **Summary:** Records supported and end-of-life interpreter branches. The inspected table lists Python 3.9 end-of-life as 2025-10-31 and Python 3.10 end-of-life as 2026-10-01.
- **Adopt:** Make a deliberate support decision: retain 3.9 compatibility for installation reach with a documented policy, or plan a supported minimum such as 3.11+. Keep development-tool Python requirements separate from runtime requirements. Consider a fixed recent stable CI version plus a separate forward-compatibility job.
- **Caution:** Do not silently raise the minimum in a tooling change. A migration affects entry-point guards, docs, lint targets, dependencies, tests, and installed users.

## Medium and custom rule development

### 29. How to Easily Extend Pylint With Plugins

- **Author:** Eldad Uzman; published in Better Programming on Medium.
- **Date/type:** 2022-04-04; original practitioner tutorial.
- **Link:** [Medium article](https://medium.com/better-programming/how-to-easily-extend-pylint-with-plugins-d8ead26a68ac).
- **Access:** Article text was accessible during research; no login was needed.
- **Summary:** Demonstrates a custom Pylint checker using plugin registration and AST visitor methods, turning a project-specific code rule into a repeatable diagnostic.
- **Adopt:** Consider the technique only for important semantic constraints that standard tools cannot express. For example, a custom rule could flag a forbidden output call in selected hook modules.
- **Caution:** The tutorial predates current Pylint APIs. Use reference 30 for implementation details. Its duplicate-import example does not justify adding Pylint alongside Ruff. Small AST-based tests may be cheaper to maintain for a handful of bridge-specific rules.

### 30. Pylint: writing a custom checker

- **Author:** Pylint contributors.
- **Type:** Official development documentation.
- **Link:** [How to Write a Checker](https://pylint.readthedocs.io/en/latest/development_guide/how_tos/custom_checkers.html).
- **Summary:** Describes checker registration, AST-based analysis, messages, and checker testing.
- **Adopt:** If a custom checker is selected, define its scope and diagnostic, test allowed and prohibited cases, and pin the tooling version. Keep it a development dependency.
- **Caution:** This is an alternative for specialized rules, not a recommendation to add another general linter immediately. The linked latest docs may describe development APIs; select documentation matching the pinned release.

### Medium candidate not used as evidence

[Good Fences: The Academic Catalog and the Import Boundary That Broke Once a Module Used It](https://medium.com/@bessavagner/good-fences-the-academic-catalog-and-the-import-boundary-that-broke-once-a-module-used-it-26ca00e54c14) appeared in search results with a discussion of direct versus transitive import boundaries. Opening the page failed during this research. The profile handle is `@bessavagner`; authorship and full content were not verified. It is an optional follow-up reading candidate, not support for any recommendation here. Its practical topic is already covered by the opened official Import Linter documentation. A browser login may help further Medium research, but no paywall was bypassed and no unread article was summarized as reviewed.

## Proposed development contract and checks

These are adoption proposals, not rules installed by this research change.

1. **Shared instructions:** root `AGENTS.md`, with an optional `CLAUDE.md` import for compatibility. Keep startup guidance short; link architecture, decisions, and canonical tests. Verify loading in each actual assistant.
2. **Architecture guide:** state ownership of provider discovery/parsing, normalized data, attribution/deduplication, measurement/pricing, persistence, and rendering. Describe existing exceptions before planning changes.
3. **Architecture checks:** establish the current import graph; enforce a small number of approved boundaries. Supplement graph tools with tests for dynamic vendor access and forbidden runtime dependencies.
4. **Python checks:** retain current linting and compatibility exceptions. Baseline formatting independently. Introduce scoped type checking with an explicit error budget of zero for newly checked modules.
5. **Correctness properties:** define missing-versus-zero, request identity, cumulative observations, inherited usage, measurement quality, and snapshot selection before adding generated tests. Provider capabilities must stay explicit.
6. **Reliability tests:** exercise deadlines, malformed input, partial results, safe writes, contention, and silent hook exits. Preserve hermetic defaults; integration tests remain a separate tier.
7. **Distribution checks:** development-only instructions and tooling must not enter the extension archive. `docs/` is already excluded; future root instruction files and tool configs need their own exclusions and package-file checks.
8. **Decision records:** explain stdlib-only runtime, vendor policy, supported Python versions, accounting assumptions, and privacy defaults. Update records when a decision is intentionally superseded.

## Practices to avoid adopting mechanically

- Huge generated agent handbooks, duplicated provider policies, and unmeasured claims that instructions guarantee better code.
- Rebuilding the extension as a conventional Python package merely to match a template.
- Adding runtime dependencies, an ORM, a dependency-injection framework, async orchestration, or an event bus without a bridge-specific need.
- Enabling every lint rule, demanding total coverage, or enforcing strict typing everywhere before a baseline exists.
- A rigid layer rule that ignores the current dependency graph, or a static import check presented as proof of dynamic behavior.
- Applying newer Python syntax without a compatibility decision, or running new development tools on an interpreter they no longer support.
- Reformatting or editing vendored upstream code as part of routine cleanup.

## How to evaluate whether adoption helps

Use a small repeatable task set: add a synthetic provider field; fix duplicate usage; preserve unknown counts; handle a malformed source; change a report; update a schema. Compare assistants using the same task descriptions and independent expected outcomes. Track correctness, boundary violations, review corrections, time, and cost where observable. Keep instructions that prevent recurring mistakes; remove redundant ones. This evaluation plan is a project recommendation inspired by references 8–9, not a reproduced research result.

Recheck living tool documentation before implementation. Record selected versions and completed adoption decisions separately from this references catalogue.
