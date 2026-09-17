# Mac 安装版

版本：0.6.1，2026-09-17。采用原生 Mac 启动器和默认浏览器，保留现有 WebUI。已完成本机安装与运行验证；当前发行包未通过 Apple Developer ID 签名和公证，不能承诺第三方 Mac 默认允许打开。

## 本次范围

软件包携带前后端源码、已构建网页、Skill、锁定 Python/Node/Pi 运行环境和本机 OCR 可执行组件。DMG 另附创业板公共知识包；初次运行复制到用户的数据目录。个人事项、会话、凭据、公司历史公告包和开发缓存不进入默认发行包。

程序规则和 Skill 随软件发布；允许用户维护的法规目录、正文、模板及其 SQLite 检索索引保存在独立知识目录。区分依据是维护责任，而不是 JSON 或 SQLite 文件格式。公共知识包包含一份可修改的初始快照，PDF 原件也位于 `.app` 外。

知识库维护继续使用现有 WebUI 和后端流程。本轮没有改写 SQLite 索引重建或磁盘压缩策略，不代表已完成增量索引改造。

`01_app` 位于 `.app/Contents/Resources`；用户数据目录内分别保存 `02_knowledge` 和 `03_local`。安装版通过明确的数据根映射沿用历史相对路径，不重写已有记录。普通源码目录继续使用既有三类布局。

## 安装与生命周期

系统要求为 macOS 13.5 或更新版本。Apple Silicon 使用 arm64 包，Intel 使用 x86_64 包。

打开 DMG 后双击应用，点击“安装并打开”。默认安装到个人 `~/Applications`，数据保存到 `~/Library/Application Support/NERO Disclosure`，不需要安装 Python、Node 或 Xcode。已有资料时，可在安装界面先选择保存 `02_knowledge`、`03_local` 的父目录，再安装并打开。

程序按锁定版本携带依赖，首次安装不运行 pip、npm 或下载解释器。初始知识库只初始化一次；更新应用不覆盖已有知识库和本机工作。启动器负责显示准备、成功、失败及停止状态，服务只监听本机回环地址。关闭启动器会有序停止由它拥有的后端进程；重复打开不会启动第二个数据写入实例。

## 验证与恢复

验收包括离线首次初始化、中文及空格路径、换目录、现有数据不覆盖、重复启动、退出清理、真实 HTTP/WebUI、知识检索及维护、Word 生成、PDF/OCR。发布构建必须使用 Release 优化，不制作开发版 App。

安装器以校验后的临时目录落地新软件，替换前保留原应用；知识库初始化失败不得覆盖已有资料。原应用回退副本保存在同一应用目录，名称含 `.previous-`。确认新版本正常后，用户可自行移除不再需要的应用副本；不要删除数据目录。

数据迁移使用完整的 `02_knowledge`、`03_local`，须在旧软件退出后复制。模型账号在新电脑重新授权。软件内置直接接入模型所需的 Pi 运行组件；模型服务本身通常需要联网和用户自己的账号。可选 OpenCodex 等外部桥接仍需其相应服务，不属于本包附送服务。

Apple Silicon 和 Intel 安装包分别通过了 12 项离线安装及实际服务检查，覆盖知识库修改、软件更新保留修改、应用换位置、重复启动、Word 回读和本机 PDF OCR。Apple Silicon 版另从只读磁盘镜像实际点击安装、打开浏览器工作台及退出。Intel 检查运行在 Apple Silicon 的 Rosetta 环境，尚未在独立 Intel Mac 上验收。

验证使用隔离的临时用户目录，没有替换开发工作区的数据或正在使用的服务，没有调用付费模型，也不等于业务结果的人工验收。逐项结果保存为发行目录中的 `VALIDATION.json`。

当前没有可用的 Apple Developer ID 证书。包内只作 ad-hoc 完整性签名，它不是 Apple 认可的开发者身份，也不是公证。第三方 Mac 可能拦截打开；此时请参阅 [Apple 安全打开应用说明](https://support.apple.com/zh-cn/102445)，不要关闭系统安全保护。未来取得账号后可签名并公证，无需改变本方案的数据布局。

## 重新构建

构建入口为 `01_app/scripts/build_macos_release.py`。分别指定 `--arch arm64` 或 `--arch x86_64`，以及匹配架构的 `--python-root`、`--site-packages`、`--node-root`、一个不存在的 `--output` 目录；加 `--dmg` 可制作并校验只读磁盘镜像。默认只作 ad-hoc 签名，有 Developer ID 后可通过 `--identity` 指定证书。脚本不上传软件或自动提交公证。

Python 运行依赖锁定在 `01_app/native/macos/requirements.lock.txt`，与开发环境依赖分开；Node/Python 基础版本沿用 `runtime/portable-runtime.lock.tsv`。构建回执记录源码和知识包哈希。不得把作者的 `.venv`、用户配置、会话或公司历史目录放入包内。

检查入口为 `01_app/scripts/validate_macos_release.py --app <应用路径> --seed <初始知识目录> --output <验证结果路径>`。它只写新建的临时测试数据，退出时回收其服务。

## 架构依据

业务问题是第三方双击即可运行且个人数据独立。复用当前 `paths.py`、知识包加载器、FastAPI/Pi 生命周期和默认浏览器；新增部分只负责安装和进程启动。

- run_identity：安装目录、用户数据根和本次进程。
- state_authority：实际进程句柄、数据根文件锁及真实监听结果。
- terminal_and_recovery_rule：准备失败保留错误；退出关闭控制管道并停止后端；未完成初始化不晋升为可用知识库。
- cross_project_isolation_evidence：安装版路径映射只覆盖实际软件根及其选定数据根，不接管其他源码工作区。
