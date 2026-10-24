import SwiftUI
import AppKit

// MARK: - 模型

enum RowState { case pending, ok, info, warn, fail }

struct CheckRow: Identifiable {
    let id = UUID()
    let name: String
    let icon: String
    var state: RowState = .pending
    var detail: String = ""
}

enum Phase { case checking, ready, failed, openFailed, switching, done, fixing }

enum AppTheme: String, CaseIterable {
    case black, white
    static let storageKey = "appearanceTheme"
    var title: String { self == .black ? "黑色" : "白色" }
    var colorScheme: ColorScheme { self == .black ? .dark : .light }
    private func color(_ dark: UInt32, _ light: UInt32) -> Color {
        let value = self == .black ? dark : light
        return Color(red: Double((value >> 16) & 255) / 255,
                     green: Double((value >> 8) & 255) / 255, blue: Double(value & 255) / 255)
    }
    var background: Color { color(0x111113, 0xF7F7F9) }
    var surface: Color { color(0x1B1B1F, 0xFFFFFF) }
    var text: Color { color(0xF5F5F7, 0x202024) }
    var secondary: Color { color(0xB8B8C2, 0x62626C) }
    var border: Color { color(0x39393F, 0xD3D3DB) }
    var button: Color { color(0x2C2C32, 0xEEEEF3) }
    var selected: Color { color(0x30294F, 0xEDEAFF) }
    var accent: Color { color(0xB9A9FF, 0x4F38AE) }
    var success: Color { color(0x4ADE80, 0x16713D) }
    var warning: Color { color(0xFACC15, 0x8A5200) }
    var danger: Color { color(0xFF827A, 0xB42318) }
}

private struct AppThemeKey: EnvironmentKey { static let defaultValue = AppTheme.black }
extension EnvironmentValues {
    var appTheme: AppTheme {
        get { self[AppThemeKey.self] }
        set { self[AppThemeKey.self] = newValue }
    }
}

enum AccountEmailLabels {
    static let keyA = "accountEmailA"
    static let keyB = "accountEmailB"
    static func save(a: String, b: String, store: UserDefaults = .standard) throws {
        let values = [a, b].map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        for (index, email) in values.enumerated() where !email.isEmpty {
            if email.count > 254 || email.range(of: #"^[^\s@]+@[^\s@]+\.[^\s@]+$"#, options: .regularExpression) == nil {
                throw NSError(domain: "AccountEmailLabels", code: 1, userInfo: [NSLocalizedDescriptionKey: "账号 \(index == 0 ? "A" : "B") 的邮箱格式不正确。"])
            }
        }
        store.set(values[0], forKey: keyA)
        store.set(values[1], forKey: keyB)
    }
}

final class VM: ObservableObject {
    @Published var rows: [CheckRow] = [
        CheckRow(name: "代理内核", icon: "cpu"),
        CheckRow(name: "TUN 网卡", icon: "cable.connector"),
        CheckRow(name: "出口 IP", icon: "globe.americas"),
        CheckRow(name: "IP 与上次一致", icon: "checkmark.seal"),
        CheckRow(name: "时区（严格）", icon: "clock"),
        CheckRow(name: "地区格式（严格）", icon: "flag"),
        CheckRow(name: "Wi-Fi IPv6", icon: "6.circle"),
        CheckRow(name: "DNS 映射", icon: "magnifyingglass"),
        CheckRow(name: "WebRTC", icon: "eye.slash"),
        CheckRow(name: "桌面进程监测", icon: "hand.raised"),
        CheckRow(name: "探测路由", icon: "list.number"),
        CheckRow(name: "客户端语言", icon: "abc"),
        CheckRow(name: "ASN 属性", icon: "building.columns"),
        CheckRow(name: "服务响应", icon: "antenna.radiowaves.left.and.right"),
    ]
    @Published var phase: Phase = .checking
    @Published var current = "?"
    @Published private(set) var selectedAccount = ""
    @Published var hasA = false
    @Published var hasB = false
    @Published var banner = ""
    @Published var note = ""
    @Published var isScanning = false
    @Published var lastScanAt: Date?
    @Published var fingerprint = ""
    @Published var isFingerprinting = false
    @Published var accountNote = "账号权限未验证；网络检查不代表登录或模型可用。"
    @Published var protectedMessage = ""
    @Published var isOpeningProtected = false
    @Published var isEditingEmails = false

