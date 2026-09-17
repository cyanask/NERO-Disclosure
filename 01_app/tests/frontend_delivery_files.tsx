import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import DeliveryTable,{deliveryRows} from '../frontend/src/components/DeliveryTable';
import type {SessionDocument} from '../frontend/src/components/DeliveryTable';
import type {DisclosureEvent} from '../frontend/src/types';

const document={document_id:'one',version:2,title:'董事会公告',filename:'董事会公告.docx',kind:'announcement',source_type:'runtime',
 created:1,sha256:'abc',bytes:3,pending:['表决结果'],review_status:'pending',available:true,session_id:'chat',session_title:'利润分配与战略投资',
 session_archived:false,download:'/api/chat/sessions/chat/documents/one/versions/2/file'} satisfies SessionDocument;
const events=[{id:'old',title:'原事项',artifacts:[{id:'one',filename:'历史交付.docx',verification:{status:'PASS'}}]}] as DisclosureEvent[];
const rows=deliveryRows(events,[document]);
assert.equal(rows.length,2);assert.notEqual(rows[0].id,rows[1].id);
assert.equal(rows[0].download,document.download);assert.equal(rows[0].status,'待补 1 项');
assert.equal(rows[1].download,'/api/events/old/artifacts/one/file');
const html=renderToStaticMarkup(<DeliveryTable rows={rows} busy={false} onSession={()=>{}} onEvent={()=>{}}/>);
assert.match(html,/董事会公告.docx/);assert.match(html,/利润分配与战略投资/);assert.match(html,/v2/);
assert.match(html,/待补 1 项/);assert.match(html,/下载 Word/);assert.match(html,/ant-btn-default/);
const missing=deliveryRows([],[{...document,available:false,session_archived:true}]);
const unavailable=renderToStaticMarkup(<DeliveryTable rows={missing} busy={false} onSession={()=>{}} onEvent={()=>{}}/>);
assert.match(unavailable,/文件不可用/);assert.match(unavailable,/会话已归档/);assert.doesNotMatch(unavailable,/href=/);
console.log('PASS: session Word and legacy deliveries, version and pending state, disabled unavailable download');
