import {createHash} from 'node:crypto';
import type {SkillResources} from './skill-resources.ts';
export const SKILL_LOAD_LIMITS = {skills:3, bytes:120000};
export type RequiredSkill = {requestedId:string; canonicalId:string; path:string; bodyHash:string; bodyBytes:number; skillVersion:string};
// Independent tokens only; code, URLs and filesystem paths remain ordinary user text.
export function skillHandles(text:string):string[] {
 const clean=text.replace(/```[\s\S]*?```|`[^`\n]*`/g,part=>' '.repeat(part.length));
 const ids:string[]=[];
 for(const match of clean.matchAll(/(?:^|\s)\/(?:skill:)?([a-z0-9]+(?:-[a-z0-9]+)*)(?=$|\s|[，。！？、,!?；;])/g))
  if(!ids.includes(match[1]))ids.push(match[1]);
 return ids;
}
export function selectSkills(text:string,resources:SkillResources) {
 const required:RequiredSkill[]=[],unknown:string[]=[];
 for(const id of skillHandles(text)) {
  const item=resources.skills.find(s=>s.skillId===id&&!s.disableModelInvocation);
  const old=resources.legacyReads?.[id];
  const target=item?{requestedId:id,canonicalId:id,path:'SKILL.md',bodyHash:item.bodyHash,bodyBytes:item.bodyBytes,skillVersion:item.version}:old?{requestedId:id,...old}:undefined;
  if(!target){unknown.push(id);continue;}
  if(!required.some(r=>r.canonicalId===target.canonicalId&&r.path===target.path))required.push(target);
 }
 const unloaded=required.filter((_,i)=>i>=SKILL_LOAD_LIMITS.skills || required.slice(0,i+1).reduce((n,s)=>n+s.bodyBytes,0)>SKILL_LOAD_LIMITS.bytes);
 return {required,unknown,unloaded};
}
function payloads(messages:any[]):any[] {
 const out:any[]=[];
 for(const m of messages) {
  if(m.role!=='toolResult'||m.toolName!=='read_skill'||m.isError)continue;
  for(const block of m.content||[])if(block.type==='text')try{const d=JSON.parse(block.text);if(typeof d.text==='string')out.push(d);}catch{/* Non-resource/error text is not read evidence. */}
 }
 return out;
}
export function skillCoverage(messages:any[],resource:RequiredSkill,snapshotVersion:string) {
 const parts=payloads(messages).filter(d=>d.canonicalId===resource.canonicalId&&d.path===resource.path&&d.bodyHash===resource.bodyHash&&d.skillVersion===resource.skillVersion&&d.snapshotVersion===snapshotVersion).sort((a,b)=>a.offset-b.offset);
 let chars:string[]=[],total:number|undefined,ended=false;
 for(const d of parts) {
  const text=Array.from(d.text) as string[];
  if(!Number.isInteger(d.offset)||!Number.isInteger(d.total)||d.offset<0||d.offset>chars.length||d.offset+text.length>d.total)continue;
  if(total!==undefined&&total!==d.total)continue;
  total=d.total;
  const overlap=chars.length-d.offset;
  if(text.slice(0,overlap).some((c,i)=>chars[d.offset+i]!==c))continue;
  chars.push(...text.slice(overlap));
  if(d.hasMore===false&&d.nextOffset===null&&d.offset+text.length===total)ended=true;
 }
 const text=chars.join('');
 return {complete:ended&&total===chars.length&&Buffer.byteLength(text)===resource.bodyBytes&&createHash('sha256').update(text).digest('hex')===resource.bodyHash,nextOffset:chars.length,total};
}
export function actualReads(messages:any[],resources:SkillResources):RequiredSkill[] {
 const targets:RequiredSkill[]=[];
 for(const d of payloads(messages)) {
  if(d.snapshotVersion!==resources.version)continue;
  const item=resources.skills.find(s=>s.skillId===d.canonicalId);
  if(item&&d.path==='SKILL.md'&&d.bodyHash===item.bodyHash&&d.skillVersion===item.version&&!targets.some(t=>t.canonicalId===item.skillId))
   targets.push({requestedId:d.requestedId||item.skillId,canonicalId:item.skillId,path:'SKILL.md',bodyHash:item.bodyHash,bodyBytes:item.bodyBytes,skillVersion:item.version});
 }
 return targets;
}
export const skillReadOnlyTools=new Set(['read_skill','ask_user','list_stages','read_stage','grep_stage','list_scenes','list_voices','web_search','fetch_url']);
