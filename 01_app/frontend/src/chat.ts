export interface ChatModel {key:string;label:string;provider:string;id:string;api:string;baseUrl:string;configured:boolean;reason:string;api_key_env:string;reasoning_effort?:string;visible?:boolean}
export interface PiCapabilities {engine:string;version:string;installed:boolean;models:ChatModel[];configuration_path:string;mcp_connected:boolean;notice:string;routes?:Record<string,string>;settings_revision?:number}
export interface ChatSession {company_code?:string;id:string;board:string;event_id:string;title:string;archived:number;updated:number}
export interface DocumentVersion {warnings?:string[];format?:"text"|"docx";text?:string;document_id:string;version:number;title:string;filename:string;kind:"announcement"|"analysis";source_type:string;run_id?:string;created:number;sha256:string;bytes:number;template_id?:string;template_name?:string;pending:string[];review_status:string;download?:string}
export interface PiRun {announcement_assessment?:{disclosure_needed:string;disclosure_scope:string;reason:string;consultation_run_id?:string};documents?:DocumentVersion[];company_code?:string;resume_after_settle?:string|null;resume_confirmation_id?:string;resume_cancelled_for?:string;continuation_run_id?:string;timings?:Record<string,number>;research_stats?:Record<string,number>;active_phase?:string;intent_domain?:string;intent?:string;knowledge_change?:KnowledgeProposal;finalization_status?:string;id:string;session_id:string;event_id:string;board:string;stage:string;status:string;reason:string;created:number;updated:number;model:ChatModel;skill_status:string;questions?:string[];artifact_id?:string;skill?:{id:string;version:string;bundle_sha256:string}}
export interface Receipt {seq:number;run_id:string;at:number;kind:string;body:Record<string,unknown>}
export const live=(run?:PiRun)=>!!run&&['accepted','running','cancelling'].includes(run.status);
export const runLabels:Record<string,string>={accepted:'等待启动',running:'执行中',cancelling:'正在停止',completed:'本轮完成',waiting_user:'待补充',waiting_approval:'待人工确认',blocked:'检查阻断',failed:'执行失败',cancelled:'已停止',interrupted:'执行中断',incomplete:'结果未齐备'};
export const nodeLabels:Record<string,string>={chat:'普通聊天',assessment:'披露判断',plan:'文件与内容规划',template:'模板适配',draft:'公告正文',word:'Word 制作'};
export const receiptLabels:Record<string,string>={user:'用户消息',accepted:'接收执行',process_spawned:'建立进程',started:'Pi 已启动',context_loaded:'冻结上下文',skill_loaded:'装载 Skill',model_input:'发送模型上下文',assistant:'助手消息',model_tool_call:'模型请求工具',tool_requested:'登记工具调用',tool_started:'开始工具执行',tool_returned:'工具返回',tool_failed:'工具失败',model_tool_failed:'模型工具失败',verification:'结果核验',questions:'待补问题',script_started:'运行 Word 脚本',script_returned:'脚本返回',script_failed:'脚本失败',artifact:'Word 文件登记',done:'Pi 结束回执',settled:'本轮状态',cancel_requested:'请求停止',interrupted:'中断恢复',cleanup_pending:'任务占用待核对',capability_unavailable:'资料接口尚未连接'};
receiptLabels.skill_injected='Skill 已注入 Pi 上下文';
receiptLabels.failure='失败原因';

export interface KnowledgeProposal {file_operation?:boolean;company?:string;requires_publication_confirmation?:boolean;requires_extraction_confirmation?:boolean;source_preview?:string;source?:{empty_pages?:number[];text_completeness?:string};basis?:{id:string;title:string;article:string;url:string}[];id:string;fingerprint:string;status:string;operation:string;collection:string;summary:string;objects:{id:string;title:string}[];items:Record<string,unknown>[];before:Record<string,unknown>[];references:{kind:string;title:string}[];template?:unknown;result?:Record<string,unknown>}
Object.assign(nodeLabels,{auto:'需求判断',knowledge:'知识库管理',scope:'范围判断',classification:'公告标签复判',company_lookup:'公司核实'});
Object.assign(runLabels,{waiting_knowledge_confirmation:'待知识变更确认'});

Object.assign(receiptLabels,{routing_decision:'需求分流',routing_usage:'范围判断用量',phase_started:'工作能力已载入',knowledge_requested:'知识工具请求',knowledge_returned:'知识工具返回',knowledge_proposal:'知识变更预览',knowledge_applied:'知识变更已执行',facts_supplemented:'用户事实补充'});
receiptLabels.session_named='首问会话命名';

export const runStageLabel=(run:PiRun)=>run.stage==='chat'&&run.intent_domain==='disclosure'?'信披咨询':nodeLabels[run.stage]||run.stage;

Object.assign(receiptLabels,{model_call_interrupted:'模型调用中断与已等待耗时',model_call_started:'模型调用开始',model_call_finished:'模型调用结束',context_compacted:'阶段上下文归并',provider_failure:'模型服务返回异常',transport_cleanup:'本轮传输连接回收',cleanup_fallback:'结束后子进程回收',session_cleanup:'连接资源清理',stage_transition:'自动进入下一节点',completion_repair_started:'纠正未完成交付',completion_incomplete:'节点结果仍未齐备',tool_validation_failed:'工具输入校验失败',research_reuse:'资料复用与检索收敛',human_resume:'人工确认后自动接续',continuation_failed:'自动接续未启动',stage_hint_corrected:'按当前合法节点推进'});

nodeLabels.document='文档制作';
receiptLabels.documents_created='文档已生成';

Object.assign(nodeLabels,{announcement:'拟写公告',confirmation:'正文确认'});
Object.assign(receiptLabels,{drafts_saved:'公告正文版本已保存',text_confirmed:'用户正文确认',documents_reused:'沿用当前Word'});
