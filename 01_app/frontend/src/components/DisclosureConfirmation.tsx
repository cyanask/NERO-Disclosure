import {useEffect,useState} from 'react';
import type {ReactNode} from 'react';
import {Alert,Button,Checkbox,Input,Modal,Select,Space,Table} from 'antd';
import type {DisclosureEvent,Gate} from '../types';
import Evidence from './Evidence';
import ConditionalPlan from './ConditionalPlan';
import {prose} from '../api';
import MessageMarkdown from './MessageMarkdown';
import {canSubmitConfirmation,wordReviewCopy,supportsConfirmation} from '../humanGates';

const labels:Record<string,string>={assessment:'判断与处理决定',plan:'文件与内容规划',template:'模板适配',draft:'完整正文',word:'当前 Word 文件'};
const duty:Record<string,string>={mandatory:'已识别强制义务',not_triggered:'条件尚未满足',no_mandatory_identified:'当前未识别强制义务',undetermined:'待判断'};
const timing:Record<string,string>={triggered:'已触发',not_triggered:'尚未触发',unknown:'待核实'};

export function DraftReviewBody({event}:{event:DisclosureEvent}){
 const documents=event.plan?.documents||[];
 return <div className="draft-review-body">
  <h4>本次文件清单</h4>
  {documents.length?<Table size="small" rowKey="document_id" pagination={false} scroll={{x:650}} dataSource={documents} columns={[{title:'文件',dataIndex:'title'},{title:'出具方',dataIndex:'producer'},{title:'用途与阶段',render:(_,d)=><>{({public:'公开披露',filing:'报送备查',internal:'内部支持'} as Record<string,string>)[d.purpose]||d.purpose}；{({current:'本次',later_trigger:'后续触发',preliminary:'仅预制'} as Record<string,string>)[d.stage]||d.stage}</>},{title:'适用及时间',render:(_,d)=><>{d.applicability}；{d.timing}{d.dependencies?.length?`；依赖：${d.dependencies.join('、')}`:''}</>}]}/>:<Alert type="warning" message="尚无本次文件清单"/>}
  {event.output_mode==='text'?event.draft?.documents?.map(d=><article key={d.document_id}><h4>{documents.find(item=>item.document_id===d.document_id)?.title||d.document_id}</h4><MessageMarkdown text={d.text}/></article>):<><h4>完整正文</h4><MessageMarkdown text={event.draft?.text||''}/></>}
 </div>;
}

function ReviewSurface({inline,open,title,busy,onClose,footer,children,className}:{inline:boolean;open:boolean;title:string;busy:boolean;onClose:()=>void;footer:ReactNode;children:ReactNode;className?:string}){
 if(inline)return open?<div className="inline-review" aria-label={title}><h3>{title}</h3>{children}<div className="inline-actions">{footer}</div></div>:null;
 return <Modal className={className} title={title} open={open} width={860} onCancel={()=>!busy&&onClose()} footer={footer}>{children}</Modal>;
}

export function DraftingSupplements({event,stage,busy,write}:{event:DisclosureEvent;stage:string;busy:boolean;write:(suffix:string,body:object)=>Promise<boolean>}){
 const [supplementKey,setSupplementKey]=useState(''),[supplementValue,setSupplementValue]=useState(''),[sourceNote,setSourceNote]=useState('');
 return stage==='template'&&!!event.plan?.drafting_gaps?.length&&<details><summary>补充已列明的制稿资料</summary><p>若金额、主体或时点变化影响判断，应先退回判断节点。</p><Select aria-label="选择制稿待补项" style={{minWidth:240}} value={supplementKey||undefined} onChange={setSupplementKey} options={event.plan.drafting_gaps.filter(g=>g.impact==='draft'&&g.treatment==='supply').map(g=>({value:g.key,label:g.description}))}/><Input.TextArea aria-label="补充资料内容" value={supplementValue} onChange={e=>setSupplementValue(e.target.value)}/><Input aria-label="补充资料来源" placeholder="资料来源及时间" value={sourceNote} onChange={e=>setSourceNote(e.target.value)}/><Button disabled={busy||!supplementKey||!supplementValue.trim()||!sourceNote.trim()} onClick={()=>write('/drafting-supplements',{values:{[supplementKey]:supplementValue},source_note:sourceNote})}>保存制稿补充</Button></details>;
}

