import { useEffect, useRef, useState } from 'react';
import type { ClassroomSession, ClassroomEvent, PlaybackCursor, Stage } from '../../contracts/generated';
import { api } from './api';
import { Player, emptyCursor, type PlayerHandle, type Grade } from './Player';
import { audioController } from './audio';
import { DialogueHistory } from './DialogueHistory';

const STATES:Record<string,string>={paused:'等待开始',lecture:'正在讲课',discussion_prompt:'等待参与讨论',running:'角色正在回答',waiting_user:'等待你的追问',waiting_lesson:'话题已结束 · 等待继续讲课',waiting_tool:'等待演示反馈',waiting_audio:'正在准备或播放语音',audio_error:'语音需要处理',interrupted:'课堂已暂停',version_conflict:'课件已更新'};
function browserController(){let id=sessionStorage.getItem('classroom-controller');if(!id){id=crypto.randomUUID();sessionStorage.setItem('classroom-controller',id);}return id;}
type ExitPrompt={label:string;dialogueId:string|null;generation:number;resolve:(answer:boolean)=>void};

export function Classroom({stage,onClose}:{stage:Stage;onClose:()=>void}){
 const [session,setSession]=useState<ClassroomSession>(),[events,setEvents]=useState<ClassroomEvent[]>([]),[input,setInput]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[tab,setTab]=useState<'course'|'chat'>('course'),[grade,setGrade]=useState<Grade>();
 const [playerEpoch,setPlayerEpoch]=useState(0);
 const [exitPrompt,setExitPrompt]=useState<ExitPrompt>();
 const promptRef=useRef<ExitPrompt|undefined>(undefined);
 const current=useRef<ClassroomSession|undefined>(undefined),player=useRef<PlayerHandle>(null),controller=useRef(browserController()),seen=useRef(new Set<number>()),executed=useRef(new Set<string>()),view=useRef<HTMLDivElement>(null),following=useRef(true),alive=useRef(true),audio=useRef<HTMLAudioElement|undefined>(undefined),loaded=useRef(false),resumeKey=useRef(''),request=useRef<string>(crypto.randomUUID()),controlReady=useRef(false),executionEpoch=useRef(0);
 function interruptLocal(stopSound=true){executionEpoch.current++;if(stopSound)audioController.stop();resumeKey.current='';}
 function adopt(value:ClassroomSession,allowNew=false){if(!alive.current)return;const previous=current.current;if(previous&&!allowNew&&(previous.id!==value.id||previous.generation>value.generation||previous.updatedAt>value.updatedAt))return;current.current=value;setSession(value);}
 async function refresh(){if(!current.current)return;adopt(await api<ClassroomSession>(`/api/classrooms/${current.current.id}`));}
 async function open(){
  setBusy(true);setError('');
  try{const value=await api<ClassroomSession>('/api/classrooms',{method:'POST',body:JSON.stringify({stageId:stage.id,expectedRevision:stage.revision,requestId:request.current})});controlReady.current=false;adopt(value,true);localStorage.setItem('lastClassroom:'+stage.id,value.id);return value;}
  catch(e){setError(String(e));}finally{setBusy(false);}
 }
 useEffect(()=>{alive.current=true;void open();return()=>{alive.current=false;promptRef.current?.resolve(false);interruptLocal();const s=current.current;if(s&&controlReady.current){void api(`/api/classrooms/${s.id}/commands`,{method:'POST',body:JSON.stringify({requestId:crypto.randomUUID(),controllerId:controller.current,kind:'stop'}),keepalive:true}).catch(()=>{});}};},[stage.id]);
 useEffect(()=>{
  if(!session?.id)return;let active=true;const cid=session.id;executed.current.clear();loaded.current=false;resumeKey.current='';
  function append(batch:ClassroomEvent[]){const additions=batch.filter(e=>!seen.current.has(e.seq));for(const e of additions)seen.current.add(e.seq);if(active&&additions.length)setEvents(old=>[...old,...additions].sort((a,b)=>a.seq-b.seq));}
  let source:EventSource|undefined;
  async function connect(){let after=0;while(active){const batch=await api<ClassroomEvent[]>(`/api/classrooms/${cid}/history?after=${after}&limit=500`);append(batch);if(batch.length)after=batch[batch.length-1].seq;if(batch.length<500)break;}
   if(!active)return;source=new EventSource(`/api/classrooms/${cid}/events?afterSeq=${after}`);source.onmessage=e=>{if(!active)return;const event=JSON.parse(e.data) as ClassroomEvent;append([event]);if(!['text_delta','message_start'].includes(event.kind))void refresh().catch(err=>setError(String(err)));};source.onerror=()=>{if(active)setError('课堂连接暂时中断，正在重连；记录已保存');};
  }
  void connect().catch(e=>setError(String(e)));
  const timer=setInterval(()=>void refresh().catch(e=>setError(String(e))),1500);
  return()=>{active=false;source?.close();clearInterval(timer);};
 },[session?.id]);
 useEffect(()=>{if(following.current)view.current?.scrollTo({top:view.current.scrollHeight,behavior:'smooth'});},[events.length,events.at(-1)?.data]);
 useEffect(()=>{if(session&&['interrupted','version_conflict'].includes(session.state)){interruptLocal();player.current?.stop();}},[session?.state,session?.generation]);
 useEffect(()=>{
  if(!session||!player.current||loaded.current||controlReady.current)return;
  const s=session,scene=s.stage.scenes.find(p=>p.id===s.cursor.sceneId);let active=true;
  if(scene?.type==='interactive'&&!s.cursor.experimentState)return;
  setBusy(true);void player.current.restore(s.cursor).then(()=>{if(active)loaded.current=true;}).catch(e=>{if(active)setError(String(e));}).finally(()=>{if(active)setBusy(false);});
  return()=>{active=false;};
 },[session?.id,session?.cursor.sceneId]);
 useEffect(()=>{
  if(!session)return;const scene=session.stage.scenes.find(s=>s.id===session.cursor.sceneId);if(scene?.type!=='quiz'){setGrade(undefined);return;}
  let active=true;void api<Array<Grade&{classroomId?:string;sceneId:string}>>(`/api/courses/${stage.id}/quiz-attempts`).then(records=>{if(active)setGrade(records.find(r=>r.classroomId===session.id&&r.sceneId===scene.id));}).catch(()=>{});return()=>{active=false;};
 },[session?.id,session?.cursor.sceneId,JSON.stringify(session?.attempts)]);
 async function command(kind:string,extra:Record<string,unknown>={}){
  const s=current.current;if(!s)return;
  setBusy(true);setError('');try{const value=await api<ClassroomSession>(`/api/classrooms/${s.id}/commands`,{method:'POST',body:JSON.stringify({requestId:crypto.randomUUID(),controllerId:controller.current,kind,...extra})});controlReady.current=true;adopt(value);return value;}catch(e){setError(String(e));throw e;}finally{setBusy(false);}
 }
 async function progress(cursor:PlaybackCursor,markerId?:string,origin?:ClassroomSession){const s=origin||current.current;if(!s||!controlReady.current||current.current?.id!==s.id||current.current?.generation!==s.generation)return;const value=await api<ClassroomSession>(`/api/classrooms/${s.id}/progress`,{method:'POST',body:JSON.stringify({controllerId:controller.current,generation:s.generation,cursor,markerId})});adopt(value);}
 async function ask(){if(busy||!input.trim()||!player.current)return;try{interruptLocal(false);const text=input,cursor=await player.current.capture(true);audioController.stop();await command('question',{text,cursor});setInput('');following.current=true;}catch(e){setError(String(e));}}
 async function participate(){try{const cursor=await player.current!.capture(true);await command('join',{markerId:(session?.pending?.marker as any)?.id,cursor});}catch(e){setError(String(e));}}
 async function skipDiscussion(){try{interruptLocal();loaded.current=false;await command('skip',{markerId:(current.current?.pending?.marker as any)?.id});}catch(e){setError(String(e));}}
 async function continueLesson(){try{interruptLocal(false);const cursor=await player.current!.capture(true);audioController.stop();await command('continue',{cursor});}catch(e){setError(String(e));}}
 async function endDialogue(dialogueId:string){
  const s=current.current;if(!s||s.activeDialogueId!==dialogueId||busy)return;
  try{interruptLocal(false);const cursor=await player.current!.capture(true);audioController.stop();await command('stop',{cursor,confirmEnd:true,expectedDialogueId:dialogueId,expectedGeneration:s.generation});}catch(e){setError(String(e));}
 }
 async function exitPermission(label:string):Promise<Record<string,unknown>|null>{
  for(;;){const s=current.current;if(!s)return null;
   if(!s.activeDialogueId&&s.state!=='discussion_prompt')return {};
   if(promptRef.current)return null;
   const accepted=await new Promise<boolean>(resolve=>{const prompt={label,dialogueId:s.activeDialogueId,generation:s.generation,resolve};promptRef.current=prompt;setExitPrompt(prompt);});
   promptRef.current=undefined;setExitPrompt(undefined);if(!accepted)return null;
   const latest=await api<ClassroomSession>(`/api/classrooms/${s.id}`);adopt(latest);
   if(latest.activeDialogueId===s.activeDialogueId&&latest.generation===s.generation)return {confirmEnd:true,expectedDialogueId:s.activeDialogueId,expectedGeneration:s.generation};
   // A changed conversation needs its own confirmation; an ended one does not.
  }
 }
 async function start(replay=false){try{const s=current.current;if(!s||!player.current)return;if(replay){const permission=await exitPermission('重播当前页');if(!permission)return;interruptLocal(false);const actual=await player.current.capture(true);audioController.stop();const cursor={...emptyCursor(s.cursor.sceneId),experimentState:actual.experimentState,displayState:actual.displayState,instanceId:actual.instanceId};loaded.current=false;await command('navigate',{cursor,...permission});await player.current.restore(cursor);loaded.current=true;await command('start',{cursor});return;}const cursor=s.cursor.experimentState||s.stage.scenes.find(p=>p.id===s.cursor.sceneId)?.type!=='interactive'?s.cursor:await player.current.capture(true);await command('start',{cursor});}catch(e){setError(String(e));}}
 async function pause(){try{interruptLocal(false);const cursor=await player.current!.capture(true);audioController.stop();await command('pause',{cursor});}catch(e){setError(String(e));}}
 function navigate(sceneId:string,autoplay=false){
  void(async()=>{try{const permission=await exitPermission('切换页面');if(!permission)return;interruptLocal(false);await player.current?.capture(true);audioController.stop();loaded.current=false;await command('navigate',{cursor:emptyCursor(sceneId),...permission});setPlayerEpoch(epoch=>epoch+1);if(autoplay)await command('start');}catch(e){setError(String(e));}})();return false;
 }
 async function ack(s:ClassroomSession,pending:Record<string,any>,status:'completed'|'failed',result:Record<string,unknown>,instanceId?:string|null){
  const value=await api<ClassroomSession>(`/api/classrooms/${s.id}/ack`,{method:'POST',body:JSON.stringify({controllerId:controller.current,generation:s.generation,operationId:pending.operationId,sceneId:pending.sceneId,instanceId:instanceId??null,status,result})});adopt(value);
 }
 useEffect(()=>{
  if(!session||!player.current||!controlReady.current)return;const s=session,p=s.pending as Record<string,any>|null;
  if(s.state==='lecture'){
   const key=s.id+':'+s.generation+':'+s.cursor.sceneId;
   if(resumeKey.current!==key){resumeKey.current=key;void(async()=>{try{if(!loaded.current){let cursor=s.cursor;if(s.stage.scenes.find(p=>p.id===cursor.sceneId)?.type==='interactive'&&!cursor.experimentState){const fresh=await player.current!.capture(true);if(fresh.sceneId!==cursor.sceneId)throw Error('新实验页面尚未就绪');cursor={...cursor,experimentState:fresh.experimentState,displayState:fresh.displayState,instanceId:fresh.instanceId};}await player.current!.restore(cursor);loaded.current=true;}player.current!.play();}catch(e){setError(String(e));}})();}
   return;
  }
  if(!p?.operationId||!['waiting_tool','waiting_audio'].includes(s.state))return;
  if(p.kind==='audio'&&!p.audioId)return;
  const key=p.operationId+':'+s.generation;if(executed.current.has(key))return;executed.current.add(key);
  const epoch=executionEpoch.current;const active=()=>alive.current&&executionEpoch.current===epoch&&current.current?.generation===s.generation;
  void(async()=>{
   try{
    if(p.kind==='tool'){
     const receipt=await player.current!.execute(p.name,p.parameters);const cursor=await player.current!.capture();
     if(!active())return;
     await ack(s,p,'completed',receipt,cursor.instanceId);
    }else if(p.kind==='restore'){
     await player.current!.restore(p.cursor);loaded.current=true;const cursor=await player.current!.capture();
     if(!active())return;
     await ack(s,p,'completed',{restored:true,state:cursor.experimentState},cursor.instanceId);
     resumeKey.current='';
    }else if(p.kind==='audio'&&p.audioId){
     const sound=new Audio(`/api/media/${p.audioId}`),owner='classroom:'+s.id;audio.current=sound;
     await new Promise<void>((resolve,reject)=>{audioController.claim(owner,()=>{sound.pause();reject(Error('语音已暂停'))});audioController.bind(owner,sound);sound.onended=()=>resolve();sound.onerror=()=>reject(Error('音频无法加载'));void sound.play().catch(reject);});
     sound.onended=null;sound.onerror=null;audio.current=undefined;audioController.release(owner);
     if(!active())return;
     await ack(s,p,'completed',{ended:true});
    }
   }catch(e){if(active()){setError(String(e));try{await ack(s,p,'failed',{error:String(e)},p.instanceId);}catch(err){setError(String(err));}}}
  })();
 },[session?.state,session?.generation,session?.pending?.operationId,session?.pending?.audioId]);
 async function audioChoice(kind:string){const p=current.current?.pending;if(p?.operationId)executed.current.delete(String(p.operationId)+':'+current.current?.generation);try{await command(kind);}catch{}}
 async function close(){try{interruptLocal(false);const cursor=await player.current?.capture(true);audioController.stop();if(controlReady.current)await command('stop',cursor?{cursor}:{});}finally{onClose();}}
 const sceneId=session?.cursor.sceneId||stage.scenes[0]?.id;
 const currentRole=events.slice().reverse().find(e=>e.kind==='message_start')?.speakerId;
 const playbackControl=session?.state==='version_conflict'?{label:'课件已更新',disabled:true,onClick:()=>{}}:
  session?.activeDialogueId?{label:'互动中',disabled:true,onClick:()=>{}}:
  session?.state==='discussion_prompt'?{label:'等待参与讨论',disabled:true,onClick:()=>{}}:
  session?.returnCursor?{label:session.pending?.kind==='restore'?'恢复演示中…':'继续讲课',disabled:busy||session.pending?.kind==='restore',onClick:()=>void continueLesson()}:undefined;
 return <section className={`classroom-overlay tab-${tab}`} role="dialog" aria-modal="true" aria-label="互动课堂">
  <header className="classroom-header"><div><small>互动课堂 · {STATES[session?.state||'paused']}</small><h2>{session?.stage.title||stage.title}</h2></div><div className="classroom-header-actions"><button className="classroom-mobile-tab" aria-pressed={tab==='course'} onClick={()=>setTab('course')}>课件</button><button className="classroom-mobile-tab" aria-pressed={tab==='chat'} onClick={()=>setTab('chat')}>对话</button><button onClick={()=>void close()}>返回制作</button></div></header>
  <div className="classroom-body"><main className="classroom-course">{session&&<Player ref={player} key={`${session.id}:${playerEpoch}`} stage={session.stage} selectedSceneId={sceneId} onSelect={navigate} learning={{id:session.id,consumed:session.consumedDiscussions,grade,busy,control:playbackControl,onProgress:(cursor,markerId)=>progress(cursor,markerId,session),onPlay:replay=>void start(replay),onPause:()=>void pause()}}/>}</main>
   <aside className="classroom-chat"><div className="classroom-chat-heading"><strong>对话</strong><small>老师和同学 · 课堂互动</small></div><div className="classroom-roles">{session?.roles.map((r,i)=><div key={r.id} title={r.description} className={`classroom-role ${r.id===currentRole&&session.state==='running'?'speaking':''}`}><span>{['师','问','记','思'][i]}</span><strong>{r.name}</strong></div>)}</div>
    <div className="classroom-transcript" tabIndex={0} aria-label="课堂对话记录" ref={view} onScroll={()=>{const v=view.current;if(v)following.current=v.scrollHeight-v.scrollTop-v.clientHeight<90;}}><DialogueHistory stageId={stage.id} activeId={session?.activeDialogueId||null} events={events} busy={busy} onEnd={did=>void endDialogue(did)}/></div>
    {(error||session?.error)&&<p className="error" role="alert">{error||session?.error}</p>}
    {session?.state==='discussion_prompt'&&<section className="classroom-decision"><strong>{String((session.pending?.marker as any)?.topic||'一起讨论')}</strong><div><button className="primary" disabled={busy} onClick={()=>void participate()}>参与讨论</button><button disabled={busy} onClick={()=>void skipDiscussion()}>跳过</button></div></section>}
    {session?.state==='audio_error'&&<div className="classroom-decision"><button disabled={busy} onClick={()=>void audioChoice('retry_audio')}>重试语音</button><button disabled={busy} onClick={()=>void audioChoice('text_only')}>仅文字继续本段</button></div>}
    {(session?.state==='interrupted'||(!controlReady.current&&['waiting_tool','waiting_audio','audio_error','waiting_user'].includes(session?.state||'')))&&<button disabled={busy} onClick={()=>{executed.current.clear();void player.current?.capture(true).then(cursor=>command('resume_interaction',{cursor})).catch(e=>setError(String(e)));}}>恢复互动（不重复已完成操作）</button>}
    <form className="classroom-input" onSubmit={e=>{e.preventDefault();void ask();}}><textarea aria-label="课堂提问" placeholder="向老师提问，或参与讨论…" value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void ask();}}}/><button className="primary" disabled={busy||!session||!input.trim()} type="submit">发送</button></form>
   </aside></div>
  {exitPrompt&&<div className="classroom-confirm-backdrop"><section className="classroom-confirm" role="alertdialog" aria-modal="true" aria-labelledby="classroom-confirm-title"><h3 id="classroom-confirm-title">结束当前互动后{exitPrompt.label}？</h3><p>当前问答或待参与讨论将结束，已发生的对话保留。取消会留在当前页，互动继续。</p><div><button autoFocus onClick={()=>exitPrompt.resolve(false)}>取消</button><button className="primary" onClick={()=>exitPrompt.resolve(true)}>结束互动后{exitPrompt.label}</button></div></section></div>}
 </section>;
}
