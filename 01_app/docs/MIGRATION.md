# 正式 App 启动与资料迁移

日常统一从正式 **NERO 信披系统 App** 启动，根目录双击脚本已退役。迁移时先核对启动器显示的资料目录，再完整复制资料；**不迁移模型密钥，不修改全局模型路由。** Mac 安装步骤见[安装说明](../native/macos/INSTALL.txt)。

## 迁移步骤

1. 在旧电脑结束当前执行并退出启动器，确认服务退出后再复制。不要在数据库仍有写入时复制，也不要遗漏同目录下的数据库辅助文件。
2. 保留原文件夹作为回退副本，将启动器显示的资料目录完整拷到新电脑的可写位置，保留 `02_knowledge` 和 `03_local` 及其关联文件。当前绑定本工作区的 App 使用本工作区目录；标准发行 App 默认使用 `~/Library/Application Support/NERO Disclosure`，不要混淆两种位置。
3. 在新 Mac 上使用对应架构的正式安装包。安装界面先选择复制后的资料父目录，再安装并打开。本机桌面入口绑定了当前工作区路径，不能仅复制该 App 就认为它会自动指向新目录。Windows 需使用对应平台的正式发行入口，当前仓库不再提供根目录双击脚本。
4. 成功后浏览器会打开本机地址。先查看原事项、会话、知识库和交付文件，再到“模型设置”重新授权、测试连接。
5. 新电脑确认可用前保留旧电脑副本。避免同时修改两边的数据；本系统没有自动同步或合并两台电脑记录的能力。

## 源码运行环境的维护边界

以下为保留的工程维护机制，不是日常启动入口；正式 App 的安装、资料目录和更新行为以安装说明为准。

| 内容 | 处理方式 |
| --- | --- |
| Python | Windows 使用随目录提供的 3.13.12 嵌入式运行包；缺少时按锁文件从官方地址下载。macOS 通过项目内 uv 准备 3.13.12 |
| Python 依赖 | 按锁定版本准备在项目目录。macOS 换目录时新建环境；Windows 保留原包，缺少依赖时新建版本目录 |
| Node.js | 准备项目内 24.21.0，不要求预装 Node.js，不修改全局 PATH |
| Pi | 按 `01_app/runtime/pi/package-lock.json` 准备依赖并检查共享模型合同中的原生接口能否加载；保留旧依赖，失败时恢复旧目录 |
| WebUI | 直接使用 `01_app/frontend/dist/` 的已构建页面；不会在新电脑自动构建 App 或前端 |
| 启动 | 检查端口和项目身份，再启动本机服务、打开浏览器；关闭窗口中的服务需按 `Ctrl+C` |

首次配置的联网请求用于下载公开运行组件和依赖，不向模型发送业务材料。下载的官方发行包会在项目内解压；这不涉及将用户文件压缩打包。uv、Node.js 和 Windows Python 的版本、地址及 SHA256 均锁定，不在启动时追踪 `latest`。

环境准备只写项目目录及操作系统正常临时目录，不调用管理员安装器、不安装 Homebrew、不修改 shell 配置、注册表或永久 PATH。不要把“环境已就绪”理解为模型已授权、真实业务已验收或 Windows 实机验证已完成。

## 不能自动迁移的内容

- **模型账号和密钥。** ChatGPT、API Key 等保存在操作系统安全凭据库，且项目路径参与隔离。新电脑或新路径需要重新授权；历史连接结果不代表新环境可用。
- **OpenCodex / Gemini 通道。** 这是可选的独立软件及账号环境，不随本文件夹自动迁移。新电脑选择 Gemini 时须先准备该通道。普通 `opencodex start` 可能同步 Codex 全局配置，本脚本不会代为执行。
- **Office、WPS 和商业字体。** Word 文件保留，但实际显示需要目标电脑上的软件和字体，仍须逐页检查。
- **企业身份与客户内部资料接口。** 原系统未接入的能力不会因复制目录而自动出现。

整个文件夹可能包含个人项目数据和宿主连接记录，仅用于本次授权的电脑迁移。若需要交给另一个人使用，应另行确定哪些数据可以交付，不能把个人数据目录当作空白演示模板。

## 必须保留的目录

按三类目录保留：`01_app/`（软件与规则，含 `backend/`、`scripts/`、`frontend/dist/`、`skills/`、`runtime/`）、`02_knowledge/`（知识库：`data/`、`templates/` 与包清单）、`03_local/`（本机资料：`var/`、`work/`、`output/`、`records/` 与 `.venv/`），以及根目录导航和项目规则。不要删除 `03_local/var/`，它包含事项数据库、会话数据库、文稿、交付物、模型设置和历史。

