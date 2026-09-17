# 信披智能体架构、功能与工程化审阅入口

本仓库提供 1.0 系统的软件实现、方法合同、测试和构建脚本，支持同事审查架构、全部已实现功能和工程质量。知识库、历史公告库、本机业务状态与模型凭据不随源码提供；这些资料的缺失影响业务效果验证，不影响查看对应功能实现。

请将“代码可审查”“虚构资料测试通过”“真实模型业务效果”“安装版可用”“专业与人工验收”分别判断。本次上传验收支持前两项，不能据此宣布系统达到生产交付标准。

## 建议的审阅顺序

1. 阅读本页的架构与功能表，再看 [源码导出验收](review/PUBLIC_ACCEPTANCE.md)，明确版本与资料边界。
2. 从 [应用装配](../backend/app.py)、[意图路由](../backend/intent_control.py)、[Pi 运行控制](../backend/pi_runtime.py)进入主链；对照 [HTTP 接口索引](review/API_INVENTORY.md)检查页面与后端入口。
3. 阅读 [项目方法注册表](../skills/registry.json)、[披露合同](../skills/disclosure-contract.md)及其 Skill 正文，检查模型指令与服务端约束是否一致。
4. 按根目录 README 在全新克隆运行默认测试、前端行为测试、Pi 测试和开发服务器；再针对下方未验证项安排复核。

## 1.0 来源与源码完整性

初次上传提交为 `7d992304b63903c83f452f633abc157874c58289`。维护者以本地 1.0 软件来源提交 `f4b2598b2af1a26283c4940210b3911e4fb68315` 的 397 个 `01_app` 跟踪文件进行逐文件比对：349 个字节一致、33 个经修改、15 个排除。见 [397 项对照清单](review/EXPORT_BASELINE.json)。这是初次上传的固定快照；本次公开审阅配套修改另由后续 Git 提交记录。

- `backend/` 的 98 个文件全部保留；97 个字节一致，仅共享 Word 组件的来源元数据去掉本机路径。没有用模拟后端替换真实业务实现。
- `skills/` 的 9 个文件全部保留且字节一致，含注册表、正文与引用合同。旧文件名中的 `neeq` 不代表当前开放新三板，实际范围由 `boards.py` 和知识包合同决定。
- Pi 的 worker、供应商适配、上下文管理、资源回收和锁文件均保留；模型替身只用于测试，不改变正式运行代码。
- 前端源码、品牌资源、Swift 启动器与 OCR 源码保留。入口 Logo 和迁移封装权限的 1.0 后修正以单独提交保留。
- 排除的是 7 个前端构建产物、2 份本机验收文档、4 份历史 QA 回执、1 份已安装 Windows 包清单和1个退役比较工具。运行依赖由锁文件安装，前端页面由源码构建。

原始提交属于维护者本机历史，没有上传整个原仓库。外部审查者可检查此公开仓库的提交和对照清单；若要独立核对原始 DMG 字节，需要另行取得被授权的原件。

## 架构与实际职责

入口为 React 工作台 → FastAPI 本机服务 → Python `PiRuntime` → Node `worker.mjs` → 已选择供应商。Python 持有业务对象、状态与工具权限，Node/Pi 执行模型调用及工具循环；工具结果返回服务端后核验和登记。

