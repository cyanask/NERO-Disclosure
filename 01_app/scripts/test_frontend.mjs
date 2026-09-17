/** Offline frontend regressions using the project's existing TypeScript/esbuild dependencies. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(path.join(root,'frontend/package.json'));
const {build}=require('esbuild');
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'nero-frontend-tests-'));
const results=[];
try{
 const files=fs.readdirSync(path.join(root,'tests')).filter(name=>name.startsWith('frontend_')&&/\.(tsx?|cjs)$/.test(name));
 const compiled=path.join(directory,'compiled');fs.mkdirSync(compiled);
 fs.symlinkSync(path.join(root,'frontend/node_modules'),path.join(compiled,'node_modules'),process.platform==='win32'?'junction':'dir');
 await build({absWorkingDir:root,entryPoints:['frontend/src/App.tsx','frontend/src/companyWorkspace.ts','frontend/src/modelSettings.ts','frontend/src/components/CompanyEntrance.tsx','frontend/src/components/LibraryPage.tsx'],outbase:'frontend',outdir:compiled,bundle:true,packages:'external',platform:'node',format:'cjs',jsx:'automatic',loader:{'.css':'empty'},logLevel:'silent'});
 for(const file of files){
  let args;
  if(file.endsWith('.cjs'))args=[path.join(root,'tests',file),file==='frontend_provider_groups.cjs'?path.join(compiled,'src'):compiled];
  else{
   const output=path.join(directory,file.replace(/\.tsx?$/,'.mjs'));
   await build({absWorkingDir:root,entryPoints:['tests/'+file],outfile:output,bundle:true,platform:'node',format:'esm',jsx:'automatic',nodePaths:[path.join(root,'frontend/node_modules')],banner:{js:"import { createRequire } from 'node:module'; const require=createRequire(import.meta.url);"},logLevel:'silent'});
   args=[output];
  }
  const result=spawnSync(process.execPath,args,{cwd:root,encoding:'utf8',timeout:30000,maxBuffer:4*1024*1024});
  results.push({file,status:result.status,stdout:result.stdout,stderr:result.stderr,error:result.error?.message});
 }
 console.log(JSON.stringify({passed:results.filter(r=>r.status===0).length,total:results.length,results},null,2));
 process.exitCode=results.some(r=>r.status!==0)?1:0;
}finally{fs.rmSync(directory,{recursive:true,force:true});}
