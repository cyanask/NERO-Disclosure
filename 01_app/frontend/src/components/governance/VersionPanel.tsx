import {Alert,Button,Empty,Space,Table,Tag} from 'antd';
import ServiceRestartButton from '../ServiceRestartButton';
import {facts,size,stamp} from './display';
import type {Asset} from './versionTypes';
import {verifying} from './useVersionChecks';
import type {useVersionChecks} from './useVersionChecks';
const indexNames:Record<string,string>={current:'与当前代码一致',stale:'需要重建',missing:'尚未生成',invalid:'无法读取'};
export default function VersionPanel({control,visible,busy,act,setNotice,setError}:{control:ReturnType<typeof useVersionChecks>;visible:boolean;busy:boolean;act:(fn:()=>Promise<void>)=>Promise<void>;setNotice:(text:string)=>void;setError:(text:string)=>void}){
 const {version,verify,watchVerify,verifyError,scanVersion,refreshVerify,startVerify,cancelVerify}=control;
 const changeRows=version?.changes||[];
 return <>
  <div className="gov-toolbar"><div><h2>版本与变更</h2><p>核对运行服务、前端资源、索引与发布清单；查看历史备份及版本变化。</p></div>
   <Space wrap><Button loading={busy} onClick={()=>act(scanVersion)}>手动核对一致性</Button>
    {verifying(verify)?<><span>{watchVerify?'校验中，自动更新':'校验进度待恢复'} {verify?.processed??verify?.checked}/{verify?.total}</span>
      <Button danger disabled={busy||verify?.state==='cancelling'} onClick={()=>act(cancelVerify)}>停止校验</Button></>
      :<Button disabled={busy||!!verifyError||!version||!!version.build.error} onClick={()=>act(startVerify)}>完整校验（后台）</Button>}
    <ServiceRestartButton visible={visible} disabled={busy||verifying(verify)} onRestored={scanVersion} onNotice={setNotice} onError={setError}/></Space></div>
  {verifyError&&<Alert type="warning" message="校验进度连接中断" description={verifyError} action={<Button onClick={()=>void refreshVerify()}>重试连接</Button>}/>}
  {!version?<Empty description="点击“手动核对一致性”，读取发布清单、前端资源、Pi 引擎与数据表结构。"/>:<>
   <p className="gov-summary">核对于 {stamp(version.scanned_at)} · 用时 {version.elapsed_ms} ms · 记录 {version.check.checked} 个文件 <span>{version.check.notice}</span></p>
   {version.build.error&&<Alert type="warning" message={version.build.error}/>}
   {version.runtime?.status==='restart_required'&&<Alert type="warning" showIcon message="后端源码已变化，当前服务仍在运行启动时的版本。需在任务空闲时重启服务。"/>}
   <h3 className="gov-section">运行服务与本地版本</h3>
   {facts([['后端运行状态',version.runtime?.status==='current'?'与本次启动时的源码一致':version.runtime?.status==='restart_required'?'源码更新，等待重启':'尚未核对'],
    ['服务启动',version.runtime?`${stamp(version.runtime.started_at)} · 进程 ${version.runtime.pid}`:'—'],
    ['发布清单标注版本',`${version.build.product||'—'} ${version.build.version||''}`],['发布清单',`${version.build.file} · 记录 ${version.build.files_count??'—'} 个文件`],
    ['清单指纹',version.build.manifest_sha256?version.build.manifest_sha256.slice(0,16):''],['清单时间',stamp(version.build.recorded_at)],
    ['发布方',`${version.build.producer.label||version.build.producer.name||'—'} · 指纹 ${version.build.producer.fingerprint||'—'}`],
    ['源码提交',version.source.available?`${version.source.commit} · ${version.source.subject}`:(version.source.error||'—')],
    ['本地改动',version.source.local_changes===null||version.source.local_changes===undefined?'—':version.source.local_changes+' 项未提交'],
    ['前端入口',version.web.bundle||'未找到'],['前端构建时间',stamp(version.web.built_at)],
    ['Pi 引擎',`${version.engine.name} ${version.engine.version||''}${version.engine.installed?' · 已安装':' · 未就绪'}`],
    ['模型设置',`${version.engine.configuration_path} · r${version.engine.settings_revision} · 已启用 ${version.engine.models.enabled}/${version.engine.models.total}`]])}
   <h3 className="gov-section">与发布清单的一致性</h3>
   {version.check.status==='unavailable'?<Alert type="warning" message="发布清单不可用，不能判断一致性。"/>:version.check.missing_count||version.check.changed_count?<Alert type="warning" showIcon message={`相对发布清单：缺失 ${version.check.missing_count} 个、大小不一致 ${version.check.changed_count} 个文件。`}
     description="这些差异可能来自更新或清理，也可能来自意外改动；需要结合下方文件清单判断。"/>:<Alert type="info" showIcon message="文件存在性与大小一致；内容是否一致需执行完整校验。"/>}
   {!!version.check.changed.length&&<Table size="small" rowKey="path" dataSource={version.check.changed} pagination={{pageSize:6}} columns={[{title:'文件',dataIndex:'path',render:v=><span className="gov-path">{v}</span>},{title:'清单记录',dataIndex:'recorded',width:120},{title:'当前',dataIndex:'current',width:120}]}/>}
   {!!version.check.missing.length&&<Alert type="warning" message="清单记录但当前缺失的文件" description={<span className="gov-path">{version.check.missing.join('、')}</span>}/>}
   <Table size="small" rowKey="reference" dataSource={version.web.assets} pagination={false}
    columns={[{title:'前端入口引用',dataIndex:'reference',render:v=><span className="gov-path">{v}</span>},{title:'大小',width:120,render:(_,a)=>a.present?size(a.bytes):'缺失'},
     {title:'与清单比对',width:150,render:(_,a)=><Tag color={a.matches===true?'green':a.matches===false?'red':'orange'}>{a.matches===true?'一致':a.matches===false?'不一致':'清单未登记'}</Tag>},
     {title:'说明',render:(_,a)=>a.present?(a.recorded_sha256?'':'本次构建后新增或改名，发布清单未登记该资源'):'入口引用的文件不存在'}]}/>
   <p className="muted">{version.web.notice}</p>
   {verify&&<><h3 className="gov-section">完整校验结果</h3>
    <p className="gov-summary">{verifying(verify)?`${verify.state==='cancelling'?'正在停止':'进行中'}：已处理 ${verify.processed??verify.checked} / ${verify.total} 个文件，已读取 ${size(verify.bytes)}`
     :verify.state==='completed'?`已完成：校验 ${verify.checked} 个文件，用时 ${verify.elapsed_ms} ms，不一致 ${verify.mismatch_count} 个、缺失 ${verify.missing_count} 个`
     :verify.state==='cancelled'?'已停止本次校验，可重新发起。':verify.error||'上一次校验已中断，请重新执行。'}<span>开始于 {stamp(verify.started_at)}</span></p>
    {verify.manifest_sha256&&verify.manifest_sha256!==version.build.manifest_sha256&&<Alert type="warning" message="此完整校验对应较早的发布清单，请重新核验。"/>}
    {!!verify.mismatched.length&&<Table size="small" rowKey="path" dataSource={verify.mismatched} pagination={{pageSize:6}} columns={[{title:'文件',dataIndex:'path',render:v=><span className="gov-path">{v}</span>},{title:'清单哈希',dataIndex:'recorded',width:200},{title:'当前哈希',dataIndex:'current',width:200}]}/>}</>}
   <h3 className="gov-section">数据与索引兼容性</h3>
   <Table size="small" rowKey="path" dataSource={version.data.indexes} pagination={false} scroll={{x:1000}}
    columns={[{title:'索引',dataIndex:'kind',width:140},{title:'范围',dataIndex:'board',width:150},{title:'状态',width:150,render:(_,r)=><Tag color={r.status==='current'?'green':r.status==='invalid'?'red':'orange'}>{indexNames[r.status]||r.status}</Tag>},
     {title:'结构标记',width:250,render:(_,r)=><span className="gov-fact">{r.schema||'—'}{r.schema&&r.expected&&r.schema!==r.expected?`（当前代码要求 ${r.expected}）`:''}</span>},
     {title:'路径',dataIndex:'path',render:v=><span className="gov-path">{v}</span>}]}/>
   <h3 className="gov-section">历史备份与回退准备</h3>
   {version.rollback.length?<Table size="small" rowKey="path" dataSource={version.rollback} pagination={{pageSize:8}} scroll={{x:1050}} columns={[{title:'类型',dataIndex:'kind',width:210},{title:'位置',dataIndex:'path',render:v=><span className="gov-path">{v}</span>},{title:'大小',width:100,render:(_,r)=>size(r.bytes)},{title:'恢复状态',width:160,render:(_,r)=><Tag color={r.readiness==='unavailable'?'red':'orange'}>{r.readiness==='unavailable'?'空目录，无法恢复':'待核验兼容性'}</Tag>},{title:'时间',width:180,render:(_,r)=>stamp(r.at)}]}/>:<p className="muted">尚未发现历史备份。</p>}
   <p className="muted">找到备份不代表已经验证可回退。恢复前需检查内容完整性和版本兼容性；本页暂不提供一键回退。</p>
   <h3 className="gov-section">变更记录</h3>
   {changeRows.length?changeRows.map((row,index)=><p key={`${row.at}-${index}`} className="gov-fact">{stamp(row.at)} · {row.differences.join('；')}</p>):<p className="muted">尚无版本变更记录；下次核对发现发布版本、前端资源、引擎或数据结构变化时会记入此处。</p>}
   <p className="muted">{version.boundary}</p></>}
 </>;
}
