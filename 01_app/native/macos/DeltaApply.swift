import Foundation
import CryptoKit
import Darwin

struct Entry: Codable, Equatable {
    let kind: String
    let mode: Int?
    let sha256: String?
    let bytes: Int?
    let link: String?
}
struct Delta: Decodable {
    let schema: String
    let baseline_version: String
    let baseline_build: String
    let version: String
    let build: String
    let before: [String: Entry]
    let after: [String: Entry]
}
struct Failure: Error, CustomStringConvertible { let description: String }
let fm = FileManager.default
func fail(_ message: String) throws -> Never { throw Failure(description: message) }
func event(_ kind: String, _ values: [String: Any] = [:]) {
    var body = values; body["event"] = kind
    if let data = try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys]), let line = String(data: data, encoding: .utf8) {
        print("NERO_EVENT " + line); fflush(stdout)
    }
}
func hash(_ url: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
    var hash = SHA256()
    while let data = try handle.read(upToCount: 1_048_576), !data.isEmpty { hash.update(data: data) }
    return hash.finalize().map { String(format: "%02x", $0) }.joined()
}
func checkPaths(_ rows: [String: Entry]) throws {
    for (name, row) in rows {
        let parts = name.split(separator: "/", omittingEmptySubsequences: false)
        if name.hasPrefix("/") || name.contains("\0") || parts.contains(where: { $0 == ".." || $0 == "." || $0.isEmpty }) { try fail("差分清单路径无效") }
        if !["file", "directory", "link"].contains(row.kind) { try fail("不支持的文件类型") }
        if row.kind == "file" && (row.sha256?.range(of: "^[0-9a-f]{64}$", options: .regularExpression) == nil || row.bytes == nil || row.mode == nil) { try fail("文件校验值缺失") }
        if row.kind == "directory" && row.mode == nil { try fail("目录权限缺失") }
        if row.kind == "link" {
            guard let link = row.link, !link.hasPrefix("/"), !link.contains("\0") else { try fail("软件链接无效") }
            let anchor = URL(fileURLWithPath: "/delta-root", isDirectory: true)
            let destination = anchor.appendingPathComponent(name).deletingLastPathComponent().appendingPathComponent(link).standardizedFileURL
            if !destination.path.hasPrefix(anchor.path + "/") { try fail("软件链接越界") }
        }
        var parent = (name as NSString).deletingLastPathComponent
        while !parent.isEmpty {
            if rows[parent]?.kind != "directory" { try fail("清单父目录无效") }
            parent = (parent as NSString).deletingLastPathComponent
        }
    }
}
func inventory(_ root: URL) throws -> [String: Entry] {
    var rows: [String: Entry] = [:]
    func walk(_ relative: String) throws {
        for leaf in try fm.contentsOfDirectory(atPath: root.appendingPathComponent(relative).path).sorted() {
            if leaf == ".DS_Store" { continue }
            let name = relative.isEmpty ? leaf : relative + "/" + leaf
            let url = root.appendingPathComponent(name)
            let a = try fm.attributesOfItem(atPath: url.path)
            let mode = (a[.posixPermissions] as? NSNumber)?.intValue ?? 0
            switch a[.type] as? FileAttributeType {
            case .typeSymbolicLink:
                rows[name] = Entry(kind: "link", mode: nil, sha256: nil, bytes: nil, link: try fm.destinationOfSymbolicLink(atPath: url.path))
            case .typeDirectory:
                rows[name] = Entry(kind: "directory", mode: mode, sha256: nil, bytes: nil, link: nil)
                try walk(name)
            case .typeRegular:
                rows[name] = Entry(kind: "file", mode: mode, sha256: try hash(url), bytes: (a[.size] as? NSNumber)?.intValue, link: nil)
            default: try fail("不支持的软件文件：" + name)
            }
        }
    }
    try walk("")
    return rows
}