    let core: String
    init(core: String = NSHomeDirectory() + "/.local/bin/claude-switch.sh") { self.core = core }
    var canRescan: Bool { !isScanning && !isFingerprinting && !isOpeningProtected && !isEditingEmails && phase != .switching && phase != .fixing }
    var canConfirmOpen: Bool {
        phase == .ready && canRescan && ["A", "B"].contains(selectedAccount)
            && rows.allSatisfy { $0.state != .pending && $0.state != .fail }
    }
    var accountActionHint: String {
        guard ["A", "B"].contains(selectedAccount) else { return "选择一个账号后，再确认打开。" }
        if selectedAccount == current { return "确认后将复检环境，并打开当前账号 \(selectedAccount)。" }
        return "确认后将退出 Claude，切换到账号 \(selectedAccount) 并打开。"
            + ((selectedAccount == "A" ? !hasA : !hasB) ? "首次使用需在 Claude 中登录。" : "")
    }

    func selectAccount(_ target: String) {
        guard phase == .ready && canRescan && ["A", "B"].contains(target) else { return }
        selectedAccount = target
    }

    private func applyAccountStatus(_ output: String) {
        let fields = output.split(whereSeparator: \.isWhitespace).map(String.init)
        current = fields.contains("current=B") ? "B" : (fields.contains("current=A") ? "A" : "未初始化")
        hasA = fields.contains("hasA=1")
        hasB = fields.contains("hasB=1")
        if selectedAccount.isEmpty { selectedAccount = ["A", "B"].contains(current) ? current : "A" }
    }

    func openProtectedBrowser() {
        guard canRescan else { return }
        isOpeningProtected = true
        protectedMessage = "正在核对固定出口…"
        run(["protected-browser"], timeout: 35) { output in
            self.protectedMessage = output.isEmpty ? "未取得启动结果，请检查专用入口。" : output
            self.isOpeningProtected = false
        }
    }

    func inspectDevice() {
        guard canRescan else { return }
        isFingerprinting = true
        fingerprint = "正在读取设备信息…"
        run(["fingerprint"], timeout: 75) { output in
            self.fingerprint = output.isEmpty ? "未取得设备信息，请重试。" : output
            self.isFingerprinting = false
        }
    }

