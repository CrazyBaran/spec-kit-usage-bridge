# Native event verification

Windows integration tests use Spec Kit 1.0.12 to install, dispatch native-shaped
payloads, and remove the extension for Claude, Codex and Cursor. These establish
dispatcher compatibility, not delivery by an authenticated agent.

Codex 0.159.2 and Cursor's editor CLI 3.22.12 are available on the development
machine. Authenticated native delivery has not been verified. Codex and Cursor
therefore remain manual/unverified for automatic capture. Run the capture or
report command after working; a project with delivered Cursor hooks also retains
private activity ledgers. The Cursor editor CLI is distinct from `cursor-agent`.

To verify native delivery in disposable projects on an authenticated machine:

```powershell
$env:UB_NATIVE_SMOKE = '1'
python -m pytest tests/integration/test_native_events.py -q
```

The smoke tests require `uvx`, network access, project trust, and the relevant
authenticated CLI. They run a short agent request and assert that the native
event produced capture state. A skipped test is not evidence of automatic support.
Run each supported operating system and runtime version before changing the
support claim. macOS/Linux native delivery remains unverified.

## v0.2.1 checkpoint coverage

The fourth command and after-specify workflow hook are supplemental to native
runtime events. Synthetic checkpoint tests verify selection and report refresh
for Claude, Codex and Cursor. Real Spec Kit installation tests verify rendering
and removal. These checks do not establish authenticated native event delivery;
Codex/Cursor automatic delivery remains unverified. Explicit later-phase
checkpoints are required even after an initial specify binding.
