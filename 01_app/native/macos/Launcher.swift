import AppKit
import Foundation
import UniformTypeIdentifiers
import WebKit
import Darwin

final class Launcher: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    private var window: NSWindow!
    private var workbench: NSWindow?
    private var webView: WKWebView?
    private var instanceLock: Int32 = -1
    private let activateNotification = Notification.Name("cn.nero.disclosure.activate")

    // Both workspace and installed bundles share this lock, including open -n.
    private func claimWindow() -> Bool {
        let directory = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/NERO Disclosure Runtime")
        do { try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true) }
        catch { showLaunchError(error.localizedDescription); return false }
        instanceLock = Darwin.open(directory.appendingPathComponent("window.lock").path, O_CREAT | O_RDWR | O_CLOEXEC, S_IRUSR | S_IWUSR)
        guard instanceLock >= 0 else { showLaunchError("无法取得应用实例锁。"); return false }
        guard flock(instanceLock, LOCK_EX | LOCK_NB) == 0 else {
            if errno == EWOULDBLOCK {
                DistributedNotificationCenter.default().postNotificationName(activateNotification, object: nil, userInfo: nil, deliverImmediately: true)
                for id in ["cn.nero.disclosure.workspace", "cn.nero.disclosure.desktop"] {
                    for app in NSRunningApplication.runningApplications(withBundleIdentifier: id) where app.processIdentifier != getpid() {
                        app.activate(options: [])
                    }
                }
            } else { showLaunchError("无法检查已有应用实例。"); }
            Darwin.close(instanceLock); instanceLock = -1
            return false
        }
        DistributedNotificationCenter.default().addObserver(self, selector: #selector(activateExisting), name: activateNotification, object: nil)
        return true
    }

    private func showLaunchError(_ message: String) {
        let alert = NSAlert(); alert.messageText = "启动未完成"; alert.informativeText = message; alert.runModal()
    }

    @objc private func activateExisting() {
        if readyURL != nil && browserEnabled { showWorkbench() }
        else { window?.deminiaturize(nil); window?.makeKeyAndOrderFront(nil) }
        NSApp.activate(ignoringOtherApps: true)
    }

    private func showWorkbench() {
        guard let url = readyURL else { return }
        if workbench == nil {
            let page = WKWebView(frame: .zero)
            page.navigationDelegate = self; page.uiDelegate = self
            let frame = NSRect(x: 0, y: 0, width: 1200, height: 800)
            let view = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            view.title = "NERO 信披系统"; view.contentView = page
            view.delegate = self; view.isReleasedWhenClosed = false
            view.center(); workbench = view; webView = page
            page.load(URLRequest(url: url))
        }
        window?.orderOut(nil)
        workbench?.deminiaturize(nil); workbench?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func isWorkbenchURL(_ url: URL) -> Bool {
        guard let origin = readyURL else { return false }
        return url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if isWorkbenchURL(url) {
            if action.shouldPerformDownload || (action.targetFrame == nil && url.path.hasPrefix("/api/")) {
                decisionHandler(.download)
            } else {
                decisionHandler(.allow)
            }
        } else {
            // Authorization and public sources belong in the user's normal browser.
            if ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, isWorkbenchURL(url) { webView.load(action.request) }
        return nil
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let attachment = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition")?.lowercased().hasPrefix("attachment") == true
        decisionHandler(attachment || !response.canShowMIMEType ? .download : .allow)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.nameFieldStringValue = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        panel.begin { result in completionHandler(result == .OK ? panel.url : nil) }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) { showLaunchError("文件下载失败：" + error.localizedDescription) }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories; panel.canChooseFiles = true
        panel.begin { result in completionHandler(result == .OK ? panel.urls : nil) }
    }

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
    private let updateInstaller = Bundle.main.object(forInfoDictionaryKey: "NEROSoftwareUpdateInstaller") as? Bool ?? false
    private let deltaInstaller = Bundle.main.object(forInfoDictionaryKey: "NERODeltaUpdateInstaller") as? Bool ?? false
    private var bundledInstaller: Bool { fullInstaller || updateInstaller }
    private var releaseVersion: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0" }
    private var logDirectory: URL { bundledInstaller
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
        let savedHome = updateInstaller
            ? UserDefaults.standard.persistentDomain(forName: "cn.nero.disclosure.desktop")?["dataHome"] as? String
            : UserDefaults.standard.string(forKey: "dataHome")
        let selected = argument("--data-home") ?? savedHome
        home = workspace ?? selected.map { URL(fileURLWithPath: $0, isDirectory: true) } ?? defaultHome
        let beside = Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent("02_knowledge")
        if let specified = argument("--seed") { seed = URL(fileURLWithPath: specified) }
        else if FileManager.default.fileExists(atPath: beside.appendingPathComponent("packages/index.json").path) { seed = beside }
        modeInstall = seed != nil && Bundle.main.bundleURL.path.hasPrefix("/Volumes/")
        if CommandLine.arguments.contains("--installer") { modeInstall = true }
        if workspace != nil { modeInstall = false }
        if bundledInstaller { modeInstall = true }
        if !modeInstall && !claimWindow() { NSApp.terminate(nil); return }
        buildWindow()
        if modeInstall {
            setState(updateInstaller ? "更新信披系统 " + releaseVersion : "安装信披系统 " + releaseVersion, updateInstaller
                ? (deltaInstaller ? "仅适用于 1.0.1（构建 2026091901）。请先退出旧程序。差分更新保留知识库、会话、文稿和模型配置。" : "仅更新程序，保留原有知识库、会话、文稿和模型配置。请先退出旧程序，并核对下方资料目录。")
                : fullInstaller
                ? "一次安装软件、五类知识资料、历史会话和执行记录。请使用一个尚不存在的新资料目录；模型账号须重新授权。"
                : "程序将安装到个人应用程序目录，知识库独立保存在下方位置。", busy: false)
            primary.title = updateInstaller ? "更新并打开" : "安装并打开"
        } else { start() }
    }

    private func buildWindow() {
        let mainMenu = NSMenu()
        let appItem = NSMenuItem()
        mainMenu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "资料位置", action: #selector(openData), keyEquivalent: "")
        appMenu.addItem(withTitle: "查看日志", action: #selector(openLogs), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出信披系统", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        let editItem = NSMenuItem(); mainMenu.addItem(editItem)
        let editMenu = NSMenu(title: "编辑"); editItem.submenu = editMenu
        for (name, action, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: name, action: Selector(action), keyEquivalent: key)
        }
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
        seedButton.isHidden = workspace != nil || bundledInstaller
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
        if readyURL != nil { showWorkbench(); return }
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
        if updateInstaller && !NSRunningApplication.runningApplications(withBundleIdentifier: "cn.nero.disclosure.desktop").isEmpty {
            setState("请先退出旧程序", "退出原来的信披系统启动器后，再点击更新。现有资料保持不变。", busy: false)
            return
        }
        guard let target = installationTarget() else { return }
        var args = ["--data-home", home.path, "--install-to", target.path]
        if updateInstaller { args += ["--update-only"] }
        if fullInstaller, let resources = Bundle.main.resourceURL {
            args += ["--snapshot", resources.appendingPathComponent("MigrationData").path]
        }
        if let seed = seed { args += ["--seed", seed.path] }
        if FileManager.default.fileExists(atPath: target.path) {
            let alert = NSAlert()
            alert.messageText = "更新已安装的软件？"
            alert.informativeText = "现有知识库与工作记录继续保留，原应用保留为回退副本。\n应用位置：" + target.path
            alert.addButton(withTitle: "更新软件")
            alert.addButton(withTitle: "取消")
            if alert.runModal() != .alertFirstButtonReturn { return }
            args.append("--replace")
        }
        installing = true
        setState(updateInstaller ? "正在更新" : "正在安装", updateInstaller
            ? "正在核对程序、保留旧版本并更新。原有资料不被覆盖。"
            : "正在复制程序和运行环境，首次安装还会初始化知识库。", busy: true)
        run(args)
    }

    private func installationTarget() -> URL? {
        if let specified = argument("--install-to") { return URL(fileURLWithPath: specified) }
        let personal = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/NERO 信披系统.app")
        if !updateInstaller { return personal }
        func isInstalled(_ url: URL) -> Bool {
            if url.path.hasPrefix(Bundle.main.bundleURL.path + "/") || url.path.hasPrefix("/Volumes/") { return false }
            return Bundle(url: url)?.bundleIdentifier == "cn.nero.disclosure.desktop"
        }
        let candidates = [personal, URL(fileURLWithPath: "/Applications/NERO 信披系统.app")]
        if let target = candidates.first(where: isInstalled) { return target }
        if let found = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "cn.nero.disclosure.desktop"), isInstalled(found) { return found }
        let panel = NSOpenPanel()
        panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.applicationBundle]
        panel.prompt = "选择原应用"; panel.message = "请选择此前安装的 NERO 信披系统.app，更新包不会新建一套资料。"
        if panel.runModal() == .OK, let target = panel.url, isInstalled(target) { return target }
        setState("未选择原应用", "请先找到原来的 NERO 信披系统.app，再点击更新。", busy: false)
        return nil
    }

    private func run(_ args: [String]) {
        guard let resources = Bundle.main.resourceURL else { return }
        #if arch(arm64)
        let architecture = "arm64"
        #else
        let architecture = "x86_64"
        #endif
        let appResources = bundledInstaller
            ? resources.appendingPathComponent("Applications/"+architecture+"/NERO 信披系统.app/Contents/Resources")
            : resources
        let code = (workspace ?? appResources).appendingPathComponent("01_app")
        let python = workspace != nil
            ? URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "NEROWorkspacePython") as? String ?? "")
            : code.appendingPathComponent("runtime/macos/python/bin/python3.13")
        let child = Process()
        child.executableURL = python
        child.arguments = ["-B", "-s", "-u", code.appendingPathComponent("scripts/macos_desktop.py").path] + args + (workspace == nil ? [] : ["--workspace"])
        if deltaInstaller {
            child.executableURL = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/DeltaApply")
            child.arguments = ["--delta", resources.appendingPathComponent("Deltas/" + architecture).path] + args
        }
        child.currentDirectoryURL = deltaInstaller ? resources : code
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
                    self.workbench?.orderOut(nil); self.workbench = nil; self.webView = nil
                    self.window.makeKeyAndOrderFront(nil)
                    if finished.terminationStatus == 0 {
                        self.setState("工作台已停止", "知识库和工作记录已保留，可以再次启动。", busy: false)
                    } else if self.title.stringValue != "启动未完成" {
                        self.setState("启动未完成", "请点击“查看日志”核对失败原因，再重新启动。", busy: false)
                    }
                    self.installing = false
                    self.primary.title = self.modeInstall ? (self.updateInstaller ? "更新并打开" : "安装并打开") : "重新启动"
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
                if browserEnabled && readyURL != nil { showWorkbench() }
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
                if bundledInstaller && argument("--desktop-folder") == nil {
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
                configuration.createsNewApplicationInstance = false
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
        activateExisting()
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
