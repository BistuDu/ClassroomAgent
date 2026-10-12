import { useEffect, useRef, useState } from 'react';
import type { ClassroomDialogue, ClassroomEvent } from '../../contracts/generated';
import { api } from './api';

const TOOLS:Record<string,string>={read_classroom_context:'读取课堂证据',spotlight:'聚光高亮',laser:'激光指示',widget_setState:'调整实验参数',widget_highlight:'突出实验控件',widget_annotation:'添加实验注释',widget_reveal:'显示实验内容'};
const STATUS:Record<string,string>={active:'正在互动',waiting_user:'等待追问',completed:'已结束',interrupted:'已中断'};
type Row={id:string;kind:'message'|'tool';speaker:string|null;text:string;name?:string;parameters?:unknown;result?:unknown;status?:string;roundId?:string|null;callId?:string|null};
function project(events:ClassroomEvent[]):Row[]{
 const rows:Row[]=[],index=new Map<string,Row>();
 for(const e of events){
  if(['user_message','message_start','text_delta','message_end'].includes(e.kind)){
   const id=e.messageId||e.eventId;let row=index.get(id);
   if(!row){row={id,kind:'message',speaker:e.kind==='user_message'?'user':e.speakerId,text:''};index.set(id,row);rows.push(row);}
   if(e.kind==='text_delta')row.text+=String(e.data.text||'');
   if(e.kind==='message_end'||e.kind==='user_message'){row.text=String(e.data.text||'');row.status='完成';}
  }else if(e.kind==='tool_start'||e.kind==='tool_end'){
   const id=`${e.roundId}:${e.toolCallId}`;let row=index.get(id);
   if(!row){row={id,kind:'tool',speaker:e.speakerId,text:'',name:String(e.data.name||''),roundId:e.roundId,callId:e.toolCallId,status:'执行中'};index.set(id,row);rows.push(row);}
   if(e.kind==='tool_start')row.parameters=e.data.parameters;
   else{row.result=e.data.result;const result=e.data.result as Record<string,unknown>|undefined;row.status=result?.status==='failed'||result?.ok===false?'失败':'完成';}
  }
 }
 return rows.filter(row=>row.kind==='tool'||row.text||row.status!=='完成');
}
function ToolCard({row,did,page}:{row:Row;did:string;page:number|null}){
 const [detail,setDetail]=useState<Record<string,unknown>>(),[error,setError]=useState('');
 async function load(){if(!row.callId||!row.roundId)return;try{setDetail(await api(`/api/classroom-dialogues/${encodeURIComponent(did)}/tool-details?roundId=${encodeURIComponent(row.roundId)}&callId=${encodeURIComponent(row.callId)}`));setError('');}catch(e){setError(String(e));}}
 return <details className="classroom-tool" onToggle={e=>{if(e.currentTarget.open)void load();}}><summary><span>{TOOLS[row.name||'']||'教学工具'} <code>{row.name}</code></span><small>{page?`P${page} · `:''}{row.status}</small></summary><label>传入参数</label><pre>{JSON.stringify(detail?.parameters??row.parameters,null,2)??'尚未收到参数'}</pre><label>返回结果</label><pre>{JSON.stringify(detail?.result??row.result,null,2)??'等待真实执行回执'}</pre>{error&&<p role="alert">{error}</p>}</details>;
}
export function DialogueHistory({stageId,activeId,events,busy,onEnd}:{stageId:string;activeId:string|null;events:ClassroomEvent[];busy?:boolean;onEnd:(dialogueId:string)=>void}){
 const [dialogues,setDialogues]=useState<ClassroomDialogue[]>([]),[cache,setCache]=useState<Record<string,ClassroomEvent[]>>({}),[expanded,setExpanded]=useState<Record<string,boolean>>({}),[errors,setErrors]=useState<Record<string,string>>({});
 const loading=useRef(new Set<string>()),known=useRef(new Set<string>()),alive=useRef(true);
 useEffect(()=>{alive.current=true;let valid=true;
  async function refresh(){try{let cursor:string|null=null,all:ClassroomDialogue[]=[];do{const page: {items:ClassroomDialogue[];nextCursor:string|null}=await api(`/api/courses/${stageId}/classroom-dialogues?limit=100${cursor?'&cursor='+encodeURIComponent(cursor):''}`);all.push(...page.items);cursor=page.nextCursor;}while(cursor&&valid);
   if(!valid)return;setDialogues(all);setExpanded(old=>{const next={...old};for(const d of all)if(!known.current.has(d.id)){known.current.add(d.id);next[d.id]=d.id===activeId&&d.status!=='completed';}return next;});setErrors(old=>({...old,list:''}));
  }catch(e){if(valid)setErrors(old=>({...old,list:String(e)}));}}
  void refresh();const timer=setInterval(()=>void refresh(),2000);return()=>{valid=false;alive.current=false;clearInterval(timer);};
 },[stageId,activeId]);
 async function load(did:string){if(loading.current.has(did))return;loading.current.add(did);try{let after=0,all:ClassroomEvent[]=[];for(;;){const batch=await api<ClassroomEvent[]>(`/api/classroom-dialogues/${encodeURIComponent(did)}/history?after=${after}&limit=500`);all.push(...batch);if(batch.length<500)break;after=batch[batch.length-1].seq;}
  if(alive.current){setCache(old=>({...old,[did]:all}));setErrors(old=>({...old,[did]:''}));}
 }catch(e){if(alive.current)setErrors(old=>({...old,[did]:String(e)}));}finally{loading.current.delete(did);}}
 useEffect(()=>{for(const d of dialogues)if(expanded[d.id]&&!cache[d.id])void load(d.id);},[dialogues,expanded]);
 return <div className="classroom-dialogues">{!dialogues.length&&!errors.list&&<div className="classroom-welcome"><h3>和老师、同学一起学</h3><p>遇到疑问随时提问，对话会在这里保存。</p></div>}{errors.list&&<p className="error" role="alert">{errors.list}</p>}{dialogues.map(d=>{
  const unique=new Map<number,ClassroomEvent>();for(const e of [...(cache[d.id]||[]),...events.filter(e=>e.dialogueId===d.id)])unique.set(e.seq,e);
  const rows=project([...unique.values()].sort((a,b)=>a.seq-b.seq));
  const names:Record<string,string>={teacher:'老师',curious:'好奇宝宝',notetaker:'笔记员',thinker:'思考者',user:'你'};
  return <details key={d.id} className="classroom-dialogue" open={!!expanded[d.id]} onToggle={e=>{const open=e.currentTarget.open;setExpanded(old=>old[d.id]===open?old:{...old,[d.id]:open});if(open)void load(d.id);}}>
   <summary><span className="dialogue-kind">{d.type==='qa'?'问答':d.type==='discussion'?'讨论':'旧版历史'}</span><strong>{d.title}</strong><small>{d.startingPageNumber?`P${d.startingPageNumber} · `:''}{STATUS[d.status]}<time>{new Date(d.createdAt).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</time></small></summary>
   <div className="dialogue-content">{d.type==='legacy'&&<p className="dialogue-note">旧记录没有独立话题边界，按原学习记录保留。阅读不会恢复旧课堂。</p>}{d.endReason&&<p className="dialogue-note">{({topic_complete:'当前话题已讲完',user_continue:'你已选择继续讲课',user_navigate:'你已结束互动并切页',user_replay_course:'你已选择从头重播',user_stop:'你已结束当前互动',service_restart:'服务重启，等待明确恢复',execution_error:'执行中断，请查看错误',course_changed:'课件已更新，旧执行暂停',receipt_timeout:'执行回执超时',budget_reached:'本轮预算已达到，可追问或继续讲课',no_progress:'本轮重复无进展，已暂停等待你'} as Record<string,string>)[d.endReason]||d.endReason}</p>}{errors[d.id]&&<p className="error">{errors[d.id]} <button onClick={()=>void load(d.id)}>重试读取</button></p>}{!rows.length&&<p className="dialogue-note">正在读取记录…</p>}{rows.map(row=>row.kind==='message'?<article key={row.id} className={`classroom-message ${row.speaker==='user'?'user':''}`}><small>{names[row.speaker||'']||'课堂角色'}</small><div>{row.text||'正在组织回答…'}</div></article>:<ToolCard key={row.id} row={row} did={d.id} page={d.startingPageNumber}/>)}{d.id===activeId&&d.status!=='completed'&&<div className="dialogue-actions"><button disabled={busy} onClick={()=>onEnd(d.id)}>{d.type==='discussion'?'结束讨论':'结束问答'}</button></div>}</div>
  </details>;
 })}</div>;
}
