import {Button,Checkbox,Input} from 'antd';
import {PlusOutlined,SearchOutlined,MessageOutlined,InboxOutlined,DeleteOutlined} from '@ant-design/icons';
import type {ChatSession} from '../chat';

type Props={
 sessions:ChatSession[];
 sid:string;
 search:string;
 onSearch:(value:string)=>void;
 archived:boolean;
 open:boolean;
 busy:boolean;
 running:(id:string)=>boolean;
 onToggle:()=>void;
 onNew:()=>void;
 onChoose:(id:string)=>void;
 onArchive:(item:ChatSession,archive:boolean)=>void;
 onDelete:(item:ChatSession)=>void;
 onArchived:(value:boolean)=>void;
};

export default function SessionPanel({sessions,sid,search,onSearch,archived,open,busy,running,onToggle,onNew,onChoose,onArchive,onDelete,onArchived}:Props){
 const visibleSessions=open?sessions.filter(s=>s.title.toLowerCase().includes(search.toLowerCase())):sessions;
 return <aside aria-label={archived?'已归档会话列表':'会话列表'} className={`session-panel ${open?'':'sessions-collapsed'}`}>
  <div className="session-heading"><Button type="text" aria-label={open?'收起会话列表':'展开会话列表'} aria-expanded={open} onClick={onToggle}>{archived?'归档':'会话'}</Button><Button type="text" aria-label="新建会话" disabled={busy} icon={<PlusOutlined/>} onClick={onNew}/></div>
  <Input aria-label="搜索会话" prefix={<SearchOutlined/>} placeholder="搜索会话名称" value={search} onChange={e=>onSearch(e.target.value)}/>
  <div className="session-list">{visibleSessions.map(s=><div key={s.id} className={`session-item ${sid===s.id?'selected':''}`}><button className="session-select" disabled={busy} onClick={()=>onChoose(s.id)} aria-current={sid===s.id?'true':undefined} title={`${s.title} · ${new Date(s.updated*1000).toLocaleString('zh-CN')}`}><MessageOutlined/><strong>{s.title}</strong></button><span className="session-row-actions">{archived?<><Button type="text" size="small" aria-label={`恢复会话：${s.title}`} disabled={busy} onClick={()=>onArchive(s,false)}>恢复</Button><Button type="text" size="small" danger icon={<DeleteOutlined/>} aria-label={`删除会话：${s.title}`} disabled={busy} onClick={()=>onDelete(s)}/></>:<Button type="text" size="small" icon={<InboxOutlined/>} aria-label={`归档会话：${s.title}`} disabled={busy||running(s.id)} onClick={()=>onArchive(s,true)}/>}</span></div>)}{!visibleSessions.length&&<p className="muted session-empty">{sessions.length?'未找到匹配会话':archived?'没有已归档会话':'暂无会话'}</p>}</div>
  <div className="session-footer"><Checkbox checked={archived} disabled={busy} onChange={e=>onArchived(e.target.checked)}>查看已归档</Checkbox></div>
 </aside>;
}