    func run(_ args: [String], timeout: TimeInterval = 45, requireSuccess: Bool = false, done: @escaping (String) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let started = Date()
            let tmp = "/tmp/switcher-out-\(UUID().uuidString).txt"
            FileManager.default.createFile(atPath: tmp, contents: nil)
            let p = Process()
            p.launchPath = "/bin/bash"
            p.arguments = [self.core] + args
            if let fh = try? FileHandle(forWritingTo: URL(fileURLWithPath: tmp)) {
                p.standardOutput = fh
                p.standardError = fh
            }
            var timedOut = false
            let watchdog = DispatchWorkItem {
                if p.isRunning { timedOut = true; p.terminate() }
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: watchdog)
            do { try p.run() } catch {
                DispatchQueue.main.async { done("FAIL:无法启动脚本 \(error.localizedDescription)") }
                return
            }
            p.waitUntilExit()
            watchdog.cancel()
            if let fh = p.standardOutput as? FileHandle { try? fh.close() }
            let data = (try? Data(contentsOf: URL(fileURLWithPath: tmp))) ?? Data()
            let out = String(decoding: data, as: UTF8.self)  // 容错解码:坏字节替换而非整体失败
            try? FileManager.default.removeItem(atPath: tmp)
            let dbg = "[\(Date())] args=\(args) timedOut=\(timedOut) exit=\(p.terminationStatus) 耗时\(String(format: "%.1f", Date().timeIntervalSince(started)))s stdout=\(out.count)字符\n"
            if let h = try? FileHandle(forWritingTo: URL(fileURLWithPath: "/tmp/switcher-debug.log")) {
                h.seekToEndOfFile(); h.write(dbg.data(using: .utf8)!); h.closeFile()
            } else { try? dbg.write(toFile: "/tmp/switcher-debug.log", atomically: true, encoding: .utf8) }
            if timedOut {
                DispatchQueue.main.async { done("FAIL:操作超时，请重试") }
                return
            }
            if requireSuccess && p.terminationStatus != 0 {
                let detail = out.trimmingCharacters(in: .whitespacesAndNewlines)
                let failure = detail.split(separator: "\n").map(String.init).first { $0.hasPrefix("FAIL:") }
                let message = failure ?? "FAIL:操作未完成（退出码\(p.terminationStatus)），请重新扫描后重试。"
                DispatchQueue.main.async { done(message) }
                return
            }
            DispatchQueue.main.async { done(out.trimmingCharacters(in: .whitespacesAndNewlines)) }
        }
    }

    func refresh() {
        guard canRescan else { return }
        isScanning = true
        phase = .checking
        banner = ""
        note = ""
        for i in rows.indices { rows[i].state = .pending; rows[i].detail = "" }
        run(["checkdetail"]) { out in
            // 每次扫描只接受本次输出,不复用磁盘上的旧结果。
            var allOk = true
            var matchedKeys = Set<String>()
            let keyMap: [String: String] = [
                "代理内核": "代理内核", "TUN网卡": "TUN 网卡", "出口IP": "出口 IP",
                "IP一致": "IP 与上次一致", "时区": "时区（严格）", "地区": "地区格式（严格）",
                "IPv6": "Wi-Fi IPv6", "DNS": "DNS 映射", "WebRTC": "WebRTC",
                "保镖": "桌面进程监测", "规则置顶": "探测路由",
                "客户端语言": "客户端语言", "ASN属性": "ASN 属性", "生态可达性": "服务响应",
            ]
            for line in out.split(separator: "\n") {
                let parts = line.split(separator: "=", maxSplits: 1).map(String.init)
                guard parts.count == 2 else { continue }
                let rhs = parts[1]
                let status = rhs.split(separator: ":", maxSplits: 1).map(String.init)
                guard let code = status.first else { continue }
                let detail = status.count > 1 ? status[1] : ""
                guard let rowName = keyMap[parts[0]], let idx = self.rows.firstIndex(where: { $0.name == rowName }) else { continue }
                matchedKeys.insert(parts[0])
                switch code {
                case "ok": self.rows[idx].state = .ok
                case "info": self.rows[idx].state = .info
                case "warn": self.rows[idx].state = .warn
                default: self.rows[idx].state = .fail; allOk = false
                }
                self.rows[idx].detail = detail
            }
            self.run(["status"]) { st in
                self.applyAccountStatus(st)
                self.run(["account-note"], timeout: 10) { observation in
                    self.accountNote = observation.isEmpty ? "账号权限未验证；网络检查不代表登录或模型可用。" : observation
                }
                self.isScanning = false
                self.lastScanAt = Date()
                if matchedKeys.count < self.rows.count {
                    for index in self.rows.indices where self.rows[index].state == .pending {
                        self.rows[index].state = .fail
                        self.rows[index].detail = "本次未取得结果,请重新扫描"
                    }
                    self.banner = "本次扫描输出不完整(\(matchedKeys.count)/\(self.rows.count))，请重新扫描"
                    self.phase = .failed
                } else {
                    self.phase = allOk ? .ready : .failed
                }
            }
        }
    }

    func fixAll() {
        guard canRescan else { return }
        phase = .fixing
        banner = "正在修复…（若弹出密码框请输入开机密码）"
        run(["fix"], timeout: 180) { out in
            let steps = out.split(separator: "\n").map(String.init).filter { $0.hasPrefix("FIX:") }.map { String($0.dropFirst(4)) }
            self.banner = steps.last ?? ""
            self.phase = .failed
            self.refresh()
        }
    }

    func confirmOpen() {
        guard canConfirmOpen else { return }
        let target = selectedAccount
        phase = .switching
        banner = "正在复检并打开账号 \(target)…"
        run(["switch", target], timeout: 180, requireSuccess: true) { out in
            let lines = out.split(separator: "\n").map(String.init)
            let success = lines.last { $0.hasPrefix("OK:已切换到账号\(target) (") || $0 == "INFO:当前已是账号\(target)" }
            let failure = lines.first { $0.hasPrefix("FAIL:") }
            if failure != nil || success == nil {
                self.banner = failure.map { String($0.dropFirst(5)) } ?? "未取得打开成功确认，请重新扫描后重试。"
                self.run(["status"]) { status in
                    self.applyAccountStatus(status)
                    self.phase = .openFailed
                }
                return
            }
            var extra = ""
            if target == "B" && !self.hasB { extra = "B 号首次使用：请在打开的 Claude 里登录 B 账号，登录一次即可。" }
            if success?.hasPrefix("INFO:") == true { extra = "" }
            self.current = target
            self.phase = .done
            self.banner = "已请求打开账号 \(target)"
            self.note = extra
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.2) {
                if self.phase == .done { NSApplication.shared.terminate(nil) }
            }
        }
    }
}

// MARK: - 视图

struct ContentView: View {
    @StateObject private var vm = VM()
    @State private var showNotice = false
    @State private var selectedCheck: CheckRow?
    @State private var showFingerprint = false
    @State private var showAccountNote = false
    @State private var editedEmailA = ""
    @State private var editedEmailB = ""
    @State private var emailError = ""
    @AppStorage(AppTheme.storageKey) private var storedTheme = AppTheme.black.rawValue
    @AppStorage(AccountEmailLabels.keyA) private var emailA = ""
    @AppStorage(AccountEmailLabels.keyB) private var emailB = ""
    private var theme: AppTheme { AppTheme(rawValue: storedTheme) ?? .black }

