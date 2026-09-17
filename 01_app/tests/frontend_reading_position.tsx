import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {captureReadingPosition,restoreReadingPosition} from '../frontend/src/readingPosition';
import ConversationNavigation from '../frontend/src/components/ConversationNavigation';

// A paragraph moves down when the progress expands; the same visual offset must survive.
let scrollTop=300,progressHeight=0;
const rect=(top:number,height:number)=>({top,bottom:top+height,height,width:600});
const panel={get scrollTop(){return scrollTop;},getBoundingClientRect:()=>rect(90,616),querySelector:()=>({offsetHeight:70}),scrollTo:({top}:{top:number})=>{scrollTop=top;}};
const owner={dataset:{messageId:'run-A:message-1'},querySelectorAll:()=>[block]};
const block={getBoundingClientRect:()=>rect(450+progressHeight-scrollTop,80),closest:()=>owner};
const messages={getBoundingClientRect:()=>rect(200+progressHeight-scrollTop,1200),querySelectorAll:(selector:string)=>selector.startsWith('[data-')?[owner]:[block]};
const saved=captureReadingPosition(panel as any,messages as any)!;
assert.equal(saved.messageId,'run-A:message-1');assert.equal(saved.delta,-26);
progressHeight=500;scrollTop=0;
assert.equal(captureReadingPosition(panel as any,messages as any),undefined); // Repeated progress clicks cannot overwrite the bookmark.
restoreReadingPosition(panel as any,messages as any,saved);
assert.equal(scrollTop,800);assert.equal(block.getBoundingClientRect().top,150);
// A different session owns another bookmark; returning to A keeps its paragraph.
const savedB={...saved,messageId:'run-B:message-1',relative:450};
const perSession={A:saved,B:savedB};
restoreReadingPosition(panel as any,messages as any,perSession.A);assert.equal(scrollTop,800);
const replaced={...messages,querySelectorAll:()=>[]};
restoreReadingPosition(panel as any,replaced as any,perSession.A);assert.equal(scrollTop,800); // Replaced streaming markup falls back within the body.
const html=renderToStaticMarkup(<ConversationNavigation canRead progress={{tone:'human',title:'判断确认',detail:'等待人工确认',action:'review',actionLabel:'去审阅确认',animate:false,historical:false,activities:[]}} onProgress={()=>{}} onRead={()=>{}} onCompose={()=>{}}/>);
assert.match(html,/工作进展，判断确认/);assert.match(html,/回到正文/);assert.match(html,/继续提问/);
console.log('PASS: paragraph offset restored after progress expansion, per-session bookmarks, safe fallback and accessible navigation labels');
