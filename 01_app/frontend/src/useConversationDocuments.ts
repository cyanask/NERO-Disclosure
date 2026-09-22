import {useEffect,useState} from 'react';
import {api} from './api';
import type {ListedDocument} from './conversationPresentation';

/** Fetch once per session/delivery revision; no requests per rendered round. */
export function useConversationDocuments(sid:string,revision:number){
 const [snapshot,setSnapshot]=useState<{sid:string;items:ListedDocument[];error:string}>({sid:'',items:[],error:''});
 useEffect(()=>{let current=true;
  if(!sid){setSnapshot({sid:'',items:[],error:''});return;}
  api<{items:ListedDocument[]}>(`/chat/sessions/${sid}/documents`).then(data=>{if(current)setSnapshot({sid,items:data.items,error:''});})
   .catch(e=>{if(current)setSnapshot({sid,items:[],error:`读取已交付文件失败：${e.message}`});});
  return()=>{current=false;};
 },[sid,revision]);
 return snapshot.sid===sid?snapshot:{sid,items:[],error:''};
}