    var body: some View {
        ZStack {
            theme.background.ignoresSafeArea()
            VStack(spacing: 16) {
                header
                scanControls
                checksCard
                if vm.phase == .ready || vm.phase == .switching || vm.phase == .done {
                    accountCard
                } else if vm.phase == .failed || vm.phase == .openFailed || vm.phase == .fixing {
                    retryCard
                }
                Spacer(minLength: 0)
                footer
            }
            .padding(20)
        }
        .frame(width: 440, height: 860)
        .environment(\.appTheme, theme)
        .preferredColorScheme(theme.colorScheme)
        .tint(theme.accent)
        .onAppear { vm.refresh() }
        .sheet(isPresented: $vm.isEditingEmails) { emailEditor }
    }

    private func accountEmail(_ account: String) -> String {
        switch account { case "A": return emailA; case "B": return emailB; default: return "" }
    }

    private var editEmailsButton: some View {
        Button {
            guard vm.canRescan else { return }
            editedEmailA = emailA; editedEmailB = emailB; emailError = ""
            vm.isEditingEmails = true
        } label: {
            Label("编辑邮箱", systemImage: "pencil")
                .font(.caption).foregroundColor(theme.text)
                .padding(.horizontal, 8).padding(.vertical, 5)
                .background(theme.button).clipShape(Capsule())
        }
        .buttonStyle(.plain).disabled(!vm.canRescan)
        .help("编辑A/B的本机邮箱标签，不登录或切换账号")
    }