| 层次 | 当前职责与审查入口 | 需要关注的边界 |
| --- | --- | --- |
| 公司与界面 | [App.tsx](../frontend/src/App.tsx)、[CompanyEntrance](../frontend/src/components/CompanyEntrance.tsx)、[company_workspace.py](../backend/company_workspace.py) | 公司范围、会话切换、错误与取消；只开放创业板 |
| 意图与工具权限 | [intent_control.py](../backend/intent_control.py)、`PiRuntime.route_request/tools/bridge` | 先分流再加载能力；信披咨询不能获得知识库写权限；旧 workflow 与现行咨询/拟稿/制文并存 |
| 模型执行 | [worker.mjs](../runtime/pi/worker.mjs)、[provider_runtime.mjs](../runtime/pi/provider_runtime.mjs)、[provider_transport.test.mjs](../runtime/pi/provider_transport.test.mjs) | 显式模型选择、协议适配、异常回收；不是把全部业务放进模型提示中 |
| 方法与业务核验 | [stage_skills.py](../backend/stage_skills.py)、[candidate_contract.py](../backend/candidate_contract.py)、[gates.py](../backend/gates.py)、[gate_checks.py](../backend/gate_checks.py) | Skill 哈希、事实/法源指纹、候选与采用分离；PASS 不等于专业批准 |
| 事实与持久状态 | [storage.py](../backend/storage.py)、[chat_store.py](../backend/chat_store.py)、[document_store.py](../backend/document_store.py) | 事项版本、会话/运行/日志、文稿版本分别有自己的真源 |
| 公共证据与历史公告 | [public_store.py](../backend/public_store.py)、[library_admin.py](../backend/library_admin.py)、[announcement_history.py](../backend/announcement_history.py) | JSON 与原件为真源，SQLite 检索索引可重建；接纳状态与真实来源必须单独审查 |
| 本机安全与凭据 | [security.py](../backend/security.py)、[model_credentials.py](../backend/model_credentials.py)、[model_authorization.py](../backend/model_authorization.py) | Host/Origin/CSRF、进程内调用身份、系统凭据库；没有互联网多用户登录体系 |
| 工程与交付 | [原生代码](../native/macos)、[构建脚本](../scripts/build_macos_release.py)、[CI](../../.github/workflows/ci.yml) | 源码验证、平台打包、签名公证、用户验收分别留证 |

现行主入口有两条生产路径：咨询 → 起草前资料核对 → 公告正文/Word 版本；以及保留的结构化事项 assessment → plan → template → draft → word。正文确认、缺项接受、Word 文件登记和事项批准互不替代。审查时应同时覆盖两条路径，不能仅按旧 136 架构说明推断所有请求都经过同一套节点。

## 全功能审阅表

“测试入口”代表相关代码有回归覆盖，不代表该行全部业务情形已穷尽。以下路径均相对 `01_app/`，全部文件可在仓库检索。

