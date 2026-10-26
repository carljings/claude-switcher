import Foundation
import SwiftUI

@main struct AccountSelectionTests {
    @MainActor static func waitUntil(_ condition: () -> Bool) async {
        for _ in 0..<100 {
            if condition() { return }
            try? await Task.sleep(nanoseconds: 50_000_000)
        }
        fatalError("Fixture operation timed out")
    }

    @MainActor static func main() async throws {
        let root = CommandLine.arguments[1]
        let vm = VM(core: root + "/core.sh")
        func write(_ name: String, _ value: String) throws {
            try value.write(toFile: root + "/" + name, atomically: true, encoding: .utf8)
        }
        func commands() throws -> [String] {
            try String(contentsOfFile: root + "/commands").split(separator: "\n").map(String.init)
        }
        var passed: [String] = []
        let suiteName = "switcher-email-fixture-" + UUID().uuidString
        let preferences = UserDefaults(suiteName: suiteName)!
        defer { preferences.removePersistentDomain(forName: suiteName) }
        try AccountEmailLabels.save(a: " a.user@example.com ", b: "", store: preferences)
        assert(preferences.string(forKey: AccountEmailLabels.keyA) == "a.user@example.com")
        assert(preferences.string(forKey: AccountEmailLabels.keyB) == "")
        passed.append("email labels trim and persist only in isolated preferences")
        do {
            try AccountEmailLabels.save(a: "new@example.com", b: "invalid-address", store: preferences)
            fatalError("Invalid email accepted")
        } catch {
            assert(preferences.string(forKey: AccountEmailLabels.keyA) == "a.user@example.com")
        }
        passed.append("invalid email rejects save without partial changes")
        vm.refresh()
        vm.refresh()
        await waitUntil { !vm.isScanning }
        assert(vm.phase == .ready && vm.current == "A" && vm.selectedAccount == "A")
        assert(vm.hasA && !vm.hasB)
        passed.append("initial selection follows current profile")
        for mode in ["nonzero-complete", "failure-line", "duplicate", "empty-state"] {
            try write("check-mode", mode)
            vm.refresh()
            await waitUntil { !vm.isScanning }
            assert(vm.phase == .failed && !vm.canConfirmOpen,
                   "Complete output must not hide scan failure: " + mode)
            if mode == "empty-state" {
                assert(vm.rows.first { $0.name == "Wi-Fi IPv6" }?.state == .fail)
            } else { assert(!vm.banner.isEmpty) }
            assert(vm.selectedAccount == "A")
            passed.append("scan rejects " + mode + " while preserving selection")
        }
        try write("check-mode", "success")
        for mode in ["nonzero-complete", "empty", "missing-field", "duplicate", "invalid-value"] {
            try write("status-mode", mode)
            vm.refresh()
            await waitUntil { !vm.isScanning }
            assert(vm.phase == .failed && !vm.canConfirmOpen && !vm.banner.isEmpty,
                   "Invalid account status must block readiness: " + mode)
            assert(vm.current == "未知" && vm.selectedAccount == "A")
            passed.append("status rejects " + mode + " without guessing a profile")
        }
        try write("check-mode", "failure-line")
        try write("status-mode", "empty")
        vm.refresh()
        await waitUntil { !vm.isScanning }
        assert(vm.banner.contains("fixture scan failed after output"))
        passed.append("status failure preserves the original scan reason")
        try write("check-mode", "success")
        try write("status-mode", "success")
        vm.refresh()
        await waitUntil { !vm.isScanning }
        assert(vm.phase == .ready && vm.current == "A")
        let absent = VM(core: root + "/missing-core.sh")
        absent.refresh()
        await waitUntil { !absent.isScanning }
        assert(absent.phase == .failed && absent.rows.allSatisfy { $0.state == .fail })
        assert(absent.banner.contains("核心脚本"))
        passed.append("missing core fails clearly without leaving pending rows")
        var callbacks = 0
        var runnerOutput = ""
        vm.run(["runner-fast"], timeout: 0.15, requireSuccess: true) { output in
            callbacks += 1; runnerOutput = output
        }
        await waitUntil { callbacks == 1 }
        assert(runnerOutput == "OK:fixture immediate exit")
        try? await Task.sleep(nanoseconds: 200_000_000)
        assert(callbacks == 1)
        passed.append("an immediate exit completes once without a late timeout")
        vm.run(["runner-timeout"], timeout: 0.1, requireSuccess: true) { output in
            callbacks += 1; runnerOutput = output
        }
        await waitUntil { callbacks == 2 }
        assert(runnerOutput.hasPrefix("FAIL:") && runnerOutput.contains("超时"))
        passed.append("deadline reports timeout instead of empty success")
        let beforeSelection = try commands()
        vm.selectAccount("B")
        vm.selectAccount("A")
        vm.selectAccount("B")
        vm.selectAccount("invalid")
        assert(vm.selectedAccount == "B" && vm.current == "A" && vm.canConfirmOpen)
        assert(vm.accountActionHint.contains("首次使用"))
        let afterSelection = try commands()
        assert(afterSelection == beforeSelection)
        passed.append("selection changes no backend or current profile")

        vm.phase = .failed
        vm.confirmOpen()
        vm.phase = .ready
        vm.isScanning = true
        vm.confirmOpen()
        vm.isScanning = false
        let afterBlockedConfirm = try commands()
        assert(afterBlockedConfirm == beforeSelection)
        passed.append("failed checks and busy scan block confirmation")
        vm.isEditingEmails = true
        vm.selectAccount("A")
        vm.confirmOpen()
        vm.refresh()
        vm.openProtectedBrowser()
        vm.openProtectedBrowser(target: .ippure)
        assert(vm.selectedAccount == "B" && !vm.canConfirmOpen && !vm.canRescan)
        let afterEmailEdit = try commands()
        assert(afterEmailEdit == beforeSelection)
        vm.isEditingEmails = false
        passed.append("email editing cannot launch or change a profile")

        for mode in ["failure", "empty", "nonzero-success"] {
            try write("mode", mode)
            vm.confirmOpen()
            vm.confirmOpen()
            let selected = vm.selectedAccount
            vm.selectAccount("A")
            vm.refresh()
            vm.fixAll()
            vm.inspectDevice()
            vm.openProtectedBrowser()
            assert(vm.phase == .switching && vm.selectedAccount == selected && !vm.canRescan)
            await waitUntil { vm.phase == .openFailed }
            assert(vm.selectedAccount == "B" && vm.current == "A" && !vm.banner.isEmpty)
            assert(!vm.banner.hasPrefix("OK:"))
            vm.refresh()
            await waitUntil { !vm.isScanning }
            assert(vm.phase == .ready && vm.selectedAccount == "B")
        }
        let failures = try commands()
        assert(failures.filter { $0 == "switch B" }.count == 3)
        assert(!failures.contains(where: { ["fix", "fingerprint", "protected-browser"].contains($0) }))
        passed.append("single request and operation exclusion")
        passed.append("empty output and nonzero success are failures")
        passed.append("failed open preserves selection through rescan")

        try write("mode", "partial-failure")
        vm.confirmOpen()
        await waitUntil { vm.phase == .openFailed }
        assert(vm.current == "B" && vm.selectedAccount == "B")
        passed.append("partial failure reads actual profile")
        vm.fixAll()
        assert(vm.phase == .fixing && !vm.canRescan)
        await waitUntil { vm.phase == .ready && !vm.isScanning }
        assert(vm.selectedAccount == "B")
        passed.append("repair completion can rescan while preserving selection")

        let targets: [ExternalCheckTarget?] = [nil, .ippure, .ping0]
        for target in targets {
            let before = try commands()
            let selected = vm.selectedAccount
            let current = vm.current
            vm.openProtectedBrowser(target: target)
            assert(vm.isOpeningProtected && !vm.canRescan && !vm.canConfirmOpen)
            assert(vm.protectedMessage.contains("预检"))
            vm.openProtectedBrowser(target: .ping0)
            vm.openProtectedBrowser()
            vm.refresh()
            vm.fixAll()
            vm.inspectDevice()
            vm.confirmOpen()
            vm.selectAccount("A")
            assert(vm.selectedAccount == selected && vm.current == current && vm.phase == .ready)
            await waitUntil { !vm.isOpeningProtected }
            let after = try commands()
            let expected = "protected-browser" + (target.map { " " + $0.rawValue } ?? "")
            assert(Array(after.dropFirst(before.count)) == [expected])
            assert(vm.protectedMessage == "OK:fixture protected " + (target?.rawValue ?? "claude"))
            passed.append("protected browser dispatches " + (target?.rawValue ?? "default") + " without profile operations")
        }
        passed.append("protected browser preflight blocks reentry and all competing operations")
        for mode in ["failure", "nonzero-success", "empty"] {
            try write("protected-mode", mode)
            let before = try commands()
            vm.openProtectedBrowser(target: .ippure)
            await waitUntil { !vm.isOpeningProtected }
            let after = try commands()
            assert(Array(after.dropFirst(before.count)) == ["protected-browser ippure"])
            assert(!vm.protectedMessage.isEmpty && !vm.protectedMessage.hasPrefix("OK:"))
            if mode != "empty" { assert(vm.protectedMessage.hasPrefix("FAIL:")) }
            assert(vm.phase == .ready && vm.canRescan && vm.current == "B" && vm.selectedAccount == "B")
            passed.append("protected browser " + mode + " reports failure without fallback or switch")
        }

        let maintenanceStart = try commands().count
        let accountBeforeMaintenance = vm.selectedAccount
        vm.openMaintenance()
        vm.openMaintenance()
        vm.refresh()
        vm.fixAll()
        vm.inspectDevice()
        vm.openProtectedBrowser(target: .ippure)
        vm.confirmOpen()
        vm.selectAccount("A")
        assert(vm.isMaintenanceOpen && !vm.canRescan && !vm.canConfirmOpen)
        assert(vm.selectedAccount == accountBeforeMaintenance && vm.current == "B")
        let afterMaintenanceOpen = try commands()
        assert(afterMaintenanceOpen.count == maintenanceStart)
        passed.append("opening maintenance runs nothing and blocks account and network operations")

        vm.previewMaintenance()
        vm.previewMaintenance()
        vm.applyMaintenance()
        await waitUntil { !vm.maintenanceBusy }
        assert(vm.maintenancePreview?.mode == .cache && vm.maintenancePreview?.operation == .clean)
        assert(!vm.maintenanceAcknowledged && !vm.canApplyMaintenance)
        vm.applyMaintenance()
        let afterPreview = try commands()
        assert(Array(afterPreview.dropFirst(maintenanceStart)) == ["maintenance-preview cache"])
        vm.maintenanceAcknowledged = true
        assert(vm.canApplyMaintenance)
        let afterAcknowledgement = try commands()
        assert(afterAcknowledgement == afterPreview)
        passed.append("preview and acknowledgement never apply without explicit confirmation")
        vm.selectMaintenanceMode(.browserReset)
        assert(vm.maintenancePreview == nil && !vm.maintenanceAcknowledged && !vm.canApplyMaintenance)
        vm.applyMaintenance()
        let afterModeChange = try commands()
        assert(afterModeChange == afterPreview)
        passed.append("mode changes invalidate the preview token and acknowledgement")

        vm.selectMaintenanceMode(.cache)
        vm.previewMaintenance()
        vm.selectMaintenanceMode(.nativeIDs)
        await waitUntil { !vm.maintenanceBusy }
        assert(vm.maintenanceMode == .nativeIDs && vm.maintenancePreview == nil && !vm.maintenanceAcknowledged)
        passed.append("a delayed preview cannot revive a token after the mode changes")
        for mode in MaintenanceMode.allCases {
            vm.selectMaintenanceMode(mode)
            vm.previewMaintenance()
            await waitUntil { !vm.maintenanceBusy }
            assert(vm.maintenancePreview?.mode == mode && !vm.maintenanceAcknowledged)
            let observed = try commands()
            assert(observed.last == "maintenance-preview " + mode.rawValue)
            passed.append("maintenance preview dispatches fixed scope " + mode.rawValue)
        }
        let beforeApply = try commands()
        vm.maintenanceAcknowledged = true
        vm.applyMaintenance()
        vm.applyMaintenance()
        vm.closeMaintenance()
        vm.selectMaintenanceMode(.cache)
        vm.previewMaintenance()
        vm.loadMaintenanceBackups()
        vm.refresh()
        vm.fixAll()
        vm.inspectDevice()
        vm.openProtectedBrowser()
        vm.confirmOpen()
        vm.selectAccount("A")
        assert(vm.isMaintenanceOpen && vm.maintenanceBusy && !vm.canRescan && vm.maintenanceMode == .nativeIDs)
        await waitUntil { !vm.maintenanceBusy }
        let afterApply = try commands()
        assert(Array(afterApply.dropFirst(beforeApply.count)) == ["maintenance-apply " + String(repeating: "d", count: 32)])
        assert(vm.maintenanceSucceeded && !vm.maintenanceIsError && vm.maintenanceLastBackupID == "fixture-result")
        assert(vm.maintenancePreview == nil && !vm.maintenanceAcknowledged && vm.current == "B" && vm.selectedAccount == accountBeforeMaintenance)
        passed.append("confirmed apply sends the exact token once and excludes all competing operations")

        vm.selectMaintenanceMode(.cache)
        for behavior in ["empty", "bad-json", "plain", "failure", "fail-text", "schema2", "missing-field", "wrong-mode", "unknown-mode", "wrong-operation", "bad-token", "expired", "nonzero-success"] {
            try write("maintenance-mode", behavior)
            vm.previewMaintenance()
            await waitUntil { !vm.maintenanceBusy }
            assert(vm.maintenanceIsError && !vm.maintenanceSucceeded && vm.maintenancePreview == nil && !vm.maintenanceAcknowledged)
            assert(vm.maintenanceMode == .cache && !vm.maintenanceMessage.isEmpty)
            let before = try commands()
            vm.maintenanceAcknowledged = true
            vm.applyMaintenance()
            let after = try commands()
            assert(after == before)
            passed.append("maintenance rejects " + behavior + " without losing the selected scope or applying")
        }
        try write("maintenance-mode", "no-items")
        vm.previewMaintenance()
        await waitUntil { !vm.maintenanceBusy }
        assert(vm.maintenancePreview?.canApply == false && !vm.maintenanceIsError && !vm.maintenanceSucceeded)
        vm.maintenanceAcknowledged = true
        assert(!vm.canApplyMaintenance)
        let beforeNoItems = try commands()
        vm.applyMaintenance()
        let afterNoItems = try commands()
        assert(afterNoItems == beforeNoItems)
        passed.append("an empty non-applicable plan is informational and cannot be applied")

        try write("maintenance-mode", "short-expiry")
        vm.previewMaintenance()
        await waitUntil { !vm.maintenanceBusy }
        vm.maintenanceAcknowledged = true
        assert(vm.canApplyMaintenance)
        try? await Task.sleep(nanoseconds: 450_000_000)
        let beforeExpiry = try commands()
        vm.applyMaintenance()
        let afterExpiry = try commands()
        assert(afterExpiry == beforeExpiry && vm.maintenancePreview == nil && !vm.maintenanceAcknowledged && vm.maintenanceIsError)
        passed.append("expiry at confirmation invalidates the token without an apply request")

        for behavior in ["bad-json", "nonzero-success", "recovery-error"] {
            try write("maintenance-mode", "success")
            vm.previewMaintenance()
            await waitUntil { !vm.maintenanceBusy }
            try write("maintenance-mode", behavior)
            vm.maintenanceAcknowledged = true
            vm.applyMaintenance()
            await waitUntil { !vm.maintenanceBusy }
            assert(vm.maintenanceIsError && !vm.maintenanceSucceeded && vm.maintenancePreview == nil && !vm.maintenanceAcknowledged)
            assert(vm.maintenanceRecoveryRequired == (behavior == "recovery-error"))
            passed.append("apply " + behavior + " cannot report success and preserves recovery guidance")
        }
        try write("maintenance-mode", "success")
        vm.loadMaintenanceBackups()
        await waitUntil { !vm.maintenanceBusy }
        assert(vm.maintenanceBackupsLoaded && vm.maintenanceBackups.count == 2 && vm.maintenancePreview == nil)
        vm.maintenanceAcknowledged = true
        let beforeBackupSelection = try commands()
        vm.selectMaintenanceBackup("fixture-completed")
        assert(!vm.maintenanceAcknowledged && !vm.canApplyMaintenance)
        let afterBackupSelection = try commands()
        assert(afterBackupSelection == beforeBackupSelection)
        vm.previewMaintenanceRestore()
        await waitUntil { !vm.maintenanceBusy }
        assert(vm.maintenancePreview?.operation == .restore && vm.maintenancePreview?.mode == .cache)
        vm.applyMaintenance()
        let afterRestorePreview = try commands()
        assert(Array(afterRestorePreview.dropFirst(beforeBackupSelection.count)) == ["maintenance-restore-preview fixture-completed"])
        vm.maintenanceAcknowledged = true
        vm.applyMaintenance()
        await waitUntil { !vm.maintenanceBusy }
        let afterRestore = try commands()
        assert(afterRestore.last == "maintenance-apply " + String(repeating: "e", count: 32) && vm.maintenanceSucceeded)
        passed.append("backup selection only previews and restoration requires its own acknowledgement and exact token")

        vm.loadMaintenanceBackups()
        await waitUntil { !vm.maintenanceBusy }
        vm.selectMaintenanceBackup("fixture-recovery")
        vm.previewMaintenanceRestore()
        await waitUntil { !vm.maintenanceBusy }
        assert(vm.maintenancePreview?.operation == .recover && vm.maintenancePreview?.mode == .browserReset && !vm.maintenanceAcknowledged)
        let recoveryPreview = try commands()
        assert(recoveryPreview.last == "maintenance-recover-preview fixture-recovery")
        vm.maintenanceAcknowledged = true
        vm.applyMaintenance()
        await waitUntil { !vm.maintenanceBusy }
        let afterRecovery = try commands()
        assert(afterRecovery.last == "maintenance-apply " + String(repeating: "f", count: 32) && vm.maintenanceSucceeded)
        passed.append("interrupted backups use a separate recover preview and confirmation")
        vm.closeMaintenance()
        assert(!vm.isMaintenanceOpen && vm.canRescan && vm.maintenancePreview == nil && !vm.maintenanceAcknowledged)
        let maintenanceCommands = try commands()
        assert(maintenanceCommands.dropFirst(maintenanceStart).allSatisfy { $0.hasPrefix("maintenance-") })
        assert(vm.current == "B" && vm.selectedAccount == accountBeforeMaintenance)
        passed.append("maintenance and recovery never invoke account operations and closing releases exclusion")

        try write("mode", "same-current")
        vm.confirmOpen()
        await waitUntil { vm.phase == .done }
        assert(vm.banner == "已请求打开账号 B" && vm.current == "B")
        passed.append("current profile can still be opened")
        vm.phase = .ready
        vm.selectAccount("A")
        try write("mode", "note-success")
        vm.confirmOpen()
        vm.confirmOpen()
        await waitUntil { vm.phase == .done }
        assert(vm.current == "A" && vm.banner == "已请求打开账号 A")
        let finalCommands = try commands()
        assert(finalCommands.filter { $0 == "switch A" }.count == 1)
        passed.append("initialization note does not hide successful open")
        assert(!finalCommands.contains("account-note"))
        passed.append("refresh never reads removed account state notes")
        print("ACCOUNT_SELECTION_TESTS: \(passed.count) scenarios passed; isolated fake core, no real accounts")
        for name in passed { print("PASS: " + name) }
    }
}
