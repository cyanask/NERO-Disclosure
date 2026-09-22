import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Empty,Modal,Spin,Table} from 'antd';
import {AppstoreOutlined,AuditOutlined,BookOutlined,FileTextOutlined,HistoryOutlined,ReloadOutlined,SettingOutlined} from '@ant-design/icons';
import {api,setCsrf} from './api';
import type {DisclosureEvent,Meta} from './types';
import {stages} from './types';
import {companyBoard,eventsForCompany,legacyCompany} from './companyWorkspace';
import type {Company,CompanyWorkspace} from './companyWorkspace';
import CompanyEntrance from './components/CompanyEntrance';
import LibraryPage from './components/LibraryPage';
import SystemGovernancePage from './components/SystemGovernancePage';
import AnnouncementSchedule from './components/AnnouncementSchedule';
import RunDetail from './components/RunDetail';
import ConversationConsole from './components/ConversationConsole';
import {SessionReceipts} from './components/PiRunAudit';
import ExecutionEvidence from './components/ExecutionEvidence';
import ModelSettingsPage from './components/ModelSettingsPage';
import DeliveryTable,{deliveryRows} from './components/DeliveryTable';
import type {DocumentListing} from './components/DeliveryTable';
import {ViewRequests,readEvents,readDeliverySources} from './workspaceRequests';

