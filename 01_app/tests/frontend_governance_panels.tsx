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
 assert.match(version,/手动核对一致性/);assert.match(version,/完整校验/);assert.match(version,/重启服务/);
 assert.doesNotMatch(version,/刷新校验进度/);assert.equal(actions,0);
});
