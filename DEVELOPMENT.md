# 开发文档

环境安装与使用步骤见 [README](README.md)。本文说明源码结构、状态与接口，以及开发和测试方式。本项目禁止商用，详见 [LICENSE](LICENSE)。

## 架构

```text
React 工作台 → FastAPI 本机服务 → Python PiRuntime → Node/Pi worker → 模型服务
                                    ↑                    │
                                    └──── 服务端工具 ────┘
```

[app.py](01_app/backend/app.py)装配接口和共享上下文。[PiRuntime](01_app/backend/pi_runtime.py)绑定会话、模型、运行所有者和工具权限；[worker.mjs](01_app/runtime/pi/worker.mjs)执行 Pi SDK 调用、工具循环和进程消息交换。

| 职责 | 主要实现（相对 `01_app/`） |
| --- | --- |
| 界面与公司 | `frontend/src/App.tsx`、`backend/company_workspace.py`、`company_lookup.py` |
| 意图与工具 | `backend/intent_control.py`、`PiRuntime.tools/route_request/bridge` |
| 模型和凭据 | `backend/model_settings.py`、`model_credentials.py`、`runtime/pi/provider_runtime.mjs` |
| 结构化事项 | `backend/agent_tasks.py`、`disclosure_contract.py`、`gates.py`、`continuous_workflow.py` |
| 公告与 Word | `backend/announcement_runtime.py`、`document_preflight.py`、`document_runtime.py` |
| 资料管理 | `backend/library.py`、`library_admin.py`、`knowledge_ops.py`、`announcement_history.py` |
| 持久化与追踪 | `backend/storage.py`、`chat_store.py`、`document_store.py`、`evidence_summary.py` |

模型方法及引用哈希登记在 [skills/registry.json](01_app/skills/registry.json)。运行范围由 `backend/boards.py` 和知识包合同决定，旧方法文件名中的 `neeq` 不代表当前开放新三板。

## 数据与状态

路径使用 [backend/paths.py](01_app/backend/paths.py)解析：`data/`、`templates/` 属于知识根，`var/`、`work/`、`output/` 属于本机根。`--data-dir` 只改变部分存储位置，不能代替独立克隆。

| 对象 | 持久化位置与规则 |
| --- | --- |
| 事项 | `disclosure.sqlite3` 的 events、requests、versions；写事务、版本检查和请求幂等 |
| 会话与运行 | `conversations.sqlite3` 的 sessions、runs、journal；绑定会话、事项、公司、板块和模型 |
| 文稿 | `03_local/work/documents/<session>/index.json` 及哈希文件；保存新版本，不直接覆盖旧稿 |
| 知识与公告 | `02_knowledge/data/`、`templates/`；JSON、原件与提取正文为资料真源 |
| 检索索引 | 知识库与公告目录中的 SQLite；可重建，过期时可能退回 JSON 查询 |

同一数据目录通过运行锁防止重复占用。取消停止本轮执行；重启后没有活跃所有者的未完成运行标为中断，不自动重放模型调用或生产操作。保留已登记文件和历史版本。

## 文稿状态

当前会话按需求进入咨询、公告、Word 或知识维护；同时保留 `assessment → plan → template → draft → word` 的结构化事项路径。候选提交与采用分离，输入、法源、模板或方法变化会使相应旧结果失效。

起草前调用 `assess_document_readiness`，登记文稿范围、核对主题与缺口。缺口分为 `content`、`evidence`、`review`、`publication`；只有内容缺失或冲突按资料缺口处理，来源定位错误交回工具修正。仅 `ready` 或 `authorized` 且输入指纹匹配时开放保存工具。

未告知的内容缺口通常进入 `waiting_user`。本轮明确要求留空或标注待补时，以 `draft_with_placeholders` 登记原话；接受既有提醒时须绑定同一会话、文稿、提醒编号和本轮消息。接受缺口不等于正文确认；换文稿、新增缺口、事实冲突或取消都不能沿用不适用的选择。