目前交付物按 `03_local/var/artifacts/` 中的文件名和哈希读取，模板快照按 `03_local/var/templates/` 读取；复制这些目录即可保留原有文件关系。历史记录里的相对路径（`data/…`、`work/…`）由软件按前缀解析到知识根与本机根，不需要改写。已完成记录不因换电脑自动获得新的业务效力，运行中断的任务须手动重新发起。

旧 `.venv`、历史环境及已有压缩备份可随整个目录保留，但工程维护程序不会把旧 `.venv` 当作新机运行环境；macOS 会按锁文件在本机重建 `01_app/runtime/portable/` 中的环境，Windows 使用 `01_app/runtime/windows-x64/`。本次不清理既有文件，也不另做压缩包。

## 工程诊断命令

仅供维护者使用已经准备好的对应平台 Python 环境；不构成 Windows 正式发行包。

Windows：

```bat
01_app\runtime\windows-x64\python\python.exe 01_app\scripts\windows_onboard.py
01_app\runtime\windows-x64\python\python.exe 01_app\scripts\windows_onboard.py --prepare-only
01_app\runtime\windows-x64\python\python.exe 01_app\scripts\windows_onboard.py --doctor
01_app\runtime\windows-x64\python\python.exe 01_app\scripts\windows_onboard.py --port 8878
01_app\runtime\windows-x64\python\python.exe 01_app\scripts\windows_onboard.py --no-browser
```

macOS：

```sh
bash 01_app/scripts/mac_onboard.sh
bash 01_app/scripts/mac_onboard.sh --prepare-only
bash 01_app/scripts/mac_onboard.sh --doctor
bash 01_app/scripts/mac_onboard.sh --port 8878
bash 01_app/scripts/mac_onboard.sh --no-browser
```

`--prepare-only` 配置后退出；`--doctor` 检查现有环境，不启动服务或重装依赖。外层入口在 Python/uv 本身缺失时仍需先准备解释器，才能运行诊断。`--no-browser` 启动服务但不自动打开浏览器。

已有同目录服务在运行时，普通启动会打开已有页面。重新配置环境前须关闭该服务，防止替换运行中的 Pi 依赖。端口冲突时可换用 `--port`；脚本不接管其他服务。

Windows 公司策略拦截 PowerShell、macOS 系统拦截下载组件或企业网络无法访问官方源时，请按正常系统授权或 IT 流程处理。脚本不会关闭执行策略、Gatekeeper 或 TLS 校验。Windows ARM、32 位、Linux 及所有实际目标电脑的验收不在本次已验证范围。

## 回退和验证

环境安装失败不会删除事项、文稿、模板或模型设置。旧 Pi 依赖保留为 `node_modules.previous-*`，失败的本次依赖保留为 `node_modules.failed-*`；macOS Python 环境使用版本目录和本机指针。不要根据目录名字自行批量删除，先联系维护者核对。

新电脑的验收至少包括：环境检查通过、能打开页面、原事项和交付文件可读、重新授权后所选模型的短消息测试通过。业务结果和 Word 仍按原有四次人工确认处理。

本次实际执行了哪些检查、哪些尚未执行，见迁移状态记录（本机历史记录，未随源码仓库分发）。

技术依据：[uv 的 Python 管理](https://docs.astral.sh/uv/concepts/python-versions/)、[uv 安装目录控制](https://docs.astral.sh/uv/reference/environment/)、[Node.js 24.21.0 官方校验文件](https://nodejs.org/dist/v24.21.0/SHASUMS256.txt)、[Python Windows 嵌入式分发](https://docs.python.org/3/using/windows.html#the-embeddable-package)。

系统最低版本依据：[Node.js 24.21.0 支持平台](https://github.com/nodejs/node/blob/v24.21.0/BUILDING.md#platform-list)。本入口使用官方二进制，不在目标电脑编译 Node.js。

<!-- prose-quality-binding: {"core_id": "nero-chinese-prose-quality", "core_version": "0.4.0", "profile": "general", "rules_sha256": "4758913f7f778ff53e520c480a470ad4aab40112855ca97a5b905a2db6f129b3", "body_sha256": "9c2e88eb0788a348edafb6018832ebe27ff917c7153feeb64743f4624bf3c3ab", "body_scope": "text before this comment, normalized to one trailing newline", "automatic_check": {"deterministic_pass": true, "finding_count": 0}, "model_review": "Verified App entry and project-local diagnostic interpreter; no effect acceptance performed", "human_acceptance": "not_claimed"} -->
