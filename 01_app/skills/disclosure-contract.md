# A/B 共享运行合同（2.6.1）

本文件与方法正文一同由项目注册表校验并随 Pi 节点任务加载。外部 Agent 接入、HTTP 接入桥和连接令牌已移除；下列 task/library/verify 操作是进程内工作流操作，不是对外接口。字段的精确类型及必需项以 `backend/agent_models.py` 和 `task.context.result_schema` 为准；不要求用户填写 JSON。

## 按需制文主路径

用户要求制作或修改 Word（包括公告）时，Pi 选择 `disclosure/document`，在同一 runtime 中整理当前会话、事项事实和系统内当前文稿，选择模板并调用 `make_word`。可从任意阶段进入，不以 A/B/T/draft 全部核验或全文预先人工确认为制文前提。普通缺口明确待补，关键事实矛盾只询问必要信息；不得虚构事实、审批、法源或第三方意见，也不擅自改变用户要求的文种。

正文、模板和输入版本由 runtime 自动保存快照；文件及版本登记于会话文档，不调用 `gate.advance` 或改写事项阶段。最终文件由用户集中审阅；确认绑定该文件版本与哈希，且不代表公司决策程序完成或已发布。会话对外输出 Word，系统外修改无需回传，也不会自动接回。系统内后续修订基于已登记版本，保留旧文件；历史人工稿继续按原有锚点保护。

以下节点合同用于事项分析和已有流程的兼容，不构成按需制文的前置节点。旧确认记录保持原有含义；单条回复导出已停止生成，仅保留历史文件读取。

| 业务输入或动作 | 实际接口与边界 |
| --- | --- |
| 范围与身份 | 新事项提交真实 `company_name`、可选 `stock_code` 和已选 `board`；服务端冻结主体、板块及事项身份。`kind` 可为空分类提示，不是事项白名单。旧模拟主体编号仅保留兼容。输入身份不证明企业授权已核实，未接通板块的知识能力仍须如实报告。 |
| 自然语言与事实 | `event.create`／`event.update` 的 `summary`、`facts`。A 的 `facts` 区分 user_statement、material_supported、model_inference、unknown、conflicting，列 source_ref、quote、observed_at。模型整理不得声称人工已确认。 |
| 判断基准 | 读取 `task.context.assessment_as_of` 并原样返回；服务端核对任务基准日与引用法规的生效、失效及核验截止时间，模型不得改日期绕过检查。过去行为用历史基准；当前新增义务须另列事项分析。 |
| 实际检索 | `task.library.search`：event_id、task_id、collection、query、offset、limit；`task.library.read`：event_id、task_id、item_id、page。服务器检查当前领取凭证，自动从事项绑定板块；不接受 board/client_ref 覆写。 |
| 完整规则与规范格式 | `task.context.sources` 和 `profiles` 提供已取出的真实文本及格式要求，补充阅读用 task.library.read。sources 保留原有时间、定位、版本、哈希及替代关系；没有的元数据为未知。 |
| 客户历史、附件 | `client_history` 按本轮公司查询历史公告及公告时间表，返回覆盖范围、版本及原文定位；未登记公司返回 not_connected。`client_materials` 仍未接通。不得用其他公司案例顶替本公司历史。 |
| 法源修正 | 保留现有 `library.manage/update`、`law.bind`、`source.search_report`；管理接口是本机工作区权限，不能冒充多租户客户授权。来源收录不等于专业适用性确认。 |
| 节点加载 | `task.request(stage=assessment/plan/template/draft)` → `task.open` → `task.submit` → `task.adopt`。由 stage_skills.get 校验并加载对应方法和共享合同；不安装到宿主全局。 |
| 自动校验 | `verify.run` 只返回当前报告；`gate.advance` 记录确定性检查，按当前策略推进工作稿或进入必需的人工确认。阻断、警告、未知项及专业复核项分别返回。 |
| 人工确认 | 仅浏览器 `POST /api/events/{id}/confirmations`，continuous-v1 的固定节点为 stage=draft（完整正文）及 stage=word（文件验收）；assessment 仅保留例外决定。不能代签。绑定 input_fingerprint、reviewer、reason、decision；Pi 进程内工具不可调用。仅证明本机产品内确认，不核验身份或替代法定审批。 |
| 补制稿资料 | `drafting.supplement` 只接纳 B 已明确列为 draft/supply 的键；不得覆盖 A 事实或一般事实键，其他变化回 A/B。保留提供内容及来源说明，不能标成材料已核实。 |
| 最小回退 | `workflow.reopen` 指定 assessment／plan／template／draft 并说明原因；只使相应节点和下游确认失效。达到自动修复上限后只能由浏览器人工恢复，Agent 不可重置计数。 |
| Word | draft 自动检查并取得当前版本人工正文确认后 `word.context` → 既有 `scripts/agent_word.py` → `artifact.register`。真实 DOCX、哈希、正文、表格和基本格式检查由 artifacts 执行；宿主复核说明是 self_reported。 |
| 文件验收及归档 | 必须是当前实际文件、当前输入哈希，并在同一次确认内声明完成人工内容及逐页视觉审阅；先核实文件仍存在及哈希匹配。仅归档 human_confirmed_unpublished，保留模拟稿限制；不写历史公告库、不发布。 |