export default function DisclosureConfirmation({event,stage,gate,busy,write,compact=false,inline=false,presentation}:{event:DisclosureEvent;stage:string;gate?:Gate;busy:boolean;write:(suffix:string,body:object)=>Promise<boolean>;compact?:boolean;inline?:boolean;presentation?:'detail'}){
 const [open,setOpen]=useState(false),[reviewer,setReviewer]=useState(''),[reason,setReason]=useState('');
 const [decision,setDecision]=useState('accept'),[visual,setVisual]=useState(false),[content,setContent]=useState(false);
 const [error,setError]=useState('');
 useEffect(()=>{setOpen(false);setVisual(false);setContent(false);setReason('');setError('');},[event.id,event.revision,stage,gate?.input_fingerprint,event.current_artifact_id]);
 if(!labels[stage]||(presentation==='detail'&&!supportsConfirmation(event,stage)))return null;
 const records=event.approval_records||[];
 const current=(presentation!=='detail'||gate?.status==='PASS')?[...records].reverse().find(r=>r.node===stage&&r.state==='current'&&r.input_fingerprint===gate?.input_fingerprint):undefined;
 const wordCopy=wordReviewCopy(event);
 const artifact=event.artifacts?.find(a=>a.id===event.current_artifact_id);
 const hasDraft=!!event.plan?.documents?.length&&(event.output_mode==='text'?!!event.draft?.documents?.length&&event.draft.documents.every(d=>!!d.text.trim()):!!event.draft?.text?.trim());
 const rejectOnly=presentation==='detail'&&gate?.status!=='PASS';
 const special=presentation==='detail'&&stage==='assessment'&&gate?.next_action.action==='manual_escalation';
 const choices=rejectOnly?[{value:'reject',label:'退回修订'}]:special?[{value:'special_review',label:'转专项处理'},{value:'reject',label:'退回修订'}]:stage==='assessment'?[{value:'prepare_mandatory',label:'依法准备披露'},{value:'prepare_voluntary',label:'自愿准备披露'},{value:'no_disclosure',label:'当前不披露并人工跟踪'},{value:'special_review',label:'转特殊或专项处理'},{value:'reject',label:'不认可，退回修订'}]:[{value:'accept',label:'认可当前版本'},{value:'reject',label:'不认可，退回修订'}];
 const begin=()=>{setDecision(rejectOnly?'reject':stage==='assessment'?(gate?.next_action.action==='manual_escalation'?'special_review':event.assessment?.status==='disclose'?'prepare_mandatory':event.assessment?.status==='no_disclosure'?'no_disclosure':'reject'):'accept');setOpen(true);};

 return <section>
  {!compact&&<div className="confirmation-heading"><h2 className="section-title">人工确认：{labels[stage]}</h2>
  <p className="muted">每次产品内确认均绑定具体版本。确认人姓名由本机使用者填写，不代表法定程序或已核验的审批权限。</p></div>}
  {current?<Alert type="success" message={`当前版本已由 ${current.reviewer} 确认`} description={current.reason}/>:<Button type="primary" disabled={busy||!gate} onClick={begin}>{presentation==='detail'?(rejectOnly?'查看问题并退回修订':special?'审阅专项处理决定':'审阅并确认当前结果'):'审阅并确认当前版本'}</Button>}
  {!compact&&!!records.length&&<details><summary>确认记录与失效原因</summary>{records.map(r=><p key={r.id}>{labels[r.node]||r.node} · {r.reviewer} · {({current:'当前有效',invalidated:'已失效',superseded:'已替代',rejected:'已退回'} as Record<string,string>)[r.state]||r.state} · {r.reason}{r.invalidation_reason&&`；${r.invalidation_reason}`}</p>)}</details>}
  {presentation!=='detail'&&<DraftingSupplements event={event} stage={stage} busy={busy} write={write}/>}
  <ReviewSurface className={presentation==='detail'?'event-review-modal':undefined} inline={inline} title={rejectOnly?'查看问题并退回修订':`确认${labels[stage]}`} open={open} busy={busy} onClose={()=>setOpen(false)} footer={<Space><Button disabled={busy} onClick={()=>setOpen(false)}>取消</Button><Button type="primary" loading={busy} disabled={!canSubmitConfirmation({stage,decision:rejectOnly?'reject':decision,reviewer,reason,gate,content,visual,hasDraft,hasArtifact:!!artifact})} onClick={async()=>{
   setError('');const ok=await write('/confirmations',{stage,input_fingerprint:gate?.input_fingerprint,decision:rejectOnly?'reject':decision,reviewer:reviewer.trim(),reason,artifact_id:stage==='word'?artifact?.id:undefined,visual_review:visual?'reviewed':'not_reviewed',content_review:content?'reviewed':'not_reviewed'});
   if(ok)setOpen(false);else setError('未能保存确认，请查看当前版本和阻断原因后重试。');
  }}>{rejectOnly?'保存退回意见':'保存本次确认'}</Button></Space>}>
   <p>当前事项：{event.title} · r{event.revision}。{rejectOnly?'本次仅记录退回意见，不确认现有结果。':'认可只适用于本次显示的内容与上游依赖。'}</p>
   {compact&&<p className="muted">确认人姓名由本机使用者填写，不代表法定程序或已核验的审批权限。</p>}
   {error&&<Alert type="error" message={error}/>}
   {rejectOnly&&<p>当前仅可退回修订，不能确认通过。</p>}
   {!!gate?.issues.length&&<Alert type="error" message="存在阻断项，只能退回修订" description={<ul>{gate.issues.map((i,n)=><li key={n}>{i.detail}</li>)}</ul>}/>}
   {!!gate?.warnings?.length&&<Alert type="warning" message="审阅时须处理以下限制" description={<ul>{gate.warnings.map((i,n)=><li key={n}>{i.detail}</li>)}</ul>}/>}
   <details className="confirmation-basis" open={!rejectOnly&&(stage==='draft'||!inline)?true:undefined}><summary>本次确认的内容与依据</summary>
   {stage==='assessment'&&event.assessment&&<>
    <p className="preserve">{prose(event.assessment.summary)}</p>
    <ConditionalPlan plan={event.assessment.preliminary_plan}/>
    {event.assessment.facts?.map(f=><p key={f.key}>{f.key}：{String(f.value??'未知')}；{({user_statement:event.intake_mode==='open'?'任务输入':'用户陈述',material_supported:'材料支持',model_inference:'模型推测',unknown:'未知',conflicting:'冲突'} as Record<string,string>)[f.status]}；来源：{f.quote||f.source_ref}（{f.observed_at}）</p>)}
    {event.assessment.matters?.map(m=><article key={m.matter_id}><h4>{m.subject} · {m.stage}</h4><p>{duty[m.duty_status]}；时点：{timing[m.timing_status]}。</p><p>{m.trigger_events?.join('；')}</p>{m.reasoning_items.map((r,n)=><p key={n}>{r.condition} → {r.application}<br/>依据：{r.locator}“{r.quote}”</p>)}<p>程序：{m.procedural_requirements?.join('；')||'未列明，须核对'}</p><p>关键问题：{m.decisive_questions?.join('；')||'无已列明问题'}</p><p>复判条件：{m.reassessment_conditions?.join('；')||'按后续事实变化判断'}</p>{m.limitations?.map((text,i)=><p key={i}>{text}</p>)}</article>)}
    <Evidence items={event.assessment.citations}/>
   </>}
   {stage==='plan'&&event.plan&&<>
    <p>规划：{gate?.review_readiness==='ready'?'可供审阅':'尚有阻碍'}；制稿：{gate?.drafting_readiness?.status==='ready'?'资料就绪':'仍有待补或接口依赖'}。</p>
    <Table size="small" rowKey="document_id" pagination={false} scroll={{x:650}} dataSource={event.plan.documents} columns={[{title:'文件',dataIndex:'title'},{title:'出具方',dataIndex:'producer'},{title:'用途与阶段',render:(_,d)=><>{({public:'公开披露',filing:'报送备查',internal:'内部支持'} as Record<string,string>)[d.purpose]}；{({current:'本次',later_trigger:'后续触发',preliminary:'仅预制'} as Record<string,string>)[d.stage]}</>},{title:'适用及时间',render:(_,d)=><>{d.applicability}；{d.timing}{d.dependencies?.length?`；依赖：${d.dependencies.join('、')}`:''}</>}]}/>
    {event.plan.requirements?.map(r=><article key={r.requirement_id}><h4>{r.topic}</h4><p>{r.granularity}</p><p>适用：{r.applicability}；核对：{r.verify_method}</p></article>)}
    {!!event.plan.drafting_gaps?.length&&<ul>{event.plan.drafting_gaps.map(g=><li key={g.key}>{g.description}；提供方：{g.owner}</li>)}</ul>}
   </>}
   {stage==='draft'&&<DraftReviewBody event={event}/>}
   {stage==='template'&&event.template&&<><p>模板：{event.template.template_id}</p><ul>{Object.entries(event.template.requirement_map).map(([key,value])=><li key={key}>{event.plan?.requirements?.find(r=>r.requirement_id===key)?.topic||key} → {event.plan?.items.find(i=>i.id===value)?.title||value}</li>)}</ul>{event.template.adaptations.map((s,i)=><p key={i}>{s}</p>)}</>}
</details>
   {!rejectOnly&&stage==='draft'&&<><p>{event.output_mode==='text'?'确认后正文定稿。':'确认完整正文后自动制作 Word，随后仍需你验收文件。'}</p><Checkbox checked={content} onChange={e=>setContent(e.target.checked)}>我已审阅本次文件清单和每份完整正文，并核对内容、数据、程序及适用限制</Checkbox></>}
   {!rejectOnly&&stage==='word'&&<>{artifact?<p><a href={`/api/events/${event.id}/artifacts/${artifact.id}/file`} target="_blank" rel="noreferrer">打开当前 Word：{artifact.filename}</a></p>:<p>当前没有可确认的 Word 文件。</p>}<p>确认后仅归档未公开稿。当前工具保留模拟稿标识。</p><Space direction="vertical"><Checkbox checked={content} onChange={e=>setContent(e.target.checked)}>{wordCopy.content}</Checkbox><Checkbox checked={visual} onChange={e=>setVisual(e.target.checked)}>{wordCopy.visual}</Checkbox></Space></>}
      <Select aria-label="本次处理决定" style={{width:'100%',marginTop:16}} value={decision} options={choices} onChange={setDecision}/>
   <Input aria-label="确认人姓名" placeholder="确认人姓名（本机自报）" value={reviewer} onChange={e=>setReviewer(e.target.value)}/>
   <Input.TextArea aria-label="确认或退回理由" placeholder="本次决定及理由；退回时说明问题" value={reason} onChange={e=>setReason(e.target.value)} rows={3}/>
  </ReviewSurface>
 </section>;
}