func verify(_ root: URL, _ expected: [String: Entry], _ label: String) throws {
    let actual = try inventory(root)
    if actual != expected {
        let name = Set(actual.keys).union(expected.keys).sorted().first(where: { actual[$0] != expected[$0] }) ?? ""
        try fail(label + "不匹配，未替换程序：" + name)
    }
}
func signed(_ app: URL) throws {
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
    p.arguments = ["--verify", "--deep", "--strict", app.path]
    p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
    try p.run(); p.waitUntilExit()
    if p.terminationStatus != 0 { try fail("软件签名校验失败，未替换程序") }
}
func lock(_ path: URL) throws -> Int32 {
    let fd = Darwin.open(path.path, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, S_IRUSR | S_IWUSR)
    if fd < 0 { try fail("无法取得更新锁") }
    if flock(fd, LOCK_EX | LOCK_NB) != 0 { Darwin.close(fd); try fail("请先退出正在运行的信披系统或其他更新任务") }
    return fd
}
func swap(_ a: URL, _ b: URL) throws {
    let result = a.path.withCString { left in b.path.withCString { right in renameatx_np(AT_FDCWD, left, AT_FDCWD, right, UInt32(RENAME_SWAP)) } }
    if result != 0 { try fail("系统无法完成程序交换；已保留程序文件及恢复记录：" + String(cString: strerror(errno))) }
}
func main() throws {
    var args: [String: String] = [:]; var flags = Set<String>(); var i = 1
    while i < CommandLine.arguments.count {
        let key = CommandLine.arguments[i]
        if ["--replace", "--update-only", "--verify-only"].contains(key) { flags.insert(key); i += 1; continue }
        if !["--delta", "--install-to", "--data-home", "--reconstruct-to"].contains(key) || i + 1 >= CommandLine.arguments.count { try fail("更新参数无效") }
        args[key] = CommandLine.arguments[i + 1]; i += 2
    }
    guard let destination = args["--install-to"], let dataHome = args["--data-home"], let patch = args["--delta"] else { try fail("请选择已安装的原应用和原资料目录") }
    let input = URL(fileURLWithPath: destination).standardizedFileURL
    if (try input.resourceValues(forKeys: [.isSymbolicLinkKey])).isSymbolicLink == true || input.pathExtension != "app" { try fail("原应用路径无效") }
    let target = input.resolvingSymlinksInPath(); let home = URL(fileURLWithPath: dataHome).resolvingSymlinksInPath()
    if target.path.hasPrefix(home.appendingPathComponent("02_knowledge").path + "/") || home.path.hasPrefix(target.path + "/") { try fail("程序和资料目录不能互相包含") }
    for part in ["02_knowledge", "03_local"] {
        let p = home.appendingPathComponent(part); let values = try p.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        if values.isDirectory != true || values.isSymbolicLink == true { try fail("请选择原有资料目录，不新建或迁移资料") }
    }
    let executable = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    let updater = executable.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    let resources = updater.appendingPathComponent("Contents/Resources")
    #if arch(arm64)
    let architecture = "arm64"
    #else
    let architecture = "x86_64"
    #endif
    let deltaRoot = URL(fileURLWithPath: patch).resolvingSymlinksInPath()
    if deltaRoot != resources.appendingPathComponent("Deltas/" + architecture).resolvingSymlinksInPath() || target.path.hasPrefix(updater.path + "/") { try fail("差分载荷位置或目标架构不符") }
    try signed(updater)
    let manifest = try JSONDecoder().decode(Delta.self, from: Data(contentsOf: deltaRoot.appendingPathComponent("manifest.json")))
    if manifest.schema != "nero.disclosure.delta.v1" || manifest.baseline_version != "1.0.1" || manifest.baseline_build != "2026091901" || manifest.version != "1.0.2" { try fail("差分版本不匹配") }
    try checkPaths(manifest.before); try checkPaths(manifest.after)
    let dataLock = try lock(home.appendingPathComponent(".desktop.lock")); defer { Darwin.close(dataLock) }
    let parent = target.deletingLastPathComponent()
    let installLock = try lock(parent.appendingPathComponent(".nero-delta-update.lock")); defer { Darwin.close(installLock) }
    event("progress", ["message":"正在核对 1.0.1 基线全部文件"])
    try verify(target, manifest.before, "原应用与冻结的 1.0.1 基线")
    for (name, row) in manifest.after where row.kind == "file" && manifest.before[name] != row {
        if try hash(deltaRoot.appendingPathComponent("blobs/" + row.sha256!)) != row.sha256 { try fail("差分文件损坏，未替换程序") }
    }
    if flags.contains("--verify-only") { event("checked", ["baseline":"1.0.1"]); return }
    if !flags.contains("--replace") || !flags.contains("--update-only") { try fail("差分更新只允许原位更新已安装程序") }
    let stage = parent.appendingPathComponent(".nero-delta-" + UUID().uuidString + ".app")
    var stageContainsOld = false
    defer { if !stageContainsOld { try? fm.removeItem(at: stage) } }
    event("progress", ["message":"正在复制原程序并应用差分，原程序和资料保持不变"])
    try fm.copyItem(at: target, to: stage)
    // Recheck the snapshot to catch an old application changed during copying.
    try verify(stage, manifest.before, "原应用快照")
    for (name, row) in manifest.before where row.kind == "directory" { try fm.setAttributes([.posixPermissions:0o755], ofItemAtPath:stage.appendingPathComponent(name).path) }
    for name in manifest.before.keys.sorted(by: { $0.count > $1.count }) {
        if manifest.after[name] == nil || manifest.after[name]?.kind != manifest.before[name]?.kind {
            try fm.removeItem(at: stage.appendingPathComponent(name))
        }
    }
    for name in manifest.after.keys.sorted(by: { $0.count < $1.count }) {
        let row = manifest.after[name]!, path = stage.appendingPathComponent(name)
        if row.kind == "directory" { try fm.createDirectory(at: path, withIntermediateDirectories: true); continue }
        if manifest.before[name] == row { continue }
        if fm.fileExists(atPath:path.path) || (try? fm.destinationOfSymbolicLink(atPath:path.path)) != nil { try fm.removeItem(at:path) }
        if row.kind == "link" { try fm.createSymbolicLink(atPath:path.path, withDestinationPath:row.link!) }
        else { try fm.copyItem(at:deltaRoot.appendingPathComponent("blobs/" + row.sha256!), to:path); try fm.setAttributes([.posixPermissions:row.mode!], ofItemAtPath:path.path) }
    }
    for (name, row) in manifest.after where row.kind == "directory" { try fm.setAttributes([.posixPermissions:row.mode!], ofItemAtPath:stage.appendingPathComponent(name).path) }
    try verify(stage, manifest.after, "重建的 1.0.2 程序"); try signed(stage)
    if let output = args["--reconstruct-to"] {
        let path = URL(fileURLWithPath:output)
        if fm.fileExists(atPath:path.path) { try fail("重建输出已存在") }
        try fm.moveItem(at:stage,to:path); event("reconstructed",["app":path.path]); return
    }
    // No data migration: only swap two complete verified application directories.
    try verify(target, manifest.before, "替换前的原应用")
    let backup = parent.appendingPathComponent(target.deletingPathExtension().lastPathComponent + ".previous-" + UUID().uuidString + ".app.backup")
    let journal = parent.appendingPathComponent(".nero-delta-recovery-" + UUID().uuidString + ".json")
    let receipt = ["app":target.path,"staging":stage.path,"backup":backup.path,"version":"1.0.2"]
    try JSONSerialization.data(withJSONObject:receipt).write(to:journal,options:.atomic)
    try swap(stage,target); stageContainsOld = true
    do { try fm.moveItem(at:stage,to:backup) }
    catch {
        // Never delete the old application if rollback itself encounters an I/O error.
        try swap(stage,target); stageContainsOld = false
        try fail("回退副本无法保存，已恢复原程序")
    }
    try? fm.removeItem(at:journal)
    event("installed",["app":target.path,"home":home.path,"knowledge":"existing_preserved","previous_app":backup.path])
}
do { try main() }
catch { event("error",["message":String(describing:error)]); exit(1) }