## 连续工作稿策略

以 event.workflow_policy 为准。continuous-v1：常规 A → B → T（仅 Word）→ draft 自动经核验推进；完整正文由人工确认，Word 必须在正文确认后制作，再由人工验收文件。纯文本在正文确认后定稿。不披露、暂缓、特殊处理及关键歧义仍需人工决定。自动核验不产生人工确认记录。无该策略标记的 legacy-v1 历史路径保留原 A/B/T/Word 确认，但新的 Pi 业务执行将通过带审计的版本更新启用连续策略。

## A 的字段映射

`status` 是兼容现有界面的总览：disclose／no_disclosure／needs_info／review_required。法律状态在 `matters[].duty_status` 中分别保存 mandatory／not_triggered／no_mandatory_identified／undetermined；时点单独用 timing_status。任一可靠路径 established 必须保留 mandatory，不被另一未知指标抵消。

`reasoning_items` 引用 source_id、locator、原文 quote、condition、fact_keys、application、outcome。quote 必须能在真实绑定条文正文定位。事实可以直接引用 `facts.字段`，或用 `summary` 的原句，以及 `scope.company_name`、`scope.stock_code`、`scope.board` 的冻结输入；未知、冲突和推测不能成为已成立路径的事实前提。当前未接入附件核验，不能填写 material_supported 冒充已核实资料。

`calculations` 使用 sum／ratio、fact_keys、result、unit、period、basis_source_id。服务端独立 Decimal 复算；公开公告或未知累计范围不得代替完整台账。口径选择、条件适用及用户关于台账完整性的陈述仍待专业审阅。

事项同时列程序提示、历史限制、案例 ID、特殊处理、决定性问题、下游缺口、复判条件及紧急程度。关键争议、紧急或专项处理单列人工升级，已知义务仍展示。

服务端加入判断 ID、contract_version、事实版本、资料版本、Skill 版本／哈希和执行宿主来源。判断结果中不存在由模型填写的 approved、approval_record 或真实身份字段。

## B、T、W 的字段映射

B 的 `documents` 包含 document_id、title、profile_id、purpose、necessity、applicability、stage、producer、production、timing、dependencies、source_ids。外部报告为 external_dependency，不生成冒充已出具的正式报告。

`requirements` 逐项绑定 requirement_id、document_id、section_id、format_field_refs、topic、granularity、necessity、applicability、source_ids、fact_keys、历史关系、gap_key、verify_method。文件在 B 按 A 判断、适用法源和本次事实确定。已绑定 profile 时，系统对章节和具体格式字段做覆盖核对；未覆盖项保留为正文及最终人工确认的显式提醒，不再因为序列化缺项阻断工作稿，也不得宣称格式已完整覆盖。每份本次公司文件仍须有具体内容要求，不能仅写文件名或空目录。