| 功能 | 实现入口 | 测试入口 | 复核条件 |
| --- | --- | --- | --- |
| 公司联网识别、登记、选择 | `backend/company_lookup.py`, `company_workspace.py`; `frontend/src/components/CompanyEntrance.tsx` | `tests/test_company_workspace.py`, `frontend_company_workspace.cjs` | 真实身份核实需模型与官方来源；开发公司为虚构 |
| 会话、历史、归档、删除 | `chat_api.py`, `chat_store.py`, `session_deletion.py`, `conversation_history.py` | `test_conversation_first.py`, `test_conversation_history.py`, `test_history_search.py` | 公司/会话隔离、删除预览与执行 |
| 信披咨询、意图切换 | `intent_control.py`, `pi_runtime.py`; `skills/disclosure-consultation/` | `test_conversation_guidance.py`, `test_pi_runtime.py` | 真实回答质量需另外评测 |
| 披露义务、结构化事项 | `domain.py`, `agent_tasks.py`, `disclosure_contract.py`, `api_events.py` | `test_agent_tasks.py`, `test_disclosure_v21.py`, `test_open_intake.py` | 已编码规则是知识片段，不是完整法规系统 |
| 确认门禁与连续接续 | `gates.py`, `continuous_workflow.py`, `continuous_policy.py` | `test_gates.py`, `test_continuous_runtime.py`, `test_production_continuous_policy.py` | 测试的 legacy 模式不代表产品默认流程 |
| 公告正文、缺项处理、确认 | `announcement_runtime.py`, `document_preflight.py`, `document_context.py` | `test_consultation_announcement_flow.py`, `test_stability_recovery.py` | 接受缺口不等于认可事实或文件定稿 |
| Word 制作、改稿、版本 | `document_runtime.py`, `document_files.py`, `document_store.py`, `scripts/agent_word.py`, `scripts/word_renderer.py` | `test_document_runtime.py`, `test_word_delivery.py`, `test_document_listing.py` | 文件真实生成与版式人工验收分开 |
| 人工稿导入与锚定修改 | `document_api.py`, `document_files.py`, `document_content.py` | `test_document_runtime.py`, `test_document_listing.py` | 保护源稿、哈希与跨会话权限 |
| 会话附件与咨询导出 | `conversation_attachments.py`, `consult_export.py` | `test_conversation_attachments.py`, `test_consult_export.py` | 临时附件不自动接纳为正式知识 |
| 法规、案例、违规案例检索 | `library.py`, `library_search.py`, `public_library_index.py` | `test_library_search.py`, `test_public_library_index.py`, `test_scope_review.py` | 真实数量、原文覆盖及适用性需知识包 |
| 知识编辑、删除、导入 | `knowledge_ops.py`, `library_admin.py`, `library_write.py`, `file_ingestion.py` | `test_knowledge_capabilities.py`, `test_library_admin.py`, `test_board_knowledge.py` | 预览确认、批次校验、原子替换；不承诺跨库事务 |
| 公开检索、下载与阅读 | `public_sources.py`, `research_session.py`, `document_extract.py` | `test_research_session.py`, `test_knowledge_capabilities.py` | 官方来源限制、下载及网络异常；线上覆盖需另外测试 |
| PDF、DOCX、XLSX 与 OCR | `document_extract.py`, `vendor/nero_office/`, `native/macos/DocumentOCR.swift` | `test_conversation_attachments.py`, `test_announcement_workspace.py`, `test_windows_onboard.py` | 样例 PDF 是占位字节；真实扫描件与 OCR 效果未验收 |
| 模板与文种管理 | `template_authoring.py`, `library_workspace.py`, `stage_skills.py` | `test_stage_skills.py`, `test_knowledge_capabilities.py`, `test_word_delivery.py` | 正式模板未上传，版式依据不能由样例证明 |
| 公司历史公告、时间表 | `announcement_history.py`, `announcement_schedule.py`, `announcement_index.py`; `AnnouncementSchedule.tsx` | `test_announcement_workspace.py`, `test_announcement_tags.py`, `test_announcement_review.py` | 真实历史公告不在仓库；空目录不代表无历史义务 |
| 公告规则分类与 Pi 复判 | `announcement_tags.py`, `announcement_review.py` | `test_announcement_tags.py`, `test_announcement_review.py` | 测试不证明分类准确率或置信度 |
| 法规生命周期与批次处理 | `law_lifecycle.py`, `api_law_lifecycle.py`, `lifecycle_batches.py` | `test_law_lifecycle.py`, `test_lifecycle_run.py`, `test_system_governance.py` | 核验记录不能静默改写法规正文 |
| 模型目录、账号、授权 | `model_settings.py`, `model_credentials.py`, `model_login.py`, `gemini_broker.py`; `runtime/pi/model_control.mjs` | `test_model_settings.py`, `test_provider_lifecycle.py`, `test_gemini_broker.py`, Pi 测试 | 各供应商真实授权与连通性需各自账号 |
| 流式输出、取消、上下文续接 | `pi_runtime.py`, `pi_subprocess.py`; `runtime/pi/conversation_context.mjs`, `worker_resources.mjs` | `test_pi_native_integration.py`, `test_pi_subprocess.py`, `test_prompt_context.py`, Pi 测试 | 记录模型调用和工具结果，不能用最终文本冒充完成 |
| 故障恢复、并发与重启 | `PiRuntime.own/cancel/close`, `chat_store.py`, `service_restart.py` | `test_pi_runtime.py`, `test_service_restart.py`, `test_stability_recovery.py`, `test_stability_e2e.py` | 单机数据目录独占；不主张分布式高可用 |
| 执行证据、进展与治理 | `evidence_access.py`, `evidence_summary.py`, `runtime_health.py`, `system_governance.py`; `WorkProgress.tsx` | `test_evidence_summary.py`, `test_work_progress_receipts.py`, `test_system_governance.py`, `frontend_work_progress.tsx` | 查阅、采用、核验和交付分别计量 |
| 打包、离线依赖、迁移恢复 | `scripts/build_macos_release.py`, `build_macos_migration.py`, `migration_snapshot.py`, `macos_bundle.py`, `portable_runtime.py`, `windows_onboard.py` | `test_macos_packaging.py`, `test_migration_snapshot.py`, `test_portable_runtime.py`, `test_windows_onboard.py` | 未在本次构建安装 App；完整迁移脚本会含资料，不能直接作为公开发布任务 |

模型工具的完整授予分支位于 `PiRuntime.tools()`：auto 只获得路由工具；company_lookup、classification、lifecycle 使用各自专用工具；assessment/plan/template/draft、chat、announcement、document 按阶段扩展能力。知识维护工具由 `knowledge_ops.tools()` 提供。结构化 `workflow_operations.py` 的内部操作合同独立于 HTTP 清单。

