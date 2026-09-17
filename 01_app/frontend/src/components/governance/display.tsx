import {Table} from 'antd';
export const stamp=(value?:string)=>value?new Date(value).toLocaleString('zh-CN'):'未核验';
export const size=(value:number)=>value>=1024**3?`${(value/1024**3).toFixed(2)} GB`:value>=1024**2?`${(value/1024**2).toFixed(1)} MB`:value>=1024?`${(value/1024).toFixed(1)} KB`:`${value} B`;
export const facts=(rows:[string,string|number|undefined][])=><Table rowKey="label" size="small" pagination={false} dataSource={rows.map(([label,value])=>({label,value}))} columns={[{title:'项目',dataIndex:'label',width:210},{title:'当前值',dataIndex:'value',render:(v:unknown)=><span className="gov-fact">{v===undefined||v===''?'—':String(v)}</span>}]}/>;

import type {Batch} from './types';
export const liveBatch=(b?:Batch)=>!!b&&['running','cancelling'].includes(b.status);