const pages=[{key:'console',label:'对话操作台',icon:<AppstoreOutlined/>},{key:'schedule',label:'公告时间表',icon:<HistoryOutlined/>},{key:'library',label:'知识库',icon:<BookOutlined/>},{key:'artifacts',label:'交付文件',icon:<FileTextOutlined/>},{key:'runs',label:'执行记录',icon:<HistoryOutlined/>},{key:'laws',label:'系统治理',icon:<AuditOutlined/>},{key:'models',label:'模型设置',icon:<SettingOutlined/>}];
type SavedView={page:string;chatSession?:string};
function savedView(company:Company):SavedView{
 try{const saved=JSON.parse(window.localStorage.getItem(`nero-disclosure:company:${company.board}:${company.stock_code}`)||'{}');return {page:pages.some(p=>p.key===saved.page)?saved.page:'console',chatSession:saved.chatSession};}catch{return {page:'console'};}
}
export default function App(){
 const [workspace,setWorkspace]=useState<CompanyWorkspace>(),[error,setError]=useState(''),[retry,setRetry]=useState(0),[choosing,setChoosing]=useState(false),[settings,setSettings]=useState(false);
 useEffect(()=>{let active=true;setError('');(async()=>{try{const session=await api<{csrf_token:string}>('/session');if(!active)return;setCsrf(session.csrf_token);const value=await api<CompanyWorkspace>('/company-workspace');if(!active)return;
  let previous:Company|undefined;try{previous=legacyCompany(value,window.localStorage.getItem('nero-disclosure:workspace-v1'));}catch{/* Browser storage may be unavailable. */}
  if(previous)value.company=await api<Company>('/company-workspace/select','POST',{board:previous.board,stock_code:previous.stock_code});
  if(active){setWorkspace(value);if(value.company)try{window.localStorage.removeItem('nero-disclosure:workspace-v1');}catch{/* One-time legacy selection is optional. */}}
 }catch(e){if(active)setError((e as Error).message);}})();return()=>{active=false;};},[retry]);
 const enter=(company:Company)=>{setWorkspace(previous=>({company,companies:[company,...(previous?.companies||[]).filter(c=>c.board!==company.board||c.stock_code!==company.stock_code)]}));setChoosing(false);};
 if(settings)return <main className="company-settings-shell"><ModelSettingsPage backLabel="返回公司登记" onBack={()=>{setSettings(false);setRetry(n=>n+1);}}/></main>;
 if(!workspace)return <main className="workspace-loading"><span>信息披露 · AI 辅助系统</span>{error?<Alert type="error" message={error} action={<Button onClick={()=>setRetry(n=>n+1)}>重新连接</Button>}/>:<><Spin/><span>正在读取本公司设置</span></>}</main>;
 if(!workspace.company||choosing)return <CompanyEntrance workspace={workspace} onEnter={enter} onSettings={()=>setSettings(true)} onReturn={workspace.company?()=>setChoosing(false):undefined}/>;
 return <CompanyWorkbench key={`${workspace.company.board}:${workspace.company.stock_code}`} company={workspace.company} onCompanySettings={()=>setChoosing(true)}/>;
}
function CompanyWorkbench({company,onCompanySettings}:{company:Company;onCompanySettings:()=>void}){
 const board=companyBoard(company),companyCode=company.stock_code;
 const [saved]=useState(()=>savedView(company));
 const [assistantRequest,setAssistantRequest]=useState<{text:string;key:number}>();
 const assist=(message:string)=>{setAssistantRequest({text:message,key:Date.now()});navigate('console',{clearSession:true});};
 const [navigationHost,setNavigationHost]=useState<HTMLDivElement|null>(null);
 const [auditSession,setAuditSession]=useState('');
 const [governanceTab,setGovernanceTab]=useState('laws');
 const [eventPage,setEventPage]=useState(1);
 const [meta,setMeta]=useState<Meta>();const [events,setEvents]=useState<DisclosureEvent[]>([]);const [selected,setSelected]=useState<DisclosureEvent>();
 const [documents,setDocuments]=useState<DocumentListing>({items:[],warnings:[]});
 const [page,setPage]=useState(saved.page);const [chatSession,setChatSession]=useState<string|undefined>(saved.chatSession);const [loading,setLoading]=useState(true);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [reload,setReload]=useState(0);
 const scope=useRef(new ViewRequests());
 const refreshSequence=useRef({events:0,deliveries:0});
 useEffect(()=>()=>{scope.current.invalidate();},[]);
 useEffect(()=>{try{window.localStorage.setItem(`nero-disclosure:company:${company.board}:${companyCode}`,JSON.stringify({page,chatSession}));}catch{/* Current-page navigation still works. */}},[company.board,companyCode,page,chatSession]);
 useEffect(()=>{let active=true;const initialView=scope.current.capture();setLoading(true);setError('');
  (async()=>{try{const session=await api<{csrf_token:string}>('/session');if(!active)return;setCsrf(session.csrf_token);
   const [metadata,records]=await Promise.all([api<Meta>(`/meta?board=${board.layer}`),api<DisclosureEvent[]>(`/events?board=${board.layer}&company=${companyCode}`)]);if(!active)return;setMeta(metadata);setEvents(records);
   const target=new URLSearchParams(window.location.search).get('event');
   if(target&&initialView.current()){const record=await api<DisclosureEvent>(`/events/${encodeURIComponent(target)}?company=${companyCode}`);if(!active||!initialView.current())return;if(eventsForCompany([record],company).length){setGovernanceTab('events');navigate('laws',{event:record});}else{setError('此事项不属于本公司，请在对应公司工作台查看。');}}
  }catch(e){if(active)setError((e as Error).message);}finally{if(active)setLoading(false);}})();
  return()=>{active=false;};
 },[company.board,companyCode,reload]);
 const refreshEvents=async()=>{const request=scope.current.capture(),sequence=++refreshSequence.current.events;const valid=()=>request.current()&&sequence===refreshSequence.current.events;setBusy(true);try{const records=await readEvents(board.layer,companyCode,request.signal);if(valid()){setEvents(records);setError('');}}catch(e){if(valid())setError((e as Error).message);}finally{if(valid())setBusy(false);}};
 const refreshDeliveries=async()=>{const request=scope.current.capture(),sequence=++refreshSequence.current.deliveries;const valid=()=>request.current()&&sequence===refreshSequence.current.deliveries;setBusy(true);setError('');try{
  const result=await readDeliverySources(board.layer,companyCode,request.signal);if(!valid())return;
  if(result.events.status==='fulfilled')setEvents(result.events.value);else setError('事项列表未刷新，暂显示上次记录：'+result.events.reason.message);
  if(result.documents.status==='fulfilled')setDocuments(result.documents.value);else{const message=String(result.documents.reason?.message||result.documents.reason);setDocuments(previous=>({...previous,warnings:['文件列表未刷新，暂显示上次记录：'+message]}));}
 }catch(e){if(valid())setError((e as Error).message);}finally{if(valid())setBusy(false);}};
 useEffect(()=>{if(page==='artifacts')void refreshDeliveries();},[page]);
 const open=async(id:string)=>{scope.current.invalidate();const request=scope.current.capture();setBusy(true);try{const record=await api<DisclosureEvent>(`/events/${encodeURIComponent(id)}?company=${companyCode}`,'GET',undefined,{signal:request.signal});if(!request.current())return;if(!eventsForCompany([record],company).length)throw new Error('此事项不属于本公司。');setGovernanceTab('events');navigate('laws',{event:record});}catch(e){if(request.current())setError((e as Error).message);}finally{if(request.current())setBusy(false);}};
 const records=eventsForCompany(events,company);const deliveries=deliveryRows(records,documents.items);
 const renderScope=scope.current.generation;
 const eventList=<><div className="gov-toolbar"><div><h2>事项办理记录</h2><p>按业务事项跟踪当前阶段、修订版本和办理详情。</p></div><Button loading={busy} onClick={refreshEvents}>刷新事项</Button></div><Table className="compact-library-table compact-operational-table" size="small" tableLayout="fixed" rowKey="id" dataSource={records} pagination={{current:eventPage,onChange:setEventPage}} loading={busy} scroll={{x:760}} columns={[{title:'事项',dataIndex:'title',width:'36%',render:(v,r)=><Button type="link" title={v} className="text-link operational-record-link" onClick={()=>open(r.id)}><span className="record-title">{v}</span></Button>},{title:'当前阶段',dataIndex:'stage',width:'26%',render:v=><span className="status-text">{stages[v]||v}</span>},{title:'版本',dataIndex:'revision',width:'12%',render:v=>`r${v}`},{title:'更新时间',dataIndex:'updated_at',width:'26%',render:v=>new Date(v).toLocaleString('zh-CN')}]} locale={{emptyText:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<span>暂无事项记录。请在对话操作台办理本公司事项。<br/><Button type="link" onClick={()=>navigate('console')}>前往对话操作台</Button></span>}/>}}/></>;
 const eventRecords=selected&&meta?<div className="governance-event-detail"><Button type="text" className="event-detail-back" onClick={()=>{scope.current.invalidate();setBusy(false);setSelected(undefined);}}>← 返回事项办理记录</Button><RunDetail key={selected.id} event={selected} meta={meta} onChanged={event=>{if(scope.current.generation!==renderScope||!eventsForCompany([event],company).length)return;setSelected(event);setEvents(prev=>[event,...prev.filter(x=>x.id!==event.id)]);}} onLibrary={()=>navigate('library')}/></div>:eventList;
 const navigate=(key:string,options:{event?:DisclosureEvent;session?:string;clearSession?:boolean}={})=>{scope.current.invalidate();setBusy(false);setPage(key);setSelected(options.event);if(options.session!==undefined)setChatSession(options.session);else if(options.clearSession)setChatSession(undefined);setError('');};
 return <div className="app-shell">
  <a className="skip-link" href="#workspace">跳至工作区</a>
  <aside className="workspace-sidebar">
   <div className="sidebar-brand"><div className="product-name"><img className="personal-mark" src="/disclosure-window-sidebar.svg" width="40" height="40" alt="披露之窗"/><span className="brand-two-lines"><span>信息披露</span><span className="second">AI 辅助系统</span></span></div><span className="sidebar-subtitle" lang="en">DISCLOSURE WORKSPACE</span></div>
   <div className="company-context"><strong>{company.company_name}</strong><small>{company.stock_code} · {company.board_name}</small></div>
   <span className="sidebar-nav-label">工作空间</span><nav className="primary-nav" aria-label="主导航">{pages.map(item=><button key={item.key} className="nav-item" aria-current={page===item.key?'page':undefined} onClick={()=>navigate(item.key)}>{item.icon}<span>{item.label}</span></button>)}</nav>
   <div className="sidebar-foot"><span className="sidebar-rule"/><p>信息有据<br/>披露有序</p></div>
  </aside>
  <div className="workspace-body"><header className="workspace-header"><div className="workspace-breadcrumb"><span>{company.company_name}</span><i>/</i><strong>{pages.find(item=>item.key===page)?.label}</strong></div>{page==='console'&&<div className="workspace-quick-navigation" ref={setNavigationHost}/>}<div className="workspace-header-right"><span className={`connection-status ${meta?'ready':''}`}><i/>{loading?'正在连接':meta?'本机已连接':'连接失败'}</span><button className="header-switch" onClick={onCompanySettings}>公司设置</button></div></header>
  <main id="workspace" className={`workspace-main${['schedule','library','artifacts','laws','models','runs'].includes(page)?' compact-page-intro':''}`} tabIndex={-1}>
   {page==='schedule'&&<AnnouncementSchedule key={`${board.layer}-${companyCode}`} board={board.layer} company={companyCode} onAssist={assist}/>}
   {loading?<div className="workspace-loading"><Spin/><span>正在读取本公司工作台</span></div>
   :!meta?<Alert type="error" message={error||'工作台连接失败'} action={<Button onClick={()=>setReload(n=>n+1)}>重新连接</Button>}/>
   :<>
    {error&&<Alert type="error" message={error} closable onClose={()=>setError('')}/>}
    <div className="workspace-page" key={`${board.id}-${page}`}>
    {page==='console'&&<ConversationConsole companyName={company.company_name} companyCode={companyCode} assistantRequest={assistantRequest} navigationHost={navigationHost} onEventDeleted={id=>{if(scope.current.generation===renderScope){setEvents(prev=>prev.filter(e=>e.id!==id));setSelected(prev=>prev?.id===id?undefined:prev);}}} board={board.layer} meta={meta} events={records} initialSession={chatSession} onSessionChange={setChatSession} onAudit={open} onSettings={sid=>navigate('models',{session:sid})} onChanged={event=>{if(scope.current.generation!==renderScope||!eventsForCompany([event],company).length)return;setEvents(prev=>[event,...prev.filter(x=>x.id!==event.id)]);}}/>}
    {page==='models'&&<ModelSettingsPage onBack={()=>navigate('console')}/>}
    {page==='library'&&<LibraryPage key={`${board.layer}-${companyCode}`} board={board} companyCode={companyCode} onAssist={assist}/>}
    {page==='laws'&&<SystemGovernancePage key={`governance-${board.layer}`} board={board} companyCode={companyCode} eventRecords={eventRecords} activeTab={governanceTab} onTabChange={tab=>{scope.current.invalidate();setBusy(false);setGovernanceTab(tab);}} onOpenSession={setAuditSession} onOpenRuns={()=>navigate('runs')} onOpenEvent={id=>{void open(id);}}/>}
    {page==='runs'&&<section className="resource-page">
     <div className="page-heading"><div><span className="page-kicker">ACTIVITY</span><h1>执行记录</h1><p className="muted">记录每次会话查阅了哪些公告法规。</p></div></div>
     <ExecutionEvidence board={board.layer} company={companyCode} onSession={sid=>navigate('console',{session:sid})}/>

    </section>}
    {page==='artifacts'&&<section className="resource-page">
     <div className="page-heading"><div><span className="page-kicker">DELIVERABLES</span><h1>交付文件</h1><p className="muted">本公司会话及事项中已生成的 Word，保留版本与待补状态。</p></div><Button icon={<ReloadOutlined/>} loading={busy} onClick={refreshDeliveries}>刷新记录</Button></div>
     {documents.warnings.map((warning,i)=><Alert key={i} type="warning" message={warning}/>)}
     <DeliveryTable rows={deliveries} busy={busy} onSession={sid=>navigate('console',{session:sid})} onEvent={id=>void open(id)}/>
    </section>}
    </div></>}
  </main></div><Modal title="系统执行记录" open={!!auditSession} width={940} footer={null} onCancel={()=>setAuditSession('')} destroyOnClose>{auditSession&&<SessionReceipts key={auditSession} sessionId={auditSession}/>}</Modal>
 </div>;
}