正文必须包含已接受缺口的具体占位。Word 生成后回读并校验哈希，同批文件成功后才登记；文件保存不推进事项确认。修改已登记的公告 Word 使用段落锚点，无法定位时返回错误。新人工稿回传接口已停用，历史版本仍可读取。

失败续接只复用实际登记且仍匹配的状态；模型文字不能当作用户选择或文件完成凭据。内部纠偏消息不作为用户追加指令。

## 接口

HTTP 接口装配在 `backend/app.py:create_app`，本机浏览器写入需要有效会话、同源 Origin 与 CSRF。该服务没有互联网多用户登录体系，不应直接暴露到公网。

Pi 进程内操作见 [workflow_operations.py](01_app/backend/workflow_operations.py)。模型工具按意图和阶段授予：初始只开放路由工具，公司核实和分类使用专用工具，起草工具在资料核对后开放。外部资料不授予操作权限。

完整 HTTP 声明见本文末尾的可展开列表；包含返回 410 的退役接口及条件挂载接口，具体可用性以处理函数为准。

## 开发与测试

下列命令从仓库根目录执行。修改前端后重新构建 `dist/`，修改后端后重启开发服务器；不将构建产物提交 Git。

```sh
(cd 01_app/frontend && npm run build)
.venv/bin/python 01_app/scripts/dev_server.py --port 8765
```

```sh
(cd 01_app && ../.venv/bin/python -m pytest -q)
(cd 01_app/frontend && npm test && npm run typecheck && npm run build)
(cd 01_app/runtime/pi && npm test)
python3 01_app/scripts/check_source_boundary.py
python3 01_app/scripts/generate_api_docs.py --check
```

默认测试使用虚构样例和模拟供应商，部分用例需要回环端口。`knowledge_pack` 测试另需经授权的知识包，其数量断言与资料快照有关：

```sh
(cd 01_app && NERO_DISCLOSURE_KNOWLEDGE_ROOT=/path/to/02_knowledge \
  ../.venv/bin/python -m pytest -q -m knowledge_pack)
```

模型连通性、真实资料质量、生成内容和实际 Word 版式需另行核对，不能由样例测试代替。

## 参与协作

从 `main` 创建功能分支，通过 Pull Request 提交修改，说明问题、行为变化与实际验证。保持既有数据、权限和确认边界；新增依赖或数据库变更应说明兼容性及恢复方式。

接口声明变化后运行 `python3 01_app/scripts/generate_api_docs.py`，只更新下方自动生成区域。知识库、真实公告、客户资料、数据库、密钥、日志及安装依赖不得提交；新增样例必须是虚构内容。

## HTTP 声明列表

<details>
<summary>展开方法、路径和实现位置</summary>

<!-- API-REFERENCE:START -->
共 120 个 HTTP 方法与路径声明。

