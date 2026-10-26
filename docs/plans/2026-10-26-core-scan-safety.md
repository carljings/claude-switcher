# Core scan failure handling implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Never report local readiness after a failed, incomplete or ambiguous core scan or account-status command.

**Architecture:** Adapt only the process execution and scan validation fixes from upstream `235d900` and `5491434`. Keep the String callback API, A/B selection, strict checks and structured maintenance failures; retain the original scan error when the following status command also fails.

**Tech Stack:** SwiftUI, Foundation Process, isolated Swift model fixtures and Python unittest.

---

### Task 1: Reproduce false readiness

**Files:** `scripts/test-account-ui.py`, `tests/AccountSelectionTests.swift`.

Add fake-core modes for complete output followed by exit 7, an explicit failure line, duplicate check keys and invalid status responses. Run `python3 scripts/test-account-ui.py`; the existing model must fail the new readiness assertion before implementation. All fixtures use a temporary HOME and contain no real account or browser data.

### Task 2: Adapt bounded execution fixes

**File:** `app/main.swift`.

- Require successful exit for `checkdetail` and `status`; retain failure output for diagnostics.
- Accept exactly one result per known check key. Require unique, valid `current`, `hasA` and `hasB` status fields; unknown future key/value fields may remain compatible.
- Missing or unreadable core and output-file failures must return a clear failure without running a command.
- Use the upstream locked deadline after process launch and clean temporary output on every return. Remove the shared debug log rather than logging maintenance arguments.
- Preserve valid nonzero `ok:false` maintenance JSON and its recovery information.

Run the real-model fixtures, including immediate exit, timeout, missing core and existing maintenance scenarios. The selected account must remain unchanged and failed scans must disable confirmation.

### Task 3: Verify and publish the reviewed source

Run isolated Python regressions, strict native Swift compilation, repository checksums and the model fixtures. Review the complete diff for secrets and unrelated edits. Record each new upstream commit as adapted, already covered or deferred, then push only this bounded fix to the user's custom branch.

Prepare and verify a signed universal candidate package without replacing the installed application, user modules, root modules or any network configuration. Local installation requires a new explicit authorization under the current AGENTS instructions. Do not run real maintenance, switch accounts, restore backups or update another device/migration bundle.
