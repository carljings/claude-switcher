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
        await waitUntil { vm.accountNote == "Account permission not verified" }
        assert(vm.phase == .ready && vm.current == "A" && vm.selectedAccount == "A")
        assert(vm.hasA && !vm.hasB)
        passed.append("initial selection follows current profile")
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
        print("ACCOUNT_SELECTION_TESTS: \(passed.count) scenarios passed; isolated fake core, no real accounts")
        for name in passed { print("PASS: " + name) }
    }
}