## 数据、身份与恢复合同

| 对象 | 权威位置 | 状态与恢复边界 |
| --- | --- | --- |
| 事项与候选 | `03_local/var/disclosure.sqlite3`：events、requests、versions | 写事务 `BEGIN IMMEDIATE`、版本号、请求幂等、旧候选保留；开发数据库在 `03_local/dev/var` |
| 会话与运行 | `conversations.sqlite3`：sessions、runs、journal | run_id、session_id、event_id、board、company_code 和显式 model 绑定 |
| 活跃运行所有者 | `PiRuntime.active` 与 `pi-runtime.lock` | 本机数据目录只允许一个所有者；重启后无活跃所有者的运行记 interrupted，不自动重放 |
| 终态与交接 | `PiRuntime.work/receive`、`ChatStore` | completed、failed、cancelled、interrupted 与 waiting_user 等业务交接状态分别检查 |
| 文稿版本 | `03_local/work/documents/<session>/index.json` 与哈希文件 | 输入、模板、内容版本及审阅状态；文件保存不推进事项门禁 |
| 知识与公告 | `02_knowledge/data`、`02_knowledge/templates` | JSON、原件和提取正文保持来源关系；索引是可重建投影 |
| 模型凭据 | 系统凭据库与进程内注入 | 不进 Git；服务日志脱敏不等于已实现所有业务字段的模型出站脱敏 |

跨范围隔离的可运行证据集中在 `test_company_workspace.py`、`test_workspace_layout.py`、`test_conversation_history.py`、`test_document_runtime.py` 和 `test_pi_runtime.py`。这些是合成数据与模拟供应商检查，不能替代多用户生产环境隔离评估。

## 工程化成熟度：可复核结论与缺口

本系统具备明确的本机状态、版本、工具权限和失败恢复设计，有大量可复现的自动测试。当前更适合定位为**可审查、可继续开发的本机工作台**。不计算综合成熟度分数，避免用测试数量抵消平台与真实业务验证的缺口。

| 方面 | 当前证据 | 尚未证明／同事应重点审查 |
| --- | --- | --- |
| 架构与功能可见性 | 后端、前端、Pi、Skill、原生源码完整；功能与接口索引已提供 | 复杂运行器与旧工作流的职责边界；`pi_runtime.py` 承担多种意图与生命周期职责 |
| 可重复验证 | 默认测试、Pi 测试、前端行为测试与构建；CI 记录绑定提交 | 没有测试覆盖率阈值，数量不能代表所有分支、竞态或长期运行都覆盖 |
| 启动与持久化 | 独立开发入口、重启保留修改、外部知识包测试写保护 | `--data-dir` 只移动数据库等配置，不移动全部 work/output 路径；应使用独立克隆 |
| 业务证据与结论 | 法源指纹、候选/采用分离、文稿版本与核验代码齐备 | 真实知识包质量、法源更新覆盖、案例适用性及生成内容质量未验收 |
| 安全与权限 | 本机 Host/Origin/CSRF、进程内身份、路径与凭据相关测试 | 无多用户鉴权/RBAC；不能把公开源码理解为可直接部署互联网服务；本次不是完整安全审计 |
| 模型与成本 | 供应商适配、取消、错误处理、无静默模型替换 | 真实供应商评测、延迟/费用基线、配额预算与长任务资源上限证据不足 |
| 依赖与构建 | Python/npm 锁文件、来源记录与构建源码 | Python 锁文件未使用逐包哈希；未形成完整 SBOM/漏洞扫描基线；CI Actions 仍有 Node 20 弃用提示 |
| 发布与平台 | macOS/Windows 相关源码及模拟测试 | 当前 CI 后端在 macOS 运行，未验证 Windows 原生和 Intel Mac 实机；未做签名公证、安装回归与发布流水线验收 |
| 运维与协作 | 日志、健康扫描、恢复工具、PR 模板与 CI | 分支保护未启用；公开贡献的 GitHub 权限不等于产品内多人协作权限；没有生产 SLA 与灾备演练证据 |

建议审查者将问题按“数据/权限正确性”“功能可靠性”“可维护性与性能”记录为 Issue。真实库、真实供应商及安装环境的结论须列出对应材料和运行条件；没有证据时记录未验证，不把默认样例测试改成替代验收。
