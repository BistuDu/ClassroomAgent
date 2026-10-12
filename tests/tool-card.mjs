// Structural rendering regression; actual browser interaction is a separate acceptance gate.
import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {pathToFileURL,fileURLToPath} from 'node:url';
const dir=await mkdtemp(fileURLToPath(new URL('../data/ui-test-',import.meta.url)));
const output=await build({entryPoints:[fileURLToPath(new URL('../frontend/src/ToolCard.tsx',import.meta.url))],bundle:true,platform:'node',format:'esm',jsx:'automatic',external:['react','react/jsx-runtime'],write:false});
const file=dir+'/tool-card.mjs';await writeFile(file,output.outputFiles[0].text);
try{
 const {ToolCard}=await import(pathToFileURL(file));
 const saved=new Map();globalThis.localStorage={getItem:key=>saved.get(key)??null,setItem:(k,v)=>saved.set(k,v)};
 const node={id:'card',kind:'tool',source:'pi',sessionId:'sid',runId:'run',toolCallId:'call',firstSeq:1,lastSeq:2,status:'failed',createdAt:'2026-10-06T00:00:00Z',updatedAt:'2026-10-06T00:00:03Z',data:{name:'patch_stage',target:'s1',parametersComplete:true,parameters:{html:'<html>'+ 'HTML_LONG_MARKER'.repeat(3000)+'</html>',array:[1,2,3]},error:{message:'版本冲突'},durationMs:2000,preparationMs:1000}};
 await test('tool default collapsed; failure and bilingual name visible without fetching details',()=>{
  const html=renderToStaticMarkup(React.createElement(ToolCard,{node}));
  assert.match(html,/aria-expanded="false"/);assert.match(html,/patch_stage/);assert.match(html,/版本冲突/);
  assert.ok(!html.includes('HTML_LONG_MARKER'));assert.match(html,/2.0s/);
 });
 await test('expanded tool renders arguments above result, preserves full long fields and section folds',()=>{
  saved.set('toolDisclosure:compact:card:card','true');
  const html=renderToStaticMarkup(React.createElement(ToolCard,{node}));
  assert.ok(html.indexOf('tool-arguments')<html.indexOf('tool-result'));
  assert.equal((html.match(/HTML_LONG_MARKER/g)||[]).length,3000);assert.match(html,/参数准备 1.0s/);
  saved.set('toolDisclosure:compact:card:parameters','false');
  const folded=renderToStaticMarkup(React.createElement(ToolCard,{node}));
  assert.ok(!folded.includes('HTML_LONG_MARKER'));assert.match(folded,/aria-label="展开传入参数"/);
 });
 await test('TTS progress counts valid reused audio as completed',()=>{
  const progressNode={...node,status:'running',data:{...node.data,progress:{details:{segments:[{status:'ready'},{status:'reused'},{status:'not_run'}]}}}};
  const html=renderToStaticMarkup(React.createElement(ToolCard,{node:progressNode}));
  assert.match(html,/2\/3 段已保存/);
 });
}finally{await rm(dir,{recursive:true,force:true});delete globalThis.localStorage;}
