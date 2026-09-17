import AppKit
import Foundation

final class Launcher: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow!
    private let title = NSTextField(labelWithString: "NERO 信息披露")
    private let detail = NSTextField(wrappingLabelWithString: "正在准备工作台")
    private let location = NSTextField(wrappingLabelWithString: "")
    private let spinner = NSProgressIndicator()
    private let primary = NSButton(title: "打开工作台", target: nil, action: nil)
    private let folders = NSButton(title: "资料位置", target: nil, action: nil)
    private let logs = NSButton(title: "查看日志", target: nil, action: nil)
    private let choose = NSButton(title: "选择数据目录…", target: nil, action: nil)
    private var process: Process?
    private var control: Pipe?
    private var output: Pipe?
    private var errorHandle: FileHandle?
    private var buffer = Data()
    private var readyURL: URL?
    private var quitting = false
    private var installed = false
    private var installedApplication: URL?
    private var attached = false
    private var installing = false
    private var modeInstall = false
    private var home: URL!
    private var seed: URL?
    private var browserEnabled = true
    private let fullInstaller = Bundle.main.object(forInfoDictionaryKey: "NEROFullMigrationInstaller") as? Bool ?? false
    private var logDirectory: URL { fullInstaller
        ? URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("NERO-Disclosure-Installer-Logs")
        : home.appendingPathComponent("03_local/var/logs") }
    private let workspace = (Bundle.main.object(forInfoDictionaryKey: "NEROWorkspaceRoot") as? String).map { URL(fileURLWithPath: $0) }

    private func argument(_ name: String) -> String? {
        let values = CommandLine.arguments
        guard let i = values.firstIndex(of: name), i + 1 < values.count else { return nil }
        return values[i+1]
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        browserEnabled = !CommandLine.arguments.contains("--no-browser")
        let defaultHome = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/NERO Disclosure")
        let selected = argument("--data-home") ?? UserDefaults.standard.string(forKey: "dataHome")
        home = workspace ?? selected.map { URL(fileURLWithPath: $0, isDirectory: true) } ?? defaultHome
        let beside = Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent("02_knowledge")
        if let specified = argument("--seed") { seed = URL(fileURLWithPath: specified) }
        else if FileManager.default.fileExists(atPath: beside.appendingPathComponent("packages/index.json").path) { seed = beside }
        modeInstall = seed != nil && Bundle.main.bundleURL.path.hasPrefix("/Volumes/")
        if CommandLine.arguments.contains("--installer") { modeInstall = true }
        if workspace != nil { modeInstall = false }
        if fullInstaller { modeInstall = true }
        buildWindow()
        if modeInstall {
            setState("安装信披系统 1.0", fullInstaller
                ? "一次安装软件、五类知识资料、历史会话和执行记录。请使用一个尚不存在的新资料目录；模型账号须重新授权。"
                : "程序将安装到个人应用程序目录，知识库独立保存在下方位置。", busy: false)
            primary.title = "安装并打开"
        } else { start() }
    }

    private func buildWindow() {
        let mainMenu = NSMenu()
        let appItem = NSMenuItem()
        mainMenu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出信披系统", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        NSApp.mainMenu = mainMenu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 330),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "NERO 信披系统"
        window.delegate = self
        window.isReleasedWhenClosed = false
        let view = NSView(frame: window.contentView!.bounds)
        window.contentView = view
        title.font = .systemFont(ofSize: 23, weight: .semibold)
        title.frame = NSRect(x: 28, y: 263, width: 480, height: 34)
        detail.font = .systemFont(ofSize: 14)
        detail.frame = NSRect(x: 28, y: 166, width: 480, height: 84)
        detail.maximumNumberOfLines = 5
        location.font = .systemFont(ofSize: 11)
        location.textColor = .secondaryLabelColor
        location.isSelectable = true
        location.frame = NSRect(x: 28, y: 112, width: 480, height: 44)
        location.stringValue = "资料目录：\n" + home.path
        spinner.style = .bar
        spinner.isIndeterminate = true
        spinner.frame = NSRect(x: 28, y: 155, width: 480, height: 5)
        for label in [title, detail, location] { view.addSubview(label) }
        view.addSubview(spinner)
        let buttons = [primary, folders, logs, choose]
        for button in buttons { button.bezelStyle = .rounded; button.target = self; view.addSubview(button) }
        primary.action = #selector(primaryAction)
        primary.frame = NSRect(x: 28, y: 66, width: 150, height: 34)
        primary.keyEquivalent = "\r"
        folders.action = #selector(openData)
        folders.frame = NSRect(x: 187, y: 66, width: 100, height: 34)
        logs.action = #selector(openLogs)
        logs.frame = NSRect(x: 294, y: 66, width: 100, height: 34)
        choose.action = #selector(chooseHome)
        choose.frame = NSRect(x: 24, y: 20, width: 150, height: 28)
        let quit = NSButton(title: "退出", target: NSApp, action: #selector(NSApplication.terminate(_:)))
        quit.bezelStyle = .rounded
        quit.frame = NSRect(x: 405, y: 66, width: 105, height: 34)
        view.addSubview(quit)
        let seedButton = NSButton(title: "选择初始知识库…", target: self, action: #selector(chooseSeed))
        seedButton.bezelStyle = .rounded
        seedButton.frame = NSRect(x: 178, y: 20, width: 145, height: 28)
        view.addSubview(seedButton)
        choose.isHidden = workspace != nil
        seedButton.isHidden = workspace != nil || fullInstaller
        let note = NSTextField(labelWithString: "退出仅停止本窗口启动的服务。")
        note.font = .systemFont(ofSize: 11)
        note.textColor = .secondaryLabelColor
        note.frame = NSRect(x: 322, y: 25, width: 200, height: 18)
        view.addSubview(note)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func setState(_ heading: String, _ message: String, busy: Bool) {
        title.stringValue = heading
        detail.stringValue = message
        primary.isEnabled = !busy
        choose.isEnabled = !busy && process?.isRunning != true
        spinner.isHidden = !busy
        if busy { spinner.startAnimation(nil) } else { spinner.stopAnimation(nil) }
    }

    @objc private func primaryAction() {
        if let application = installedApplication { NSWorkspace.shared.open(application); return }
        if let url = readyURL { NSWorkspace.shared.open(url); return }
        if modeInstall { installApp() } else { start() }
    }

    private func start() {
        guard process?.isRunning != true else { return }
        setState("正在启动", "正在检查运行环境和知识库。", busy: true)
        var args = ["--data-home", home.path]
        if let seed = seed { args += ["--seed", seed.path] }
        if let port = argument("--port") { args += ["--port", port] }
        run(args)
    }

    private func installApp() {
        let target = argument("--install-to").map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/NERO 信披系统.app")
        var args = ["--data-home", home.path, "--install-to", target.path]
        if fullInstaller, let resources = Bundle.main.resourceURL {
            args += ["--snapshot", resources.appendingPathComponent("MigrationData").path]
        }
        if let seed = seed { args += ["--seed", seed.path] }
        if FileManager.default.fileExists(atPath: target.path) {
            let alert = NSAlert()
            alert.messageText = "更新已安装的软件？"
            alert.informativeText = "现有知识库与工作记录继续保留，原应用保留为回退副本。请先退出正在运行的旧版本。"
            alert.addButton(withTitle: "更新软件")
            alert.addButton(withTitle: "取消")
            if alert.runModal() != .alertFirstButtonReturn { return }
            args.append("--replace")
        }
        installing = true
        setState("正在安装", "正在复制程序和运行环境，首次安装还会初始化知识库。", busy: true)
        run(args)
    }

    private func run(_ args: [String]) {
        guard let resources = Bundle.main.resourceURL else { return }
        #if arch(arm64)
        let architecture = "arm64"
        #else
        let architecture = "x86_64"
        #endif
        let appResources = fullInstaller
            ? resources.appendingPathComponent("Applications/"+architecture+"/NERO 信披系统.app/Contents/Resources")
            : resources
        let code = (workspace ?? appResources).appendingPathComponent("01_app")
        let python = workspace != nil
            ? URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "NEROWorkspacePython") as? String ?? "")
            : code.appendingPathComponent("runtime/macos/python/bin/python3.13")
        let child = Process()
        child.executableURL = python
        child.arguments = ["-B", "-s", "-u", code.appendingPathComponent("scripts/macos_desktop.py").path] + args + (workspace == nil ? [] : ["--workspace"])
        child.currentDirectoryURL = code
        child.environment = ["PATH":"/usr/bin:/bin:/usr/sbin:/sbin", "HOME":FileManager.default.homeDirectoryForCurrentUser.path,
                             "TMPDIR":NSTemporaryDirectory(), "LANG":"en_US.UTF-8", "PYTHONUTF8":"1",
                             "PYTHONDONTWRITEBYTECODE":"1", "PYTHONNOUSERSITE":"1"]
        let input = Pipe(), output = Pipe()
        self.control = input; self.output = output; self.buffer = Data(); self.readyURL = nil; self.attached = false
        child.standardInput = input; child.standardOutput = output
        do {
            let directory = logDirectory
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let log = directory.appendingPathComponent("desktop-\(Int(Date().timeIntervalSince1970)).log")
            FileManager.default.createFile(atPath: log.path, contents: nil)
            let handle = try FileHandle(forWritingTo: log)
            errorHandle = handle; child.standardError = handle
            output.fileHandleForReading.readabilityHandler = { [weak self] pipe in
                let data = pipe.availableData
                if data.isEmpty { pipe.readabilityHandler = nil; return }
                DispatchQueue.main.async { self?.receive(data) }
            }
            child.terminationHandler = { [weak self] finished in
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    self.process = nil
                    try? self.control?.fileHandleForWriting.close()
                    try? self.errorHandle?.close()
                    if self.installed { return }
                    if self.quitting { NSApp.reply(toApplicationShouldTerminate: true); return }
                    if self.attached { return }
                    if self.readyURL != nil { self.readyURL = nil }
                    if finished.terminationStatus == 0 {
                        self.setState("工作台已停止", "知识库和工作记录已保留，可以再次启动。", busy: false)
                    } else if self.title.stringValue != "启动未完成" {
                        self.setState("启动未完成", "请点击“查看日志”核对失败原因，再重新启动。", busy: false)
                    }
                    self.installing = false
                    self.primary.title = self.modeInstall ? "安装并打开" : "重新启动"
                }
            }
            process = child
            try child.run()
        } catch {
            process = nil
            setState("启动未完成", error.localizedDescription, busy: false)
            primary.title = "重试"
        }
    }

    private func receive(_ bytes: Data) {
        buffer.append(bytes)
        while let range = buffer.range(of: Data([10])) {
            let line = buffer.subdata(in: 0..<range.lowerBound)
            buffer.removeSubrange(0..<range.upperBound)
            guard let text = String(data: line, encoding: .utf8), text.hasPrefix("NERO_EVENT "),
                  let raw = text.dropFirst(11).data(using: .utf8),
                  let value = try? JSONSerialization.jsonObject(with: raw) as? [String:Any],
                  let kind = value["event"] as? String else { continue }
            try? errorHandle?.write(contentsOf: line + Data([10]))
            switch kind {
            case "progress": detail.stringValue = value["message"] as? String ?? "正在处理"
            case "ready", "attached":
                attached = kind == "attached"
                if let url = value["url"] as? String { readyURL = URL(string: url) }
                setState("工作台已就绪", "现有 WebUI 已可使用。首次使用请在“模型设置”中授权自己的账号。", busy: false)
                choose.isEnabled = false; primary.title = "打开工作台"
                if browserEnabled, let url = readyURL { NSWorkspace.shared.open(url) }
            case "error":
                setState("启动未完成", value["message"] as? String ?? "请查看日志", busy: false)
                primary.title = "重试"
            case "installed":
                guard let path = value["app"] as? String else { continue }
                installed = true
                installedApplication = URL(fileURLWithPath: path)
                if argument("--desktop-folder") == nil { UserDefaults.standard.set(home.path, forKey: "dataHome") }
                // The installer and installed application have separate bundle IDs.
                var settings = UserDefaults.standard.persistentDomain(forName: "cn.nero.disclosure.desktop") ?? [:]
                settings["dataHome"] = home.path
                if fullInstaller && argument("--desktop-folder") == nil {
                    UserDefaults.standard.setPersistentDomain(settings, forName: "cn.nero.disclosure.desktop")
                }
                if fullInstaller {
                    do { try createDesktopAlias(URL(fileURLWithPath: path)) }
                    catch {
                        setState("软件和资料已安装", "桌面快捷方式未创建："+error.localizedDescription+"。请从应用程序目录打开。", busy: false)
                        primary.title = "打开已安装软件"
                        continue
                    }
                }
                installed = true
                setState("安装完成", "正在打开已安装的软件。", busy: false)
                let configuration = NSWorkspace.OpenConfiguration()
                configuration.createsNewApplicationInstance = true
                configuration.arguments = ["--data-home", home.path] + (browserEnabled ? [] : ["--no-browser"])
                NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: path), configuration: configuration) { _, error in
                    DispatchQueue.main.async {
                        if let error = error { self.installed = false; self.setState("请打开已安装的软件", error.localizedDescription, busy: false) }
                        else { NSApp.terminate(nil) }
                    }
                }
            default: break
            }
        }
        if buffer.count > 1_000_000 { buffer.removeAll() }
    }

    @objc private func openData() { NSWorkspace.shared.open(home) }
    private func createDesktopAlias(_ application: URL) throws {
        let desktop = argument("--desktop-folder").map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask)[0]
        try FileManager.default.createDirectory(at: desktop, withIntermediateDirectories: true)
        var destination = desktop.appendingPathComponent("NERO 信披系统")
        if FileManager.default.fileExists(atPath: destination.path) {
            destination = desktop.appendingPathComponent("NERO 信披系统 1.0-"+String(UUID().uuidString.prefix(6)))
        }
        let data = try application.bookmarkData(options: .suitableForBookmarkFile, includingResourceValuesForKeys: nil, relativeTo: nil)
        try URL.writeBookmarkData(data, to: destination)
    }

    @objc private func openLogs() { NSWorkspace.shared.open(logDirectory) }
    @objc private func chooseHome() {
        guard process?.isRunning != true else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true
        panel.prompt = "使用此数据目录"
        panel.message = fullInstaller ? "选择一个父文件夹，将在其中新建独立的迁移资料目录。" : "选择保存 02_knowledge 和 03_local 的父文件夹。"
        if panel.runModal() == .OK, let url = panel.url {
            home = fullInstaller ? url.appendingPathComponent("NERO Disclosure-"+String(UUID().uuidString.prefix(6))) : url
            UserDefaults.standard.set(home.path, forKey: "dataHome")
            location.stringValue = "资料目录：\n" + home.path
        }
    }

    @objc private func chooseSeed() {
        guard process?.isRunning != true else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.prompt = "选择知识库"
        panel.message = "选择安装介质中的 02_knowledge 文件夹。只在当前数据目录尚无知识库时初始化。"
        if panel.runModal() == .OK, let url = panel.url {
            seed = url
            detail.stringValue = "已选择初始知识库，点击上方按钮继续。"
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        if let url = readyURL, browserEnabled { NSWorkspace.shared.open(url) }
        return true
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let child = process, child.isRunning else { return .terminateNow }
        quitting = true
        setState("正在退出", "正在停止本机服务，请稍候。", busy: true)
        try? control?.fileHandleForWriting.close()
        if installing { child.terminate() }
        DispatchQueue.main.asyncAfter(deadline: .now()+35) {
            if child.isRunning { child.terminate() }
        }
        return .terminateLater
    }
}

let app = NSApplication.shared
let delegate = Launcher()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
