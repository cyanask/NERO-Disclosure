import {ReadOutlined,EditOutlined,DownOutlined} from '@ant-design/icons';
import {Popover} from 'antd';
import type {ReactNode} from 'react';
import type {WorkProgress} from '../workProgress';
import './ConversationNavigation.css';

export default function ConversationNavigation({progress,canRead,open=false,content,onClose,onShown,onProgress,onRead,onCompose}:{progress:WorkProgress;canRead:boolean;open?:boolean;content?:ReactNode;onClose?:()=>void;onShown?:()=>void;onProgress:()=>void;onRead:()=>void;onCompose:()=>void}){
 return <nav className="conversation-navigation" aria-label="会话快捷索引">
  <Popover content={content} open={open} trigger="click" placement="bottomRight" overlayClassName="header-work-progress-popover" destroyOnHidden onOpenChange={value=>{if(!value)onClose?.();}} afterOpenChange={value=>{if(value)onShown?.();}}>
   <button type="button" onClick={()=>{if(!open)onProgress();}} className={`header-progress-trigger ${progress.tone}`} onKeyDown={e=>{if(e.key==='Escape')onClose?.();}} aria-label={`工作进展，${progress.title}`} aria-haspopup="dialog" aria-expanded={open} title={progress.detail} data-motion={progress.animate&&!open?'on':'off'}><span className="header-progress-dot" aria-hidden="true"/><span className="header-progress-title" aria-live={open?'off':'polite'}>{progress.title==='尚未开始'?'工作进展':progress.title}</span><DownOutlined/></button>
  </Popover>
  <button type="button" onClick={onRead} disabled={!canRead} aria-label="回到正文"><ReadOutlined/><span>回到正文</span></button>
  <button type="button" onClick={onCompose} aria-label="继续提问"><EditOutlined/><span>继续提问</span></button>
 </nav>;
}
