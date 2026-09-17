// Only invoked by the explicitly approved, isolated V2 script.
import { pathToFileURL } from 'node:url';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const [url,out,executable,modulePath,extra]=process.argv.slice(2);
const {chromium}=await import(pathToFileURL(modulePath).href);
const browser=await chromium.launch({executablePath:executable,headless:true});
const report={viewports:[],screenshots:[],checks:[],console_errors:[],external_requests:[]};
let page;
try {
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.route('**/*',route=>{if(new URL(route.request().url()).origin!==url){report.external_requests.push(route.request().url());return route.abort();}return route.continue();});
 page=await context.newPage();page.on('pageerror',e=>report.console_errors.push(e.message));
 const shot=async name=>{
   await page.evaluate(async()=>{window.scrollTo({top:0,left:0,behavior:'instant'});await Promise.allSettled(document.getAnimations().filter(a=>a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished));await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
   await page.screenshot({path:path.join(out,name+'.png'),fullPage:true,animations:'disabled'});report.screenshots.push(name+'.png');
   if(name==='desktop-audit'){await page.getByRole('dialog',{name:'执行全过程',exact:true}).screenshot({path:path.join(out,'audit-dialog.png'),animations:'disabled'});report.screenshots.push('audit-dialog.png');}
 };
 const pick=async(label,option)=>{const input=page.getByRole('combobox',{name:label,exact:true});await page.locator('.ant-select').filter({has:input}).locator('.ant-select-selector').click();const id=await input.getAttribute('aria-controls');await page.locator('.ant-select-dropdown').filter({has:page.locator(`[id="${id}"]`)}).getByTitle(option,{exact:true}).click();};
 const waitRound=async(count,status)=>{
   await page.waitForFunction(({count,status})=>{const nodes=[...document.querySelectorAll('.chat-round .round-meta button')];return nodes.length===count&&nodes.at(-1)?.textContent?.includes(status);},{count,status},{timeout:30000});
 };
 const send=async value=>{await page.getByRole('textbox',{name:'输入消息',exact:true}).fill(value);await page.getByRole('button').filter({hasText:/^(发送(消息|并执行|讨论|补充)|保存补充并继续)$/}).click();};
 await page.goto(url);await page.getByRole('button',{name:'选择北京交易所',exact:true}).click();await page.getByRole('button',{name:'进入北京基础层',exact:true}).click();
 await page.getByRole('heading',{name:'信息有据，披露有序',exact:true}).waitFor();await shot('desktop-empty');
 if(extra==='settings-only'){
  await page.getByRole('button',{name:'新建会话',exact:true}).first().click();await pick('选择绑定事项','V2 模拟董事会议案');
  await page.getByRole('textbox',{name:'事项与会话名称',exact:true}).fill('重命名后的披露会话');await page.getByRole('button',{name:'创建会话',exact:true}).click();
  await page.getByRole('heading',{name:'重命名后的披露会话',exact:true}).waitFor();
 }else{
 assert.equal(await page.getByRole('region',{name:'信息披露流程关系图'}).count(),1);
 assert.equal(await page.locator('.graph-node.running').count(),0);assert.equal(await page.locator('.graph-edge.executing').count(),0);
 assert.ok(await page.locator('.graph-edge.branch').count()>0&&await page.locator('.graph-edge.return').count()>0&&await page.locator('.graph-edge.evidence').count()>0);report.checks.push('graph_branches_and_static_idle');
 await page.getByRole('button',{name:'新建会话',exact:true}).first().click();
 await pick('选择绑定事项','V2 模拟董事会议案');await page.getByRole('textbox',{name:'事项与会话名称',exact:true}).fill('董事会披露 · 接口样例');
 await page.getByRole('button',{name:'创建会话',exact:true}).click();await page.getByRole('heading',{name:'董事会披露 · 接口样例',exact:true}).waitFor();
 await send('请先梳理当前事项');await waitRound(1,'本轮完成');report.checks.push('real_pi_chat_stream');await shot('desktop-chat');
 await pick('选择本轮模型','本地接口样例 B');await send('切换模型后的第二轮');await waitRound(2,'本轮完成');
 assert.ok((await page.locator('.chat-round').last().innerText()).includes('本地接口样例 B'));report.checks.push('model_switch_between_rounds');
 await send('慢速输出，用于停止测试');await page.getByRole('button').filter({hasText:'停止执行'}).waitFor();await page.getByRole('button').filter({hasText:'停止执行'}).click();await waitRound(3,'已停止');report.checks.push('cancel_running_round');
 await send('慢速输出，用于断线补读测试');await page.waitForFunction(()=>document.querySelector('.chat-round:last-of-type .round-meta button')?.textContent?.includes('执行中'));
 await context.setOffline(true);await new Promise(r=>setTimeout(r,700));await context.setOffline(false);await waitRound(4,'本轮完成');report.checks.push('stream_reconnect_replay');
 await pick('选择本轮工作方式','披露判断');await send('请列出还缺什么');await waitRound(5,'待补充');
 const human=page.getByRole('region',{name:'本轮需要你处理',exact:true});
 await human.getByText('会议实际召开日期是什么？',{exact:true}).waitFor();assert.equal(await human.getByText('请补充决议是否已经作出及资料来源。',{exact:true}).count(),1);
 await page.getByRole('button',{name:'去对话区补充',exact:true}).click();assert.equal(await page.getByRole('textbox',{name:'输入消息',exact:true}).evaluate(el=>el===document.activeElement),true);
 await shot('desktop-input-needed');report.checks.push('actual_questions_and_input_handoff');
 await page.route('**/api/chat/sessions/*/runs',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'本地测试启动失败'})}),{times:1});
 const answer='会议于 2026 年 9 月 11 日召开，已作出决议；资料来源为本地公开模拟会议记录。';
 await send(answer);await page.getByText(/补充已保存，本轮尚未启动/).waitFor();
 assert.equal(await page.getByRole('textbox',{name:'输入消息',exact:true}).inputValue(),answer);
 await page.getByRole('button').filter({hasText:/^保存补充并继续$/}).click();
 await page.locator('.graph-node.running').waitFor();assert.notEqual(await page.locator('.graph-node.running').evaluate(el=>getComputedStyle(el,'::before').animationName),'none');
 assert.notEqual(await page.locator('.graph-edge.executing .edge-pulse').evaluate(el=>getComputedStyle(el).animationName),'none');
 assert.ok(await page.locator('.graph-edge.executing .edge-pulse').evaluate(async el=>{const before=getComputedStyle(el).strokeDashoffset;await new Promise(resolve=>setTimeout(resolve,160));return before!==getComputedStyle(el).strokeDashoffset;}));report.checks.push('graph_edge_motion_observed');
 await page.getByRole('button',{name:'暂停动效',exact:true}).click();assert.equal(await page.locator('.graph-node.running').evaluate(el=>getComputedStyle(el,'::before').animationName),'none');
 await page.getByRole('button',{name:'开启动效',exact:true}).click();report.checks.push('graph_motion_pause_resume');
 await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>{const el=document.querySelector('.graph-node.running');return !!el&&getComputedStyle(el,'::before').animationName==='none';});
 report.checks.push('running_only_breathing','reduced_motion');await page.emulateMedia({reducedMotion:'no-preference'});await shot('desktop-running');
 await waitRound(6,'待人工确认');await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(el=>el.textContent==='审阅并确认当前版本'&&!el.disabled));
 const detail=await page.evaluate(async()=>{const sessions=await(await fetch('/api/chat/sessions?board=base&archived=false')).json();return await(await fetch('/api/chat/sessions/'+sessions[0].id)).json();});
 assert.equal(detail.event.summary.split(answer).length-1,1);report.checks.push('input_saved_once_and_explicit_retry');
 assert.equal(await page.locator('.graph-gate').count(),4);assert.equal(await page.locator('.graph-gate[aria-current="step"]').getAttribute('data-gate'),'assessment');
 assert.equal(await page.locator('.graph-edge[data-edge="assessment-plan"]').evaluate(el=>el.classList.contains('held')),true);
 assert.equal(await human.getByRole('button',{name:'审阅并确认当前版本',exact:true}).count(),1);
 await page.getByRole('button',{name:'Gate 2 · 规划确认，尚未到达',exact:true}).click();
 assert.equal(await human.getAttribute('data-handoff'),'gate-assessment');
 assert.equal(await page.getByRole('combobox',{name:'选择本轮工作方式',exact:true}).isDisabled(),true);report.checks.push('four_gates_and_pending_card_survives_inspection');
 await send('同意');await waitRound(7,'本轮完成');
 assert.equal(await page.locator('.graph-gate[aria-current="step"]').getAttribute('data-gate'),'assessment');
 assert.equal(await human.getAttribute('data-handoff'),'gate-assessment');report.checks.push('discussion_does_not_auto_confirm');
 await page.getByRole('button',{name:'Gate 1 · 判断确认，等待你确认',exact:true}).click();await shot('desktop-confirmation');
 await page.setViewportSize({width:390,height:844});await shot('narrow-human-gate');assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
 assert.ok(await human.getByRole('button',{name:'审阅并确认当前版本',exact:true}).isVisible());await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('button',{name:'审阅并确认当前版本',exact:true}).click();
 await page.getByRole('textbox',{name:'确认人姓名',exact:true}).fill('V2 模拟审阅者');await page.getByRole('textbox',{name:'确认或退回理由',exact:true}).fill('仅验证本机确认与状态切换，不构成真实人工验收。');
 await page.getByRole('button',{name:'保存本次确认',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.graph-node[aria-current="step"] strong')?.textContent==='文件与内容');report.checks.push('assessment_gate_then_browser_confirmation');
 assert.equal(await human.count(),0);assert.equal(await page.locator('.graph-gate[data-gate="assessment"]').getAttribute('data-state'),'done');report.checks.push('confirmation_clears_handoff_and_releases_next_node');
 assert.equal(await page.locator('.graph-node.running').count(),0);assert.equal(await page.locator('.graph-edge.executing').count(),0);
 await page.getByRole('button',{name:'模板适配，未开始',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.graph-inspector strong')?.textContent?.startsWith('模板适配'));
 assert.equal(await page.locator('.graph-node[aria-current="step"] strong').innerText(),'文件与内容');report.checks.push('graph_selection_does_not_advance_workflow');await shot('desktop-graph');
 await page.getByRole('navigation',{name:'主导航'}).getByRole('button').filter({hasText:'执行记录'}).click();await page.getByRole('row').filter({hasText:'披露判断'}).first().getByRole('button',{name:'查看全过程',exact:true}).click();
 await page.getByText('Skill 已注入 Pi 上下文',{exact:true}).waitFor();await shot('desktop-audit');report.checks.push('skill_and_tool_receipts');
 await page.getByRole('button',{name:'打开所属会话',exact:true}).click();await page.getByRole('heading',{name:'董事会披露 · 接口样例',exact:true}).waitFor();
 await page.getByRole('button',{name:'重命名',exact:true}).click();await page.getByRole('textbox',{name:'新的会话名称',exact:true}).fill('重命名后的披露会话');await page.getByRole('button',{name:'确定',exact:true}).click();
 await page.getByRole('heading',{name:'重命名后的披露会话',exact:true}).waitFor();report.checks.push('rename_session');
 await page.setViewportSize({width:390,height:844});await shot('narrow-console');report.viewports.push({width:390,height:844});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
 assert.ok(await page.locator('.graph-viewport').evaluate(el=>el.scrollWidth>el.clientWidth));
 await page.getByRole('button',{name:'确认稿归档，未开始',exact:true}).focus();await page.keyboard.press('Enter');assert.equal(await page.locator('.graph-node[data-node="archive"]').getAttribute('aria-pressed'),'true');report.checks.push('graph_narrow_scroll_and_keyboard');
 await page.setViewportSize({width:1440,height:1000});report.viewports.push({width:1440,height:1000});
 await page.getByRole('button',{name:'归档',exact:true}).click();await page.getByLabel('查看已归档',{exact:true}).check();
 await page.locator('.session-item').filter({hasText:'重命名后的披露会话'}).click();await page.getByRole('button',{name:'恢复',exact:true}).click();report.checks.push('archive_restore_session');
 }
 if(extra==='model-settings'||extra==='settings-only')await(await import('./validate_model_settings_browser.mjs')).checkModelSettings({page,report,shot,pick,url});
 assert.deepEqual(report.console_errors,[]);assert.deepEqual(report.external_requests,[]);report.status='passed';
} catch(error) {report.status='failed';report.error=String(error);if(page){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});await fs.writeFile(path.join(out,'failure-body.txt'),await page.locator('body').innerText().catch(()=>''));}throw error;}
finally {await fs.writeFile(path.join(out,'browser-report.json'),JSON.stringify(report,null,2)+'\n');await browser.close();}
