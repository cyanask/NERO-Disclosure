import {Alert,Button,Empty,Space,Tag} from 'antd';
import ServiceRestartButton from '../ServiceRestartButton';
import {facts,stamp} from './display';
import type {useVersionChecks} from './useVersionChecks';
import type {Version} from './versionTypes';

/** The quick scan compares file presence and size only; it never compares content. */
function manifestSummary(version:Version){
 const check=version.check;
 if(check.status==='unavailable')return '发布清单不可用，未核对';
 if(check.missing_count||check.changed_count)return `缺失 ${check.missing_count} 个、大小不一致 ${check.changed_count} 个`;
 return '文件存在性与大小一致（未比对内容）';
}

/** Curated iteration records: the current version stays expanded, older ones collapse. */
function iterationRecords(value?:Version['releases']){
 const rows=value?.releases||[];
 if(!rows.length)return <p className="muted">本副本尚未登记版本迭代记录。请核对 config/release-notes.json 是否存在且可读。</p>;
 return <>{rows.map(row=><details key={row.version} className="gov-history" open={row.version===value?.current}>
  <summary><Tag color={row.version===value?.current?'gold':'default'}>{row.version}</Tag>{[row.kind,row.released_at].filter(Boolean).join(' · ')}</summary>
  {row.summary&&<p>{row.summary}</p>}
  <ul>{row.items.map((item,index)=><li key={`${row.version}-${index}`}>{item}</li>)}</ul>
 </details>)}</>;
}

export default function VersionPanel({control,visible,busy,act,setNotice,setError}:{control:ReturnType<typeof useVersionChecks>;visible:boolean;busy:boolean;act:(fn:()=>Promise<void>)=>Promise<void>;setNotice:(text:string)=>void;setError:(text:string)=>void}){
 const {version,scanVersion}=control;
 return <>
  <div className="gov-toolbar"><div><h2>版本与变更</h2><p>核对运行服务与本地版本；查看各版本迭代内容。</p></div>
   <Space wrap><Button loading={busy} onClick={()=>act(scanVersion)}>手动核对一致性</Button>
    <ServiceRestartButton visible={visible} disabled={busy} onRestored={scanVersion} onNotice={setNotice} onError={setError}/></Space></div>
  {!version?<Empty description="点击“手动核对一致性”，读取发布清单、运行服务与本地版本。"/>:<>
   {version.build.error&&<Alert type="warning" message={version.build.error}/>}
   {version.runtime?.status==='restart_required'&&<Alert type="warning" showIcon message="后端源码已变化，当前服务仍在运行启动时的版本。需在任务空闲时重启服务。"/>}
   <h3 className="gov-section">运行服务与本地版本</h3>
   {facts([['本次核对',`${stamp(version.scanned_at)} · 用时 ${version.elapsed_ms} ms · 记录 ${version.check.checked} 个文件`],
    ['与发布清单',manifestSummary(version)],
    ['后端运行状态',version.runtime?.status==='current'?'与本次启动时的源码一致':version.runtime?.status==='restart_required'?'源码更新，等待重启':'尚未核对'],
    ['服务启动',version.runtime?`${stamp(version.runtime.started_at)} · 进程 ${version.runtime.pid}`:'—'],
    ['发布清单标注版本',`${version.build.product||'—'} ${version.build.version||''}`],['发布清单',`${version.build.file} · 记录 ${version.build.files_count??'—'} 个文件`],
    ['清单指纹',version.build.manifest_sha256?version.build.manifest_sha256.slice(0,16):''],['清单时间',stamp(version.build.recorded_at)],
    ['发布方',`${version.build.producer.label||version.build.producer.name||'—'} · 指纹 ${version.build.producer.fingerprint||'—'}`],
    ['源码提交',version.source.available?`${version.source.commit} · ${version.source.subject}`:(version.source.error||'—')],
    ['本地改动',version.source.local_changes===null||version.source.local_changes===undefined?'—':version.source.local_changes+' 项未提交'],
    ['前端入口',version.web.bundle||'未找到'],['前端构建时间',stamp(version.web.built_at)],
    ['Pi 引擎',`${version.engine.name} ${version.engine.version||''}${version.engine.installed?' · 已安装':' · 未就绪'}`],
    ['模型设置',`${version.engine.configuration_path} · r${version.engine.settings_revision} · 已启用 ${version.engine.models.enabled}/${version.engine.models.total}`]])}
   <h3 className="gov-section">版本迭代记录</h3>
   {iterationRecords(version.releases)}
   <p className="muted">{version.boundary}</p></>}
 </>;
}