| 方法 | 路径 | 实现与行号 | 处理函数 |
| --- | --- | --- | --- |
| GET | `/api/events` | [api_events.py:37](01_app/backend/api_events.py#L37) | `events` |
| POST | `/api/events` | [api_events.py:48](01_app/backend/api_events.py#L48) | `event_create` |
| GET | `/api/events/{event_id}` | [api_events.py:54](01_app/backend/api_events.py#L54) | `event_get` |
| PATCH | `/api/events/{event_id}` | [api_events.py:61](01_app/backend/api_events.py#L61) | `event_edit` |
| POST | `/api/events/{event_id}/assess` | [api_events.py:76](01_app/backend/api_events.py#L76) | `assess` |
| PATCH | `/api/events/{event_id}/draft` | [api_events.py:89](01_app/backend/api_events.py#L89) | `retired_production` |
| PATCH | `/api/events/{event_id}/plan` | [api_events.py:89](01_app/backend/api_events.py#L89) | `retired_production` |
| POST | `/api/events/{event_id}/approve` | [api_events.py:89](01_app/backend/api_events.py#L89) | `retired_production` |
| POST | `/api/events/{event_id}/draft` | [api_events.py:89](01_app/backend/api_events.py#L89) | `retired_production` |
| POST | `/api/events/{event_id}/plan` | [api_events.py:89](01_app/backend/api_events.py#L89) | `retired_production` |
| POST | `/api/events/{event_id}/word/prepare` | [api_events.py:89](01_app/backend/api_events.py#L89) | `retired_production` |
| POST | `/api/events/{event_id}/word/review` | [api_events.py:89](01_app/backend/api_events.py#L89) | `retired_production` |
| GET | `/api/events/{event_id}/verify` | [api_gates.py:29](01_app/backend/api_gates.py#L29) | `verify_event` |
| POST | `/api/events/{event_id}/advance` | [api_gates.py:98](01_app/backend/api_gates.py#L98) | `advance_event` |
| POST | `/api/events/{event_id}/confirmations` | [api_gates.py:102](01_app/backend/api_gates.py#L102) | `human_confirmation` |
| POST | `/api/events/{event_id}/drafting-supplements` | [api_gates.py:109](01_app/backend/api_gates.py#L109) | `drafting_supplement` |
| POST | `/api/events/{event_id}/reopen` | [api_gates.py:113](01_app/backend/api_gates.py#L113) | `reopen_event` |
| POST | `/api/events/{event_id}/law-bindings` | [api_gates.py:117](01_app/backend/api_gates.py#L117) | `law_bindings` |
| POST | `/api/events/{event_id}/source-search` | [api_gates.py:121](01_app/backend/api_gates.py#L121) | `source_search` |
| GET | `/api/events/{event_id}/word/context` | [api_gates.py:125](01_app/backend/api_gates.py#L125) | `word_context` |
| POST | `/api/events/{event_id}/artifacts` | [api_gates.py:143](01_app/backend/api_gates.py#L143) | `artifact_upload` |
| GET | `/api/events/{event_id}/artifacts/{artifact_id}/file` | [api_gates.py:147](01_app/backend/api_gates.py#L147) | `artifact_file` |
| GET | `/api/law-lifecycle` | [api_law_lifecycle.py:12](01_app/backend/api_law_lifecycle.py#L12) | `law_lifecycle_state` |
| POST | `/api/law-lifecycle/check` | [api_law_lifecycle.py:32](01_app/backend/api_law_lifecycle.py#L32) | `law_lifecycle_check` |
| POST | `/api/law-lifecycle/run` | [api_law_lifecycle.py:39](01_app/backend/api_law_lifecycle.py#L39) | `law_lifecycle_run` |
| GET | `/api/templates` | [api_library.py:24](01_app/backend/api_library.py#L24) | `templates` |
| GET | `/api/knowledge` | [api_library.py:29](01_app/backend/api_library.py#L29) | `knowledge` |
| GET | `/api/library/search` | [api_library.py:36](01_app/backend/api_library.py#L36) | `search` |
| GET | `/api/library/items/{item_id}` | [api_library.py:44](01_app/backend/api_library.py#L44) | `item` |
| GET | `/api/library/assets/{item_id}` | [api_library.py:50](01_app/backend/api_library.py#L50) | `library_asset` |
| GET | `/api/library/items/{item_id}/evidence/{document_id}` | [api_library.py:56](01_app/backend/api_library.py#L56) | `library_evidence_asset` |
| GET | `/api/scenarios` | [api_library_admin.py:18](01_app/backend/api_library_admin.py#L18) | `scenarios` |
| POST | `/api/scenarios/{scenario_id}/import` | [api_library_admin.py:23](01_app/backend/api_library_admin.py#L23) | `import_scenario` |
| GET | `/api/library/{collection}/manage` | [api_library_admin.py:32](01_app/backend/api_library_admin.py#L32) | `library_manage` |
| POST | `/api/library/{collection}/update` | [api_library_admin.py:39](01_app/backend/api_library_admin.py#L39) | `library_update` |
| POST | `/api/events/{event_id}/agent-tasks/{task_id}/finish` | [api_tasks.py:130](01_app/backend/api_tasks.py#L130) | `task_finish` |
| POST | `/api/events/{event_id}/agent-tasks/{task_id}/adopt` | [api_tasks.py:134](01_app/backend/api_tasks.py#L134) | `task_adopt` |
| GET | `/api/meta` | [app.py:122](01_app/backend/app.py#L122) | `meta` |
| GET | `/api/session` | [app.py:129](01_app/backend/app.py#L129) | `session` |
| DELETE | `/api/session` | [app.py:137](01_app/backend/app.py#L137) | `removed_login` |
| POST | `/api/session` | [app.py:137](01_app/backend/app.py#L137) | `removed_login` |
| GET | `/api/chat/models` | [chat_api.py:51](01_app/backend/chat_api.py#L51) | `models` |
| GET | `/api/model-settings` | [chat_api.py:65](01_app/backend/chat_api.py#L65) | `model_settings` |
| PUT | `/api/model-settings` | [chat_api.py:69](01_app/backend/chat_api.py#L69) | `save_model_settings` |
| GET | `/api/model-settings/catalog` | [chat_api.py:75](01_app/backend/chat_api.py#L75) | `model_catalog` |
| POST | `/api/model-settings/catalog/refresh` | [chat_api.py:79](01_app/backend/chat_api.py#L79) | `refresh_model_catalog` |
| POST | `/api/model-settings/gemini/connect` | [chat_api.py:83](01_app/backend/chat_api.py#L83) | `connect_gemini` |
| POST | `/api/model-settings/{key}/credential` | [chat_api.py:89](01_app/backend/chat_api.py#L89) | `save_model_credential` |
| DELETE | `/api/model-settings/{key}/credential` | [chat_api.py:94](01_app/backend/chat_api.py#L94) | `remove_model_credential` |
| POST | `/api/model-settings/providers/{provider}/sync` | [chat_api.py:98](01_app/backend/chat_api.py#L98) | `sync_provider_models` |
| POST | `/api/model-settings/{key}/login` | [chat_api.py:107](01_app/backend/chat_api.py#L107) | `model_login` |
| POST | `/api/model-settings/providers/{provider}/login` | [chat_api.py:111](01_app/backend/chat_api.py#L111) | `provider_login` |
| GET | `/api/model-settings/login/{identity}` | [chat_api.py:115](01_app/backend/chat_api.py#L115) | `model_login_status` |
| DELETE | `/api/model-settings/login/{identity}` | [chat_api.py:119](01_app/backend/chat_api.py#L119) | `model_login_cancel` |
| POST | `/api/model-settings/login/{identity}/answer` | [chat_api.py:123](01_app/backend/chat_api.py#L123) | `answer_model_login` |
| POST | `/api/model-settings/{key}/test` | [chat_api.py:128](01_app/backend/chat_api.py#L128) | `test_model` |
| GET | `/api/chat/sessions` | [chat_api.py:132](01_app/backend/chat_api.py#L132) | `sessions` |
| POST | `/api/chat/sessions` | [chat_api.py:142](01_app/backend/chat_api.py#L142) | `create` |
| PATCH | `/api/chat/sessions/{sid}` | [chat_api.py:154](01_app/backend/chat_api.py#L154) | `edit` |
| GET | `/api/chat/sessions/{sid}` | [chat_api.py:158](01_app/backend/chat_api.py#L158) | `detail` |
| POST | `/api/chat/sessions/{sid}/runs` | [chat_api.py:165](01_app/backend/chat_api.py#L165) | `send` |
| GET | `/api/chat/runs` | [chat_api.py:171](01_app/backend/chat_api.py#L171) | `runs` |
| GET | `/api/chat/runs/{rid}` | [chat_api.py:181](01_app/backend/chat_api.py#L181) | `run` |
| POST | `/api/chat/runs/{rid}/cancel` | [chat_api.py:185](01_app/backend/chat_api.py#L185) | `cancel` |
| POST | `/api/chat/runs/{rid}/messages` | [chat_api.py:189](01_app/backend/chat_api.py#L189) | `continue_message` |
| GET | `/api/chat/runs/{rid}/stream` | [chat_api.py:195](01_app/backend/chat_api.py#L195) | `stream` |
| GET | `/api/chat/sessions/{sid}/deletion-preview` | [chat_api.py:214](01_app/backend/chat_api.py#L214) | `deletion_preview` |
| DELETE | `/api/chat/sessions/{sid}` | [chat_api.py:220](01_app/backend/chat_api.py#L220) | `delete_session` |
| POST | `/api/chat/runs/{rid}/knowledge-confirmation` | [chat_api.py:227](01_app/backend/chat_api.py#L227) | `knowledge_confirmation` |
| GET | `/api/chat/runs/{rid}/source-candidate` | [chat_api.py:234](01_app/backend/chat_api.py#L234) | `source_candidate` |
| GET | `/api/chat/runs/{rid}/template-candidate` | [chat_api.py:245](01_app/backend/chat_api.py#L245) | `template_candidate` |
| GET | `/api/chat/sessions/{sid}/exports` | [chat_api.py:258](01_app/backend/chat_api.py#L258) | `session_exports` |
| POST | `/api/chat/sessions/{sid}/exports` | [chat_api.py:264](01_app/backend/chat_api.py#L264) | `create_session_export` |
| GET | `/api/chat/sessions/{sid}/exports/{export_id}/file` | [chat_api.py:270](01_app/backend/chat_api.py#L270) | `session_export_file` |
| GET | `/api/company-workspace` | [company_workspace.py:122](01_app/backend/company_workspace.py#L122) | `workspace` |
| POST | `/api/company-workspace/select` | [company_workspace.py:127](01_app/backend/company_workspace.py#L127) | `choose` |
| POST | `/api/company-workspace/lookup` | [company_workspace.py:132](01_app/backend/company_workspace.py#L132) | `lookup` |
| POST | `/api/company-workspace/register` | [company_workspace.py:137](01_app/backend/company_workspace.py#L137) | `registration` |
| POST | `/api/chat/sessions/{sid}/attachments` | [document_api.py:24](01_app/backend/document_api.py#L24) | `upload_attachment` |
| GET | `/api/documents` | [document_api.py:31](01_app/backend/document_api.py#L31) | `company_documents` |
| GET | `/api/chat/sessions/{sid}/documents` | [document_api.py:57](01_app/backend/document_api.py#L57) | `documents` |
| GET | `/api/chat/sessions/{sid}/documents/{document_id}/versions/{number}/file` | [document_api.py:62](01_app/backend/document_api.py#L62) | `download` |
| GET | `/api/chat/sessions/{sid}/documents/{document_id}/versions/{number}/preview` | [document_api.py:68](01_app/backend/document_api.py#L68) | `preview` |
| POST | `/api/chat/sessions/{sid}/documents/{document_id}/open` | [document_api.py:79](01_app/backend/document_api.py#L79) | `open_working_copy` |
| POST | `/api/chat/sessions/{sid}/documents/{document_id}/review` | [document_api.py:84](01_app/backend/document_api.py#L84) | `review` |
| POST | `/api/chat/sessions/{sid}/documents/import` | [document_api.py:90](01_app/backend/document_api.py#L90) | `import_source` |
| GET | `/api/chat/evidence-sessions` | [evidence_api.py:20](01_app/backend/evidence_api.py#L20) | `sessions` |
| GET | `/api/chat/sessions/{sid}/evidence` | [evidence_api.py:33](01_app/backend/evidence_api.py#L33) | `summary` |
| POST | `/api/governance/scan` | [governance_api.py:39](01_app/backend/governance_api.py#L39) | `scan` |
| POST | `/api/governance/cleanup-preview` | [governance_api.py:44](01_app/backend/governance_api.py#L44) | `preview` |
| POST | `/api/governance/cleanup` | [governance_api.py:49](01_app/backend/governance_api.py#L49) | `cleanup` |
| POST | `/api/governance/cleanup/restore` | [governance_api.py:55](01_app/backend/governance_api.py#L55) | `cleanup_restore` |
| POST | `/api/governance/cleanup/purge` | [governance_api.py:61](01_app/backend/governance_api.py#L61) | `cleanup_purge` |
| POST | `/api/governance/laws/runs` | [governance_api.py:67](01_app/backend/governance_api.py#L67) | `start` |
| GET | `/api/governance/laws/current` | [governance_api.py:71](01_app/backend/governance_api.py#L71) | `current` |
| GET | `/api/governance/laws/runs/{identity}` | [governance_api.py:76](01_app/backend/governance_api.py#L76) | `read` |
| POST | `/api/governance/laws/runs/{identity}/cancel` | [governance_api.py:79](01_app/backend/governance_api.py#L79) | `stop` |
| POST | `/api/governance/health/scan` | [governance_api.py:82](01_app/backend/governance_api.py#L82) | `health_scan` |
| GET | `/api/governance/health` | [governance_api.py:86](01_app/backend/governance_api.py#L86) | `health_read` |
| POST | `/api/governance/version/scan` | [governance_api.py:89](01_app/backend/governance_api.py#L89) | `version_scan` |
| GET | `/api/governance/version` | [governance_api.py:92](01_app/backend/governance_api.py#L92) | `version_read` |
| POST | `/api/governance/version/verify` | [governance_api.py:95](01_app/backend/governance_api.py#L95) | `version_verify` |
| GET | `/api/governance/version/verify` | [governance_api.py:99](01_app/backend/governance_api.py#L99) | `version_verify_state` |
| POST | `/api/governance/version/verify/cancel` | [governance_api.py:102](01_app/backend/governance_api.py#L102) | `version_verify_cancel` |
| GET | `/api/announcement-schedule` | [library_workspace.py:45](01_app/backend/library_workspace.py#L45) | `schedule` |
| POST | `/api/announcement-schedule/review` | [library_workspace.py:53](01_app/backend/library_workspace.py#L53) | `review_announcements` |
| GET | `/api/announcements/{identity}` | [library_workspace.py:64](01_app/backend/library_workspace.py#L64) | `announcement` |
| GET | `/api/announcements/{identity}/original` | [library_workspace.py:68](01_app/backend/library_workspace.py#L68) | `announcement_original` |
| PATCH | `/api/announcement-schedule` | [library_workspace.py:73](01_app/backend/library_workspace.py#L73) | `correct_schedule` |
| POST | `/api/announcement-schedule/coverage` | [library_workspace.py:93](01_app/backend/library_workspace.py#L93) | `coverage` |
| POST | `/api/announcement-schedule/restore` | [library_workspace.py:103](01_app/backend/library_workspace.py#L103) | `restore` |
| POST | `/api/library/imports` | [library_workspace.py:112](01_app/backend/library_workspace.py#L112) | `upload` |
| GET | `/api/library/imports/{identity}` | [library_workspace.py:123](01_app/backend/library_workspace.py#L123) | `import_detail` |
| GET | `/api/library/imports/{identity}/original` | [library_workspace.py:127](01_app/backend/library_workspace.py#L127) | `import_original` |
| POST | `/api/library/imports/{identity}/commit` | [library_workspace.py:132](01_app/backend/library_workspace.py#L132) | `commit` |
| POST | `/api/library/deletion-preview` | [library_workspace.py:141](01_app/backend/library_workspace.py#L141) | `preview_delete` |
| POST | `/api/library/delete` | [library_workspace.py:146](01_app/backend/library_workspace.py#L146) | `delete_library` |
| POST | `/api/library/template-replacement` | [library_workspace.py:150](01_app/backend/library_workspace.py#L150) | `replace` |
| POST | `/api/library/template-upload` | [library_workspace.py:155](01_app/backend/library_workspace.py#L155) | `add_template` |
| GET | `/api/library/template-file/{profile_id}` | [library_workspace.py:160](01_app/backend/library_workspace.py#L160) | `template_file` |
<!-- API-REFERENCE:END -->

</details>
