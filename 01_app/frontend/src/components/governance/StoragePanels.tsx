import {Alert,Button,Empty,Space,Table,Tag} from 'antd';
import type {Inventory,Database,Backup,Cache,Quarantine} from './types';
import {size,stamp} from './display';
type Props={inventory?:Inventory;busy:boolean;onScan:()=>void;onPrepare:(category:string,ids:string[])=>void;onQuarantine:(item:Quarantine,action:'restore'|'purge')=>void};
export function DatabasePanel({inventory,busy,onScan,onPrepare,onQuarantine}:Props){
 return <>
  <div className="gov-toolbar"><div><h2>数据库副本</h2><p>每个数据库保留最新 1 份历史副本；超过 1 份即提示，当前数据库始终保留。</p></div><Button loading={busy} onClick={onScan}>手动扫描副本</Button></div>
  {!inventory?<Empty description="点击“手动扫描副本”，读取本项目数据库与历史副本。"/>:<>
   <p className="gov-summary">{inventory.databases.groups.length} 个当前数据库 · {inventory.databases.excess_groups} 组副本超出保留数量 <span>扫描于 {stamp(inventory.scanned_at)}</span></p>
   <Table<Database> rowKey="id" dataSource={inventory.databases.groups} pagination={false} scroll={{x:980}}
    expandable={{expandedRowRender:g=><div><p className="gov-path">当前文件：{g.current_path}</p>{!g.backups.length?<p>没有历史副本</p>:<Table<Backup> size="small" rowKey="path" dataSource={g.backups} pagination={false} columns={[{title:'副本路径',dataIndex:'path',render:v=><span className="gov-path">{v}</span>},{title:'大小',render:(_,r)=>size(r.bytes)},{title:'保留规则',dataIndex:'reason'}]}/>}</div>}}
    columns={[{title:'数据库',dataIndex:'label',width:280,render:v=>String(v).replace('chinext','创业板')},{title:'用途',dataIndex:'kind',width:130},{title:'当前大小',render:(_,r)=>size(r.current_bytes+r.sidecar_bytes),width:140},
     {title:'历史副本',render:(_,r)=><Tag color={r.needs_attention?'orange':undefined}>{r.backup_count} 份{r.needs_attention?' · 建议清理':''}</Tag>,width:160},
     {title:'可释放',render:(_,r)=>size(r.reclaimable_bytes),width:130},{title:'操作',render:(_,r)=><Button disabled={busy||!r.reclaimable_bytes} onClick={()=>onPrepare('databases',[r.id])}>预览清理清单</Button>}]} />
   {!!inventory.databases.unclassified.length&&<Alert type="warning" message={`${inventory.databases.unclassified.length} 个副本来源未能确定，已排除自动清理。`}/>}
   {!!inventory.quarantine?.items.some(item=>item.count>0)&&<><h3 className="gov-section">隔离区 · 可恢复副本</h3><p>移入隔离区尚未释放空间。可以恢复原位置，或核对清单后永久删除。</p>
    <Table<Quarantine> rowKey="id" size="small" dataSource={inventory.quarantine.items.filter(item=>item.count>0)} pagination={{pageSize:5}} columns={[{title:'批次',dataIndex:'id',render:v=><span className="gov-path">{v}</span>},{title:'文件数',dataIndex:'count'},{title:'占用',render:(_,r)=>size(r.bytes)},{title:'操作',render:(_,r)=><Space><Button disabled={busy} onClick={()=>onQuarantine(r,'restore')}>恢复副本</Button><Button danger disabled={busy} onClick={()=>onQuarantine(r,'purge')}>预览永久清理</Button></Space>}]}/></>}
   </>}
 </>;
}
export function CachePanel({inventory,busy,onScan,onPrepare}:Props){
 return <>
  <div className="gov-toolbar"><div><h2>缓存与空间</h2><p>查看可重建缓存的数量与占用；确认后按清单释放空间。</p></div><Button loading={busy} onClick={onScan}>手动扫描缓存</Button></div>
  {!inventory?<Empty description="点击“手动扫描缓存”，查看缓存数量和可释放空间。"/>:<>
   <p className="gov-summary">{inventory.caches.count} 个缓存文件 · 可释放 {size(inventory.caches.bytes)} · 磁盘剩余 {size(inventory.disk.free)} <span>扫描于 {stamp(inventory.scanned_at)}</span></p>
   <Table<Cache> rowKey="id" dataSource={inventory.caches.groups} pagination={false} columns={[{title:'缓存类型',dataIndex:'label',width:210},{title:'位置',dataIndex:'id',render:v=><span className="gov-path">{v}</span>},{title:'文件数',dataIndex:'count',width:100},{title:'可释放',render:(_,r)=>size(r.bytes),width:130},{title:'操作',width:180,render:(_,r)=><Button disabled={busy||!r.count} onClick={()=>onPrepare('caches',[r.id])}>预览清理清单</Button>}]}/>
  <p className="muted">{inventory.caches.notice}</p>
   <Button disabled={busy||!inventory.caches.count} onClick={()=>onPrepare('caches',inventory.caches.groups.filter(g=>g.count).map(g=>g.id))}>预览全部可清理缓存</Button></>}
 </>;
}
