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