    private var emailEditor: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("账号邮箱").font(.headline)
            Text("邮箱用于区分本机档案，不验证当前登录或账号权限。重新登录其他账号后，请核对标签。")
                .font(.caption).foregroundColor(theme.secondary)
            VStack(alignment: .leading, spacing: 6) {
                Text("账号 A").font(.callout.bold())
                TextField("未填写", text: $editedEmailA)
                    .textFieldStyle(.plain).foregroundColor(theme.text).tint(theme.accent)
                    .padding(8).background(theme.button)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(theme.border))
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("账号 B").font(.callout.bold())
                TextField("未填写", text: $editedEmailB)
                    .textFieldStyle(.plain).foregroundColor(theme.text).tint(theme.accent)
                    .padding(8).background(theme.button)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(theme.border))
            }
            if !emailError.isEmpty { Text(emailError).font(.caption).foregroundColor(theme.danger) }
            Text("仅保存在这台Mac的应用偏好中；不会随源码或迁移包导出。")
                .font(.caption2).foregroundColor(theme.secondary)
            HStack {
                Spacer()
                Button("取消") { vm.isEditingEmails = false }
                    .keyboardShortcut(.cancelAction)
                Button("保存") {
                    do {
                        try AccountEmailLabels.save(a: editedEmailA, b: editedEmailB)
                        vm.isEditingEmails = false
                    } catch { emailError = error.localizedDescription }
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20).frame(width: 380)
        .foregroundColor(theme.text).background(theme.surface)
        .preferredColorScheme(theme.colorScheme)
    }

    var header: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 12)
                    .fill(LinearGradient(colors: [Color.indigo, Color.purple], startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 44, height: 44)
                Image(systemName: "shield.lefthalf.filled").font(.title2).foregroundColor(.white)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text("Claude 账号切换器").font(.title3.bold()).foregroundColor(theme.text)
                Text("环境检查 · 选择账号 · 确认打开").font(.caption).foregroundColor(theme.secondary)
            }
            Spacer()
            Button {
                storedTheme = (theme == .black ? AppTheme.white : AppTheme.black).rawValue
            } label: {
                Image(systemName: theme == .black ? "moon.fill" : "sun.max.fill")
                    .font(.callout).foregroundColor(theme.secondary)
                    .frame(width: 24, height: 24).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(theme == .black ? "切换为白色皮肤" : "切换为黑色皮肤")
            .accessibilityLabel(theme == .black ? "切换为白色皮肤" : "切换为黑色皮肤")
            .accessibilityValue(theme.title)
            Button { showNotice = true } label: {
                Image(systemName: "info.circle").font(.title3).foregroundColor(theme.secondary)
            }
            .buttonStyle(.plain)
            .help("使用建议与检查边界")
            statusPill
        }
        .sheet(isPresented: $showNotice) { NoticeView() }
    }

    var statusPill: some View {
        let (txt, color): (String, Color) = {
            switch vm.phase {
            case .checking: return ("检查中", theme.warning)
            case .ready:
                if vm.rows.contains(where: { $0.state == .warn }) { return ("有提醒", theme.warning) }
                return ("本地通过", theme.success)
            case .failed: return ("检查未过", theme.danger)
            case .openFailed: return ("打开未完成", theme.danger)
            case .switching: return ("打开中", theme.accent)
            case .fixing: return ("修复中", theme.warning)
            case .done: return ("完成", theme.success)
            }
        }()
        return Text(txt)
            .font(.caption.bold())
            .padding(.horizontal, 10).padding(.vertical, 5)
            .background(color.opacity(0.14))
            .foregroundColor(color)
            .clipShape(Capsule())
    }

    var scanControls: some View {
        HStack {
            if vm.isScanning {
                Text("正在读取当前出口和全部检查项…")
                    .font(.caption).foregroundColor(theme.secondary)
            } else if let date = vm.lastScanAt {
                Text("上次扫描 " + date.formatted(date: .omitted, time: .standard))
                    .font(.caption).foregroundColor(theme.secondary)
            }
            Spacer()
            Button {
                vm.inspectDevice()
                showFingerprint = true
            } label: {
                Label("设备信息", systemImage: "waveform.path.ecg")
                    .font(.caption).padding(.horizontal, 8).padding(.vertical, 7)
                    .background(theme.button).clipShape(Capsule())
            }
            .buttonStyle(.plain).disabled(!vm.canRescan)
            .help("按需读取字体、GPU及虚拟化线索，不影响启动")
            Button { vm.refresh() } label: {
                HStack(spacing: 6) {
                    if vm.isScanning { ProgressView().controlSize(.small) }
                    else { Image(systemName: "arrow.clockwise") }
                    Text(vm.isScanning ? "扫描中…" : "重新扫描")
                }
                .font(.callout.bold())
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(theme.button)
                .clipShape(Capsule())
            }
            .buttonStyle(.plain)
            .disabled(!vm.canRescan)
            .keyboardShortcut("r", modifiers: .command)
            .help("重新读取当前网络、出口和全部检查项,不切换账号")
        }
        .foregroundColor(theme.text)
        .sheet(isPresented: $showFingerprint) {
            FingerprintView(text: vm.fingerprint).environment(\.appTheme, theme)
        }
    }

    var checksCard: some View {
        VStack(spacing: 0) {
            ForEach(Array(vm.rows.enumerated()), id: \.element.id) { idx, row in
                Button { selectedCheck = row } label: {
                HStack(spacing: 10) {
                    Image(systemName: row.icon)
                        .frame(width: 20)
                        .foregroundColor(theme.secondary)
                    Text(row.name).font(.callout).foregroundColor(theme.text)
                    Spacer()
                    if !row.detail.isEmpty {
                        Text(row.detail).font(.caption).foregroundColor(theme.secondary).lineLimit(1).help(row.detail)
                    }
                    stateIcon(row.state)
                }
                .padding(.vertical, 7).padding(.horizontal, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("点击查看完整结果和处理建议")
                if idx < vm.rows.count - 1 {
                    Divider().background(theme.border)
                }
            }
        }
        .background(theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(theme.border))
        .popover(item: $selectedCheck) { row in
            CheckDetailView(row: row).environment(\.appTheme, theme)
        }
    }

    func stateIcon(_ s: RowState) -> some View {
        Group {
            switch s {
            case .pending: ProgressView().scaleEffect(0.55).frame(width: 16, height: 16)
            case .ok: Image(systemName: "checkmark.circle.fill").foregroundColor(theme.success).help("本项检查通过；范围见详情")
            case .info: Image(systemName: "info.circle").foregroundColor(theme.secondary).help("说明：确认记录或检测范围，不是告警；未核验部分仍未确认")
            case .warn: Image(systemName: "exclamationmark.triangle.fill").foregroundColor(theme.warning).help("提醒：需要核实，见详情")
            case .fail: Image(systemName: "xmark.octagon.fill").foregroundColor(theme.danger).help("故障：阻止启动，见详情")
            }
        }
        .font(.callout)
    }

    var accountCard: some View {
        VStack(spacing: 12) {
            if vm.phase == .switching {
                HStack(spacing: 8) {
                    ProgressView().scaleEffect(0.7)
                    Text(vm.banner).font(.callout).foregroundColor(theme.secondary)
                }
                .frame(maxWidth: .infinity).padding(.vertical, 10)
            } else if vm.phase == .done {
                VStack(spacing: 4) {
                    Label(vm.banner, systemImage: "checkmark.circle.fill").foregroundColor(theme.success).font(.callout.bold())
                    if !vm.note.isEmpty { Text(vm.note).font(.caption).foregroundColor(theme.warning).multilineTextAlignment(.center) }
                }
                .frame(maxWidth: .infinity).padding(.vertical, 10)
            } else {
                HStack(spacing: 6) {
                    Text("当前档案").font(.caption).foregroundColor(theme.secondary)
                    Text(vm.current).font(.caption.bold())
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(theme.selected).foregroundColor(theme.accent)
                        .clipShape(Capsule())
                    Spacer()
                    editEmailsButton
                    Button { vm.openProtectedBrowser() } label: {
                        Label("专用浏览器", systemImage: "network.badge.shield.half.filled")
                            .foregroundColor(theme.text)
                            .font(.caption).padding(.horizontal, 8).padding(.vertical, 5)
                            .background(theme.button).clipShape(Capsule())
                    }
                    .buttonStyle(.plain).disabled(!vm.canRescan)
                    .help("独立Edge资料目录，固定本机代理；需要官方登录")
                }
                Button { showAccountNote = true } label: {
                    Text(vm.accountNote).font(.caption2)
                        .foregroundColor(vm.accountNote.contains("on hold") ? theme.warning : theme.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading).multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .buttonStyle(.plain)
                .help(vm.accountNote)
                .popover(isPresented: $showAccountNote) {
                    CheckDetailView(row: CheckRow(name: "账号状态备注", icon: "person.crop.circle", state: .info, detail: vm.accountNote)).environment(\.appTheme, theme)
                }
                if !vm.protectedMessage.isEmpty {
                    Text(vm.protectedMessage).font(.caption2).foregroundColor(theme.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                HStack(spacing: 10) {
                    accountButton("A", subtitle: vm.current == "A" ? "当前档案" : (vm.hasA ? "已建档" : "首次使用 · 需登录"))
                    accountButton("B", subtitle: vm.current == "B" ? "当前档案" : (vm.hasB ? "已建档" : "首次使用 · 需登录"))
                }
                Text(vm.accountActionHint).font(.caption).foregroundColor(theme.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true)
                Button { vm.confirmOpen() } label: {
                    Label(vm.selectedAccount.isEmpty ? "请先选择账号" : "确认打开账号 \(vm.selectedAccount)", systemImage: "arrow.up.right.square")
                        .font(.callout.bold()).frame(maxWidth: .infinity)
                        .padding(.vertical, 11)
                        .foregroundColor(vm.canConfirmOpen ? theme.background : theme.secondary)
                        .background(vm.canConfirmOpen ? theme.accent : theme.button)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain).disabled(!vm.canConfirmOpen)
                .keyboardShortcut(.return, modifiers: .command)
                .help("复检通过后切换并请求打开所选账号（⌘↩）")
                .accessibilityLabel("确认打开账号 \(vm.selectedAccount)，\(accountEmail(vm.selectedAccount).isEmpty ? "未填写邮箱" : accountEmail(vm.selectedAccount))")
            }
        }
        .padding(12)
        .background(theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(theme.border))
    }

    func accountButton(_ t: String, subtitle: String) -> some View {
        Button { vm.selectAccount(t) } label: {
            VStack(spacing: 4) {
                HStack(spacing: 6) {
                    Image(systemName: vm.selectedAccount == t ? "checkmark.circle.fill" : "circle")
                        .foregroundColor(vm.selectedAccount == t ? theme.accent : theme.secondary)
                    Text("账号 \(t)").font(.headline).foregroundColor(theme.text)
                }
                Text(accountEmail(t).isEmpty ? "未填写邮箱" : accountEmail(t))
                    .font(.caption).foregroundColor(theme.secondary).lineLimit(1).truncationMode(.middle)
                    .padding(.horizontal, 8)
                    .help(accountEmail(t).isEmpty ? "点击编辑邮箱填写本机标签" : accountEmail(t))
                Text(subtitle).font(.caption2).foregroundColor(theme.secondary)
            }
            .frame(maxWidth: .infinity).padding(.vertical, 10)
            .background(vm.selectedAccount == t ? theme.selected : theme.button)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(vm.selectedAccount == t ? theme.accent : theme.border, lineWidth: 1.2))
        }
        .buttonStyle(.plain)
        .disabled(!vm.canRescan)
        .accessibilityLabel("选择账号 \(t)")
        .accessibilityValue((vm.selectedAccount == t ? "已选择，" : "未选择，") + accountEmail(t) + "，" + subtitle)
        .accessibilityHint("只选择账号；点击下方确认打开才会切换或启动")
    }

    var retryCard: some View {
        VStack(spacing: 10) {
            if vm.phase == .fixing {
                HStack(spacing: 8) {
                    ProgressView().scaleEffect(0.7)
                    Text(vm.banner).font(.callout).foregroundColor(theme.secondary)
                }
            } else {
                if !vm.banner.isEmpty {
                    Text(vm.banner).font(.callout).foregroundColor(theme.danger).multilineTextAlignment(.center)
                }
                if !vm.selectedAccount.isEmpty {
                    Text("待打开账号：\(vm.selectedAccount)（选择已保留）").font(.caption).foregroundColor(theme.text)
                }
                editEmailsButton
                Text(vm.phase == .openFailed ? "重新扫描后再确认打开；若仍失败，请检查 Claude 安装。" : "存在未通过项，可网络修复或手动处理后重新扫描")
                    .font(.caption).foregroundColor(theme.secondary)
                HStack(spacing: 10) {
                    if vm.phase != .openFailed {
                    Button { vm.fixAll() } label: {
                        Label("网络修复", systemImage: "wand.and.stars")
                            .font(.callout.bold())
                            .padding(.horizontal, 18).padding(.vertical, 8)
                            .background(theme.accent)
                            .foregroundColor(theme.background)
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(!vm.canRescan)
                    }
                    Button { vm.refresh() } label: {
                        Label("重新扫描", systemImage: "arrow.clockwise")
                            .font(.callout.bold())
                            .padding(.horizontal, 18).padding(.vertical, 8)
                            .background(vm.phase == .openFailed ? theme.accent : theme.button)
                            .foregroundColor(vm.phase == .openFailed ? theme.background : theme.text)
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(!vm.canRescan)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(12)
        .background(theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(theme.danger.opacity(0.5)))
    }

    var footer: some View {
        HStack {
            Image(systemName: "lock.shield").font(.caption2)
            Text("点击检查项查看全文 · 本地通过不代表账号可用").font(.caption2)

        }
        .foregroundColor(theme.secondary)
    }
}

struct FingerprintView: View {
    let text: String
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("设备信息").font(.headline)
                Spacer()
                Button("关闭") { dismiss() }
            }
            Text("按需设备线索，不是账号风险评分，也不影响启动。")
                .font(.caption).foregroundColor(theme.secondary)
            ScrollView {
                Text(text).font(.callout).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).lineSpacing(4)
            }
        }
        .padding(20).frame(width: 480, height: 360)
        .foregroundColor(theme.text).background(theme.background)
        .preferredColorScheme(theme.colorScheme)
    }
}

struct CheckDetailView: View {
    let row: CheckRow
    @Environment(\.appTheme) private var theme

    private var status: String {
        switch row.state {
        case .pending: return "等待本次扫描"
        case .ok: return "通过 · 以本项检测范围为准"
        case .info: return "说明 · 不是黄色告警，未核验部分仍未确认"
        case .warn: return "提醒 · 需要核实"
        case .fail: return "故障 · 阻止启动"
        }
    }
    private var guidance: String {
        switch row.name {
        case "Wi-Fi IPv6": return "本项核对Wi-Fi接口设置。Clash内核的IPv6状态由探测路由单独严格核验，Wi-Fi关闭不能代表内核也关闭；其他物理接口需分别核对。"
        case "DNS 映射": return "Fake-IP 只证明域名被映射。可在实际使用的浏览器运行 DNS 测试，再结合 Clash 日志核对上游路径；解析器地区不同本身不等于泄漏。"
        case "WebRTC": return "当前策略核验列出的4个STUN域名和UDP 3478/5349/19302拒绝规则。它可能影响使用这些端口的实时通话，未覆盖所有端口；Edge的实际表现仍需在Edge实测。"
        case "桌面进程监测": return "服务启用后约每 10 秒检查一次。Claude 桌面端未运行时待命；运行后重新扫描可查看近期核验。它仅保护桌面主进程，有检测窗口，不是系统防火墙。"
        case "ASN 属性": return "IPPure/Ping0 的截图可以佐证第三方住宅标签，不能单独证明物理住宅接入。无需为了去掉说明而伪造或更改 ASN。"
        case "服务响应", "生态可达性": return "这项只检查Claude网页与API的匿名HTTP响应。只有明确检测到cf-mitigated: challenge的403加匿名API401才显示灰色说明；其他403继续提醒，传输失败仍阻断。浏览器验证需在官方页面完成，HTTP响应不验证账号权限，也不能据此判定封号。"
        default: return ""
        }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(row.name, systemImage: row.icon).font(.headline).foregroundColor(theme.text)
            Text(status).font(.caption).foregroundColor(theme.secondary)
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(row.detail.isEmpty ? "本项没有补充结果。" : row.detail)
                    if !guidance.isEmpty { Text(guidance).foregroundColor(theme.secondary) }
                }
                .font(.callout).lineSpacing(4).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 260)
            Text("可选中文字复制；点击浮层外关闭。").font(.caption2).foregroundColor(theme.secondary)
        }
        .padding(18).frame(width: 380)
        .foregroundColor(theme.text).background(theme.surface)
        .preferredColorScheme(theme.colorScheme)
    }
}

// MARK: - 公告页

struct NoticeView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme

    let sections: [(String, String)] = [
        ("账号使用与官方规则", "本人使用自己的账号，不共享或转交凭据，遵守服务条款、使用政策及适用地区要求。固定IP、时区和网站评分都不能保证账号不会停用。"),
        ("ASN 与 IP 历史", "ASN只表示网络归属。运营商名称未匹配时标为待核验，不能据此认定机房；名称匹配也不证明物理住宅线路。48小时统计的是不同IP个数，不是切换次数或官方封禁阈值。"),
        ("网络连通与账号权限", "探测请求不携带账号凭据。API返回401可能是正常的未认证响应；网页403需要进一步核实访问限制或验证挑战；429表示限流，5xx表示服务端异常。它们不能单独证明账号被封或账号可用。"),
        ("偏好设置与网络证据", "按用户选择严格核对时区、地区格式与英文语言基线，不符会阻止启动；这是本地策略，不是官方封禁判据。网络修复不会自动改写或放宽基线。Fake-IP只说明指定域名映射，不证明全部上游DNS路径。STUN无响应不代表零暴露。"),
        ("桌面账号与原生 CLI", "本工具切换Claude桌面数据目录，不等同于切换CLI账号或完全隔离系统钥匙串。官方CLI多账号可使用各自的CLAUDE_CONFIG_DIR，并通过官方流程登录。不要将订阅OAuth凭据提供给第三方代转发服务。"),
        ("路由核验与桌面运行监测", "无认证TLS探测连接按源端口与控制器记录核对规则和所选出口，真实应用连接另行标明。新版监测器仅在Claude桌面端运行时检查所选出口和API链路，连续两次失败才终止桌面主进程；不关闭浏览器或CLI，不提供防火墙级断网保证。"),
    ]
    let sources: [(String, String)] = [
        ("官方：认证与多账号", "https://code.claude.com/docs/en/authentication"),
        ("官方：网络配置", "https://code.claude.com/docs/en/network-config"),
        ("官方：认证用途与使用政策", "https://code.claude.com/docs/en/legal-and-compliance"),
        ("官方：账号警告与申诉", "https://support.claude.com/en/articles/8241253-safeguards-warnings-and-appeals"),
        ("官方：受限详情与复核", "https://claude.ai/restricted"),
    ]

    var body: some View {
        ZStack {
            theme.background.ignoresSafeArea()
            VStack(spacing: 0) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("使用建议与检查边界").font(.title3.bold()).foregroundColor(theme.text)
                        Text("本地检查说明 · 官方资料").font(.caption).foregroundColor(theme.secondary)
                    }
                    Spacer()
                    Button { dismiss() } label: {
                        Image(systemName: "xmark.circle.fill").font(.title2).foregroundColor(theme.secondary)
                    }
                    .buttonStyle(.plain)
                }
                .padding(20)

                ScrollView {
                    VStack(spacing: 10) {
                        Text("检查结果用于发现本地配置与连接问题，不能验证完整账号状态、代替平台规则或保证不会封号。红色故障阻止启动；黄色提醒需要核实；灰色为确认记录或范围说明。绿色探测路由仅表示本次探测通过，未观察的应用连接仍未核验。")
                            .font(.callout)
                            .foregroundColor(theme.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.bottom, 6)

                        ForEach(Array(sections.enumerated()), id: \.offset) { idx, s in
                            VStack(alignment: .leading, spacing: 5) {
                                Text("\(idx + 1). \(s.0)").font(.callout.bold()).foregroundColor(theme.accent)
                                Text(s.1).font(.caption).foregroundColor(theme.secondary).lineSpacing(3)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(12)
                            .background(theme.surface)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                        }

                        ForEach(Array(sources.enumerated()), id: \.offset) { _, source in
                            Link(source.0, destination: URL(string: source.1)!)
                                .font(.caption)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        Text("地区、账号与服务政策以官方当前版本为准。")
                            .font(.caption2).foregroundColor(theme.secondary)
                            .padding(.top, 8)
                    }
                    .padding(.horizontal, 20).padding(.bottom, 20)
                }
            }
        }
        .frame(width: 460, height: 620)
    }
}

// MARK: - App

class AppDelegate: NSObject, NSApplicationDelegate {
    // 关闭窗口即退出进程,杜绝"旧实例残留"
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct SwitcherApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
                .background(WindowAccessor { win in
                    guard let w = win else { return }
                    w.titlebarAppearsTransparent = true
                    w.titleVisibility = .hidden
                    w.styleMask.insert(.fullSizeContentView)
                    w.isMovableByWindowBackground = true
                    w.standardWindowButton(.zoomButton)?.isEnabled = false
                })
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
    }
}

struct WindowAccessor: NSViewRepresentable {
    let cb: (NSWindow?) -> Void
    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        DispatchQueue.main.async { self.cb(v.window) }
        return v
    }
    func updateNSView(_ nsView: NSView, context: Context) {}
}
