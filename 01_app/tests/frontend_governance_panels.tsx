import assert from 'node:assert/strict';
import {test} from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import LawPanel from '../frontend/src/components/governance/LawPanel';
import HealthPanel from '../frontend/src/components/governance/HealthPanel';
import {DatabasePanel,CachePanel} from '../frontend/src/components/governance/StoragePanels';
import VersionPanel from '../frontend/src/components/governance/VersionPanel';

test('governance panel rendering never initiates scans, recovery, cleanup or verification',()=>{
 let actions=0;const action=()=>{actions++;};
 const law=renderToStaticMarkup(<LawPanel models={[]} modelKey="" busy={false} onModel={action} onRefresh={action} onStart={action} onCancel={action} onOpenSession={action}/>);
 assert.match(law,/尚未读取法规清单/);assert.match(law,/全库核验/);
 const health=renderToStaticMarkup(<HealthPanel busy={false} onScan={action} onStop={action} onOpenSession={action} onOpenEvent={action} findingAction={()=>null}/>);
 assert.match(health,/运行健康与恢复/);assert.match(health,/手动检查/);
 const props={busy:false,onScan:action,onPrepare:action,onQuarantine:action};
 assert.match(renderToStaticMarkup(<DatabasePanel {...props}/>),/手动扫描副本/);
 assert.match(renderToStaticMarkup(<CachePanel {...props}/>),/手动扫描缓存/);
 const control={version:undefined,verify:undefined,watchVerify:false,verifyError:'',scanVersion:async()=>{action();},refreshVerify:async()=>{action();},startVerify:async()=>{action();},cancelVerify:async()=>{action();}};
 const version=renderToStaticMarkup(<VersionPanel control={control} visible={true} busy={false} act={async fn=>fn()} setNotice={action} setError={action}/>);
 assert.match(version,/手动核对一致性/);assert.match(version,/重启服务/);
 assert.doesNotMatch(version,/刷新校验进度/);assert.equal(actions,0);
});

test('version panel keeps the runtime table and the iteration records only',()=>{
 let actions=0;const action=()=>{actions++;};
 const version={scanned_at:'2026-09-18T09:00:00+08:00',boundary:'只读核对边界',elapsed_ms:12,
  build:{file:'BUILD_MANIFEST.json',present:true,version:'1.0.1',product:'NERO_Disclosure',schema_version:'nero.disclosure.manifest.v1',description:'',files_count:2,
   producer:{name:'NERO',label:'NERO 出品',fingerprint:'f'.repeat(16)},manifest_sha256:'a'.repeat(64),recorded_at:'2026-09-18T08:00:00+08:00',error:null},
  source:{available:true,commit:'60f5dc1',commit_date:'2026-09-18',subject:'隔离用例',local_changes:1},
  web:{root:'frontend',index:'index.html',present:true,bundle:'assets/index.js',assets:[],stale:false,notice:'',built_at:'2026-09-18T07:00:00+08:00'},
  engine:{name:'pi-agent-core',version:'0.85.1',installed:true,node:'v22.19.0',configuration_path:'config/model-contract.json',settings_revision:3,models:{total:2,enabled:1}},
  data:{databases:[],indexes:[]},runtime:{pid:91802,started_at:'2026-09-18T09:00:00+08:00',status:'current'},
  check:{mode:'quick',status:'current',checked:2,recorded:2,missing_count:0,changed_count:0,missing:[],changed:[],notice:''},
  rollback:[],changes:[],
  releases:{current:'1.0.1',releases:[{version:'1.0.1',released_at:'2026-09-18',kind:'程序更新',summary:'直接更新程序，保留原有资料。',
   items:['文稿列表只读取一次版本索引。','空答复不再被标记为完成。']}]}};
 const control={version,verify:undefined,watchVerify:false,verifyError:'',scanVersion:async()=>{action();},refreshVerify:async()=>{action();},startVerify:async()=>{action();},cancelVerify:async()=>{action();}};
 const markup=renderToStaticMarkup(<VersionPanel control={control} visible={true} busy={false} act={async fn=>fn()} setNotice={action} setError={action}/>);
 assert.match(markup,/运行服务与本地版本/);assert.match(markup,/版本迭代记录/);
 assert.match(markup,/NERO_Disclosure 1\.0\.1/);assert.match(markup,/文件存在性与大小一致/);
 assert.match(markup,/文稿列表只读取一次版本索引。/);assert.match(markup,/空答复不再被标记为完成。/);
 assert.match(markup,/程序更新 · 2026-09-18/);
 assert.doesNotMatch(markup,/与发布清单的一致性|前端入口引用|完整校验|数据与索引兼容性|历史备份与回退准备|变更记录/);
 assert.equal(actions,0);
});
