# 包边界：软件、知识与本机资料

本文件固定 NERO 信息披露 AI 系统的三个交付边界及各自的可重建内容。`.gitignore` 与 `scripts/generate_manifest.py` 以本文件为准。

本源码仓库只包含 `01_app` 软件包，并附带 `tests/fixtures/knowledge` 虚构样例供开发与默认测试使用；`02_knowledge` 与 `03_local` 始终由使用者在本机提供，详见根目录 [README](../../README.md) 与 [贡献指南](../../CONTRIBUTING.md)。

下文的登记范围描述发行软件与资料布局，不是 Git 上传清单。公开仓库不跟踪 `frontend/dist/`、运行依赖、生成清单或任何正式知识模板。实际上传范围与例外以[公开源码验收](review/PUBLIC_ACCEPTANCE.md)、[来源对照](review/EXPORT_BASELINE.json)及根目录 `.gitignore` 为准。

## 01_app 软件包

登记范围：`01_app/backend/`、`01_app/scripts/`、`01_app/skills/`、`01_app/tests/`、`01_app/docs/`、`01_app/config/pi-models.example.json`、`01_app/frontend/src/`、`01_app/frontend/dist/`、`01_app/requirements*.txt`、`01_app/pytest.ini`、`01_app/BUILD_MANIFEST.json`，`01_app/native/` 的原生启动器源码，以及根目录导航和工具元数据（`README.md`、`AGENTS.md`、`.gitignore`）。根目录旧启动脚本已退役，日常使用正式 App。

- 源码、方法、锁文件及维护说明进入版本基线，可离线比对与回退。生成的发布清单保留在工作区。
- `01_app/frontend/dist/` 是实际提供服务的页面包，属软件包；App 启动的本机服务直接使用它，新用户不需要编译前端。
- 模型凭据不在软件包内：非敏感模型配置存于 `03_local/var/pi-models.json`，密钥保存于系统凭据库。
- 路径解析集中在 `01_app/backend/paths.py`：软件根、知识根、本机根分别解析，历史记录中的相对路径按前缀映射（`data/`、`templates/` → 知识根；`work/`、`var/`、`output/`、`design-output/`、`cache/` → 本机根；其余 → 软件根）。旧式单根目录继续兼容。

## 运行包（`01_app/runtime/`）

登记范围：`01_app/runtime/portable/`（项目内 uv、Python、Node.js 与锁定安装介质）、`01_app/runtime/pi/`（Pi 工作进程与运行依赖）、`01_app/runtime/windows-x64/`（Windows 目标平台解释器与依赖）。发行副本按目标平台选取运行依赖；前端的 `node_modules/` 仅用于开发构建，不是网页运行的依赖。

- 工程维护程序按锁定文件校验 SHA-256 后准备运行依赖，正式 App 的运行入口另见安装说明：`01_app/runtime/portable-runtime.lock.tsv`、`01_app/requirements.lock.txt`、`01_app/runtime/pi/package-lock.json`、`01_app/runtime/windows-x64/runtime.lock.json`。
- 可重建的包管理缓存位于 `03_local/cache/portable/<平台>/`，旧依赖和环境指针保存在本机历史区。缓存删除后，重新准备环境可能需要联网。
- Windows 的 `downloads/python.zip`、`downloads/uv.zip` 仍参与 bundle 校验；macOS 的锁定安装介质支持环境准备，本次保留，均不列作普通缓存清理。
- 保留：当前平台已解压的 `envs/`、`runtime/pi/node_modules/`、`runtime/windows-x64/packages/`。
- 运行器源码、来源记录与锁文件进入版本基线；安装后的解释器、依赖与介质按平台复制，不作为源码提交。

## 02_knowledge 知识包

登记范围：`02_knowledge/data/` 与 `02_knowledge/templates/`；包身份、版本、路径、校验与依赖清单见 `02_knowledge/packages/`。

- `data/`：板块登记清单（`catalog.json`、`profiles.json`、`instruments.json`、`rules.json`、`scenarios.json`）、官方原件与页级提取正文、公司公告原件与提取正文、模板与版式依据、SQLite 检索投影。
- `templates/`：文种与版式模板、版式依据与导入模板。
- 可重建：`data/public/boards/<board>/disclosure_library.sqlite3`、`data/client_announcements/<board>/<code>/announcement_history.sqlite3`。删除后检索降级为读取 JSON 真源，重建入口为 `01_app/scripts/sync_sqlite_library.py` 与 `01_app/scripts/sync_announcement_history_index.py`。
- 不可重建：官方原件、页级提取正文、公司公告原件与正文、来源回执。
- 大体积知识数据不进入代码版本基线；原已纳入版本控制的模板继续保留版本历史。按包复制前后核对包清单；加载时检查版本、依赖和软件能力，完整哈希通过 `refresh_knowledge_packages.py --verify` 核对。

## 03_local 本机资料

登记范围：`03_local/var/`（事项与版本库 `disclosure.sqlite3`、会话与执行记录 `conversations.sqlite3`、交付物 `artifacts/`、模板快照、`pi-models.json`、治理预览与历史、备份与归档）、`03_local/work/`、`03_local/output/`、`03_local/design-output/`、`03_local/records/`、`03_local/.venv/`、`03_local/cache/`。

- `var/disclosure.sqlite3` 与 `var/conversations.sqlite3` 不可重建；`var/backups/`、`var/archives/` 为历史回退点，按现有清理流程单独管理。
- 不进入默认软件包或知识包；新环境延续历史业务时必须显式迁移本目录，并按 `03_local/README.md` 核对业务状态。
- 本机开发环境 `.venv/` 可重建；模型密钥不在此目录，仍在系统凭据库。

## 迁移与恢复

三类目录及根目录入口一起复制，可保持事项、会话、交付物与资料关系。只复制软件和所选知识包会创建空的事项库与会话库；软件本身不能代替知识数据。缺少当前平台运行包时，入口按锁定文件准备环境。

## 发布清单

`scripts/generate_manifest.py` 默认登记 `01_app/` 内的软件源码与运行器（`--scope source`）。`--scope full` 以工作区为路径基准扩展扫描，仍按排除清单跳过 `var/`、`node_modules/`、`.venv/` 等内容，不能用作业务备份。清单默认写到 `01_app/BUILD_MANIFEST.json`，`scripts/verify_release.py` 按清单核对副本；根目录入口及历史迁移的逐文件对照另存迁移审计清单。
