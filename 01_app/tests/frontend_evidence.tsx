import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import assert from 'node:assert/strict';
import {EvidenceContent} from '../frontend/src/components/ExecutionEvidence';
import {sourceLines,sourceUrl} from '../frontend/src/evidence';
import type {EvidenceSummary,SourceItem} from '../frontend/src/evidence';
const law:SourceItem={key:'a',id:'a',category:'laws',title:'测试规则',article:'第十条',instrument_id:'law',effective_from:'2026-01-01',url:'https://example.com/rule',states:['read','cited'],pages:[],run_ids:['r1']};
const lines=sourceLines([law,{...law,id:'b',key:'b',article:'第十一条'}]);
assert.equal(lines.length,1);assert.deepEqual(lines[0].articles,['第十条','第十一条']);
assert.equal(sourceLines([law,{...law,key:'new',effective_from:'2026-06-01'}]).length,2);
assert.equal(sourceLines([{...law,sha256:'a'},{...law,key:'new',sha256:'b'}]).length,2);
assert.equal(sourceUrl('javascript:alert(1)'),undefined);assert.equal(sourceUrl('https://a:b@example.com'),undefined);
const value:EvidenceSummary={session_id:'s',title:'本会话',board:'chinext',company:'300001',scope:'session',run_id:'',status:'completed',live:false,legacy:false,unresolved_citations:0,notice:'会话查阅记录',runs:[],groups:[
 ...['法律法规','案例库','黑名单库','历史公告','模板'].map((label,i)=>({key:['laws','cases','blacklist_cases','history','templates'][i],label,items:i===0?[law,{...law,id:'b',key:'b',article:'第十一条'}]:[],searched:i===1,empty_search:i===1,failed:i===2,unavailable:false,incomplete:i===3,checks:[]}))
]};
const html=renderToStaticMarkup(<EvidenceContent value={value}/>);
assert.equal((html.match(/class="evidence-category"/g)||[]).length,5);
assert.match(html,/第十条、第十一条/);assert.match(html,/已引用/);assert.match(html,/已检索，未命中/);assert.match(html,/查阅未完成/);assert.match(html,/已发起查阅/);assert.match(html,/本次未查阅/);
assert.doesNotMatch(html,/模型请求工具|建立进程|全部记录|snapshot/);
value.groups[1].items=[{...law,id:'case-a',key:'case-a',category:'cases',title:'同名公告',stock_code:'300001',article:undefined,states:['searched']},{...law,id:'case-b',key:'case-b',category:'cases',title:'同名公告',stock_code:'300002',article:undefined,states:['searched']}];
const names=renderToStaticMarkup(<EvidenceContent value={value}/>);
assert.match(names,/300001/);assert.match(names,/300002/);assert.match(names,/仅检索到/);
value.groups[3].checks=[{performed:true,method:'announcement_fields',scope:'all_registered',count:2,run_id:'r1',fields:['公告编号','会议日期'],items:[{id:'a',title:'公告甲'},{id:'b',title:'公告乙'}]}];
const checked=renderToStaticMarkup(<EvidenceContent value={value}/>);
assert.match(checked,/已比对本公司库内全部公告的公告编号、会议日期/);assert.doesNotMatch(checked,/全文核对通过/);
console.log('PASS: five evidence groups, article aggregation, version separation, truthful failure/empty states and safe source links');
