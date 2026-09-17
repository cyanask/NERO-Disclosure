# 会话中的 Word 制作

用户可直接说“认可你的方案，请制作成 Word”，或“先按当前资料制作公告，缺的标待补”。Pi 选择 `disclosure/document`，从当前公司、事项、会话和已保存文稿组织内容，选择实际模板后调用既有 `scripts/agent_word.py`。公告和分析材料使用相同交互方式，不要求走完事项全部节点。

咨询和拟公告分别加载项目方法 Skill。拟公告先保存正文版本，用户可回复确认，并随时要求 Word；Word 区分公告和咨询回复。会话主要对外输出文件，系统外修改无需回传。流程见[咨询、拟公告与 Word 输出](CONSULTATION_ANNOUNCEMENT_FLOW.md)。

文档以独立版本保存。生成只更新会话文档，不修改事项阶段、不代签正文确认、不发布。最终文件在文档卡片中集中审阅；文字预览不是分页验收，实际版式应打开 Word 核对。浏览器下载请求和保存成功分别处理，安全策略拦截不会标为下载完成。

## 执行与数据边界

- 唯一控制器仍为 `PiRuntime`。`document_runtime` 是其工具实现，不创建额外 Agent、队列或常驻服务。
- 每轮绑定现有 session/run、公司和板块；制文前自动冻结事项版本、用户陈述、文档索引版本、正文和模板。实际文件回读及哈希通过后才能登记。
- 文稿与文件存于 `03_local/work/documents/<session>/`，`index.json` 是文档版本和审阅状态的真源；run 中只保存产物引用。沿用原子写入和当前 runtime 单实例锁，不改变数据库 schema。
- 同一批次多文稿全部制作成功后原子登记。取消、超时、旧版本和跨会话访问不会替换当前稿；未登记临时文件不显示为交付成功。服务重启沿用 interrupted 状态恢复规则，已有文档从索引读取，模型调用不会自动重放。
- 用户在会话内提出修改，系统基于已登记的当前稿生成新版本。公告 Word 使用正文段落锚点修改副本，除 `word/document.xml` 外的 package parts 保持字节一致；无法定位或跨段修改明确失败。历史人工稿仍受原有保护，不再导入新人工稿或读取外部工作副本。
- 最终确认由浏览器用户操作，绑定当前版本及哈希，不能由模型调用。待补事项未解决时可下载审阅，但不能标为定稿。

## 工具与接口

Pi 文档阶段提供 `read_document_context`、`read_document_template`、`read_document`、`make_word`，并沿用当前板块资料检索工具。正文事实通过 `basis` 原句绑定本轮来源；模型组织与机器校验不等于人工业务接受。

浏览器可读取 `/api/chat/sessions/{sid}/documents` 及文件、文字预览，提交当前文件 review。浏览器没有文稿生成 API。旧 `/exports` POST、`/documents/import` POST、`/documents/{id}/open` POST 返回 410；历史文件及版本仍可读取。

## 验证要求

覆盖咨询直接制文、方案中途制作公告、复用正文、多文件、带待补项、系统内修订、历史版本保护、停用回传、外部副本变化隔离、旧版本冲突、跨会话访问、取消和重启恢复；必须区分模拟模型的集成测试与真实模型/browser evidence。短指令验收不能依赖外部 Agent 代写冗长业务提示。

<!-- prose-quality-binding: {"core_id": "nero-chinese-prose-quality", "core_version": "0.4.0", "profile": "general", "rules_sha256": "4758913f7f778ff53e520c480a470ad4aab40112855ca97a5b905a2db6f129b3", "body_sha256": "75c07a16ee9850c20a5d09f64ede97561b713d5910d6ebc0d446ff6d19a0dddf", "body_scope": "text before this comment, normalized to one trailing newline", "automatic_check": {"deterministic_pass": true, "finding_count": 0}, "model_review": "Reviewed output-only scope against code and observed checks; historical sources and human acceptance remain separate", "human_acceptance": "not_claimed"} -->
