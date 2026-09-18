# macOS 打包与安装

macOS 启动器使用 Swift，业务界面仍在默认浏览器中打开。运行版要求 macOS 13.5 或更新版本，按 arm64 或 x86_64 架构准备对应组件。

## 构建输入

发行包需要已构建前端、目标架构的 Python 与依赖、Node.js、Pi 依赖、原生 OCR 组件，以及经授权的知识包。仓库本身不包含这些已安装组件或正式知识资料。

先构建页面，再查看发行脚本参数：

```sh
(cd 01_app/frontend && npm ci && npm run build)
.venv/bin/python 01_app/scripts/build_macos_release.py --help
```

| 参数 | 用途 |
| --- | --- |
| `--arch` | `arm64` 或 `x86_64` |
| `--python-root`、`--site-packages` | 可重定位的 Python 目录与已准备的依赖 |
| `--node-root` | 目标架构 Node.js 目录 |
| `--output` | 新的构建输出目录，已有目录拒绝覆盖 |
| `--identity` | 代码签名身份，默认 `-` 为 ad-hoc 签名 |
| `--dmg` | 同时生成磁盘镜像 |

脚本复制已有的 `frontend/dist/`，不会自动构建前端。`BUILD_RECEIPT.json` 记录来源提交、架构、文件哈希与构建结果；签名和公证状态以实际发行产物为准。运行构建脚本需要维护者安排，CI 不自动制作或发布 App。

## 安装与数据

普通发行包将 `01_app` 放在 App 内，`02_knowledge` 作为独立初始知识快照随介质提供。安装器默认把软件安装到个人应用程序目录，数据放在 `~/Library/Application Support/NERO Disclosure`。

已有知识和工作记录不会在普通更新时被覆盖。迁移数据前先退出服务并备份；新电脑需要重新授权模型。交付用步骤见 [INSTALL.txt](../native/macos/INSTALL.txt)。

## 完整迁移包

`scripts/build_macos_migration.py` 接收两种架构的软件载荷和完整资料快照，生成迁移安装器。该包可能包含知识库、公司公告、会话、附件与文稿，只适合明确授权的资料迁移，不得作为公共源码附件或公开下载包。

## 验证

打包后使用 `scripts/validate_macos_release.py` 检查安装副本。自动检查不能替代目标 Mac 上的首次安装、更新、退出、数据迁移和模型授权测试。

`runtime/windows-x64/` 与 `scripts/windows_onboard.py` 保留 Windows 相关实现。macOS 测试通过不能代表 Windows 原生运行通过。未签名或未公证的包可能受到系统限制，不应关闭系统安全保护来绕过。
