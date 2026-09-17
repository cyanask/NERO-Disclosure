const assert=require('node:assert/strict');
const path=require('node:path');
const {createRequire}=require('node:module');
const fromOutput=createRequire(path.join(process.argv[2],'src/App.js'));
const React=fromOutput('react');
const {renderToStaticMarkup}=fromOutput('react-dom/server');
const {eventsForCompany,companyBoard,legacyCompany}=fromOutput('./companyWorkspace.js');
const Entrance=fromOutput('./components/CompanyEntrance.js').default;
const Library=fromOutput('./components/LibraryPage.js').default;
const company={board:'chinext',board_name:'创业板',company_name:'示例科技股份有限公司',stock_code:'300101'};
const records=Object.freeze([
 Object.freeze({id:'own',layer:'chinext',stock_code:'300101',artifacts:[{id:'own-file'}]}),
 Object.freeze({id:'other',layer:'chinext',stock_code:'300102',artifacts:[{id:'other-file'}]}),
 Object.freeze({id:'other-board',layer:'innovation',stock_code:'300101',artifacts:[]}),
 Object.freeze({id:'unbound',layer:'chinext',artifacts:[]}),
]);
assert.deepEqual(eventsForCompany(records,company).map(r=>r.id),['own']);
assert.deepEqual(eventsForCompany(records,company).flatMap(r=>r.artifacts).map(a=>a.id),['own-file']);
assert.equal(legacyCompany({company:null,companies:[company]},JSON.stringify({boardId:'chinext',companyCode:'300101'})),company);
assert.equal(legacyCompany({company:null,companies:[company]},JSON.stringify({boardId:'base',companyCode:'300101'})),undefined);
assert.equal(legacyCompany({company:null,companies:[company]},JSON.stringify({boardId:'chinext',companyCode:'300999'})),undefined);
const first=renderToStaticMarkup(React.createElement(Entrance,{workspace:{company:null,companies:[]},onEnter:()=>{},onSettings:()=>{}}));
assert.match(first,/公司全称/);assert.match(first,/证券代码/);assert.match(first,/联网核实并登记/);
assert.doesNotMatch(first,/选择您的市场|选择具体板块|exchange-card|board-option/);
assert.equal((first.match(/<input/g)||[]).length,2);
const existing=renderToStaticMarkup(React.createElement(Entrance,{workspace:{company,companies:[company]},onEnter:()=>{},onSettings:()=>{}}));
assert.match(existing,/选择已登记公司/);assert.match(existing,/进入工作台/);
const library=renderToStaticMarkup(React.createElement(Library,{board:companyBoard(company),companyCode:company.stock_code}));
assert.match(library,/法规库/);assert.match(library,/案例库/);assert.match(library,/模板库/);
assert.doesNotMatch(library,/class="collection-tab"[^>]*>黑名单案例库/);
console.log('PASS: company entry fields, saved company entry, company-specific event/delivery projection and library ownership');