`drafting_gaps` 列 key、description、impact、owner、treatment、source_ids。B 只被判断或规划问题、无效特殊处理和未安排的缺口阻断；普通制稿待补可进入规划审阅。依法披露未确定状态须有来源依据并随完整正文确认一起审阅。

`output_mode=word` 时，T 使用 template_id、requirement_map（要求 ID → 模板真实章节 ID）、adaptations；模板不能反向删减已确认要求。draft 返回 template_id、text、requirement_map；text 是当前 Word 内容真源。

`output_mode=text` 时，A/B 按当前策略核验通过后直接进入 draft，按当前 result_schema 返回 documents 数组，每项含 document_id、text 和 requirement_map。文件集合对应 B 的本次公司起草清单，各文件只能映射自己的要求；不生成第三方已出具报告，不调用模板快照、Word 工具或 Word 确认。draft.documents 是逐文件正文真源，汇总 text 仅供兼容显示。依赖外部文件的当前公司正文仍须等依赖核实；不依赖的公司正文可以单独准备，不能把外部文件的列入清单写成已经出具。正文检查自动执行；continuous-v1 完整正文经人工确认后方可定稿。

## 版本、错误和权限

人工记录为只读 approval_records；每条包含事项、节点、产物版本、输入指纹、事实／上游依赖、确认人自报姓名、时间、决定、理由与失效原因。受影响旧记录保留，不能把永远有效的布尔值当作批准。Skill 正文或共享合同变化也使受影响旧任务与确认失效。

当前系统是本机工作区，内部运行身份提供租约隔离，未接入企业身份及跨客户授权服务。本公司历史公告和专用模板按公司范围读取，任务检索绑定当前事件并拒绝参数越界；管理身份仍是工作区级，不能宣传为生产多租户授权。授权内部附件、专项处理决定、自动监测和企业授权仍是接口缺口；按需制文支持同一请求中的多文件。

开放事项的 A 候选如已通过来源、结构和版本检查，仅缺决定性事实，可以保存为 awaiting_assessment_information；这不是 Gate 通过，不能进入 B。用户补充后按新版本重新判断。未知和未接入不算通过。错误不自动无限重试；同一节点、同类问题和当前事实最多初次失败加两次自动修复；失败结果及原候选保留，网络重试使用同一 request_id 不重复记数。

## 节点责任与统一提交（2.5）

A 只提交义务、时点、程序、决定性问题和复判条件。B 读取当前 A 后形成文件清单、每份文件颗粒度和制稿缺口。两个节点不重复序列化同一份 PlanCandidate。

task.evaluate 与 task.submit 使用相同的身份、版本和租约参数。服务端自动补齐能够唯一确定的字段，并把 field_bindings、每次候选和核验反馈留在原任务中。模型显式提供的错误值不会被覆盖；有歧义就反馈修订。成功后按 next_context 连续进入下一合法节点，或等待必需的人工确认；未知事实保存待补；可修复问题允许同一任务内初次提交加两次修订，未通过不能作为正式产物。

计算 scope=snapshot 且 operation=sum 时，可以用 facts 作为数量勾稽依据，省略 result 由 Decimal 根据已登记数值计算。法律阈值和累计判断仍须绑定相应规则；scope=cumulative 的公开公告或未知范围不能冒充完整台账。单位、时点、输入事实和法律适用仍由业务判断核实。

task.library.read 默认返回注册条款正文及原件定位，不附整份法规；page 显式读取页，view=document 显式展开全文。定义、例外、关联条款必须按分析需要继续读取，节省上下文不等于省略必要核验。检索返回精简来源信息，原件、哈希和全量依据保留在库与执行回执中。
