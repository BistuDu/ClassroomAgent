import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Action, Scene, Stage } from '../../contracts/generated';
import type { Session } from './types';
import { api, ApiError } from './api';
import { Player, type PlayerHandle } from './Player';
import { Slide } from './SceneView';
import { audioController } from './audio';
import { NarrationPanel, type Draft, type NarrationJob } from './NarrationPanel';
import { TeacherVoice } from './TeacherVoice';
import { Classroom } from './Classroom';
export type CoursePaneHandle={requestNavigation:(action:()=>void)=>boolean};
type PaneState={visible:boolean;consumed:boolean;selectedSceneId:string|null};
export function readPane(stageId:string):PaneState{try{return JSON.parse(localStorage.getItem('coursePane:'+stageId)||'null')||{visible:false,consumed:false,selectedSceneId:null};}catch{return {visible:false,consumed:false,selectedSceneId:null};}}
export function writePane(stageId:string,value:PaneState){localStorage.setItem('coursePane:'+stageId,JSON.stringify(value));}
function Thumbnail({stage,scene}:{stage:Stage;scene?:Scene}){return <div className="thumbnail-content">{scene?.type==='slide'?<Slide stage={stage} scene={scene}/>:scene?<div className="thumbnail-symbol"><span>{scene.type==='interactive'?'◉':'☑'}</span><small>{scene.type==='interactive'?'互动实验':'基础测验'}</small></div>:<div className="thumbnail-symbol"><span>…</span><small>待制作</small></div>}</div>;}
export const CoursePane=forwardRef<CoursePaneHandle,{stage?:Stage;session?:Session;selected:string|null;onSelect:(id:string)=>void;onSaved:(stage:Stage)=>void;onRefresh:()=>Promise<Stage>;onError:(s:string)=>void}>(function CoursePane({stage,session,selected,onSelect,onSaved,onRefresh,onError},ref){
 const player=useRef<PlayerHandle>(null),[allDrafts,setAllDrafts]=useState<Record<string,Draft>>(()=>{try{return JSON.parse(localStorage.getItem('narrationDrafts')||'{}');}catch{return {};}}),[pending,setPending]=useState<(()=>void)|null>(null),[busy,setBusy]=useState(false),[job,setJob]=useState<NarrationJob>();
 const [learning,setLearning]=useState(false);
 const draftsRef=useRef(allDrafts);draftsRef.current=allDrafts;
 const scene=stage?.scenes.find(s=>s.id===selected),prefix=stage&&scene?stage.id+':'+scene.id+':':'';
 const activeDrafts=Object.fromEntries(Object.entries(allDrafts).filter(([k])=>prefix&&k.startsWith(prefix)).map(([k,v])=>[k.slice(prefix.length),v]));
 const blocked=session?.state==='running'||!!session?.pendingQuestion||!!session?.operation||job?.status==='running';
 function updateDrafts(next:Record<string,Draft>){draftsRef.current=next;setAllDrafts(next);localStorage.setItem('narrationDrafts',JSON.stringify(next));}
 function requestNavigation(action:()=>void){if(Object.keys(activeDrafts).length){setPending(()=>action);return false;}audioController.stop();action();return true;}
 useImperativeHandle(ref,()=>({requestNavigation}));
 function navigate(id:string){if(id===selected)return true;return requestNavigation(()=>onSelect(id));}
 function draft(action:Action,text:string){if(!stage)return;const key=prefix+action.id,old=draftsRef.current[key];const next={...draftsRef.current};if(text===action.text)delete next[key];else next[key]={...old,text,baseText:old?.baseText??action.text,expectedRevision:old?.expectedRevision??stage.revision,requestId:crypto.randomUUID(),error:undefined};updateDrafts(next);}
 async function save(action:Action){if(!stage||!scene||!session)return;const key=prefix+action.id,d=draftsRef.current[key];if(!d)return;setBusy(true);
  try{const saved=await api<Stage>(`/api/courses/${stage.id}/scenes/${scene.id}/speech/${action.id}`,{method:'PATCH',body:JSON.stringify({sessionId:session.id,expectedRevision:d.expectedRevision,requestId:d.requestId,text:d.text})});
   const next={...draftsRef.current};if(next[key]?.requestId===d.requestId)delete next[key];
   for(const [other,value] of Object.entries(next)){if(other.startsWith(stage.id+':')&&value.expectedRevision===d.expectedRevision)next[other]={...value,expectedRevision:saved.revision};}
   updateDrafts(next);onSaved(saved);
  }catch(e){updateDrafts({...draftsRef.current,[key]:{...draftsRef.current[key],error:String(e)}});throw e;}finally{setBusy(false);}
 }
 async function saveAll(){if(!scene)return;for(const action of scene.actions){if(draftsRef.current[prefix+action.id])await save(action);}const action=pending;setPending(null);audioController.stop();action?.();}
 function discardAll(){const next={...draftsRef.current};for(const key of Object.keys(next))if(key.startsWith(prefix))delete next[key];updateDrafts(next);const action=pending;setPending(null);audioController.stop();action?.();}
 async function rebase(id:string){const latest=await onRefresh();const key=prefix+id,d=draftsRef.current[key];const action=latest.scenes.find(s=>s.id===scene?.id)?.actions.find(a=>a.id===id&&a.type==='speech');if(!action||!d){onError('目标讲稿已删除，草稿仍保留');return;}updateDrafts({...draftsRef.current,[key]:{...d,expectedRevision:latest.revision,baseText:action.text,requestId:crypto.randomUUID(),error:undefined}});}
 const polling=useRef(0);
 function jobKey(){return `narrationJob:${stage?.id}:${scene?.id}`;}
 const storedJob=stage&&scene?localStorage.getItem(jobKey()):null;
 useEffect(()=>{
  const token=++polling.current;setJob(undefined);if(!stage||!scene)return;
  const id=(session?.operation?.kind==='narration'?session.operation.id:null)||storedJob;if(!id)return;
  let timer:ReturnType<typeof setTimeout>|undefined;
  async function poll(){try{const value=await api<NarrationJob>(`/api/narration-jobs/${id}`);if(token!==polling.current)return;if(value.stageId===stage?.id&&value.sceneId===scene?.id)setJob(value);if(value.status==='running')timer=setTimeout(()=>void poll(),1000);else await onRefresh();}catch(e){if(token===polling.current){onError(String(e));timer=setTimeout(()=>void poll(),3000);}}}
  void poll();return()=>{polling.current++;clearTimeout(timer);};
 },[stage?.id,scene?.id,session?.operation?.id,storedJob]);
 async function setVoice(voice:string){if(!stage||!session)return;setBusy(true);audioController.stop();
  const key='teacherVoiceRequest:'+stage.id;let request={sessionId:session.id,expectedRevision:stage.revision,requestId:crypto.randomUUID(),voice};
  try{const prior=JSON.parse(localStorage.getItem(key)||'null');if(prior&&prior.sessionId===request.sessionId&&prior.voice===voice)request=prior;}catch{}
  localStorage.setItem(key,JSON.stringify(request));
  try{const saved=await api<Stage>(`/api/courses/${stage.id}/teacher-voice`,{method:'PATCH',body:JSON.stringify(request)});localStorage.removeItem(key);onSaved(saved);}
  catch(e){if(e instanceof ApiError&&e.status>=400&&e.status<500)localStorage.removeItem(key);throw e;}finally{setBusy(false);}
 }
 async function tts(actionIds?:string[],force=false){if(!stage||!scene||!session||Object.keys(activeDrafts).length)return;setBusy(true);audioController.stop();
  const storageKey='narrationRequest:'+stage.id+':'+scene.id;const body={sessionId:session.id,expectedRevision:stage.revision,requestId:crypto.randomUUID(),actionIds,force};
  let request=body;try{const prior=JSON.parse(localStorage.getItem(storageKey)||'null');if(prior&&prior.sessionId===body.sessionId&&!!prior.force===force&&JSON.stringify(prior.actionIds)===JSON.stringify(body.actionIds))request=prior;}catch{}
  localStorage.setItem(storageKey,JSON.stringify(request));
  try{const value=await api<NarrationJob>(`/api/courses/${stage.id}/scenes/${scene.id}/tts`,{method:'POST',body:JSON.stringify(request)});localStorage.setItem(jobKey(),value.id);localStorage.removeItem(storageKey);setJob(value);onSaved(await onRefresh());
  }catch(e){if(e instanceof ApiError&&e.status>=400&&e.status<500)localStorage.removeItem(storageKey);onError(String(e));}finally{setBusy(false);}
 }
 useEffect(()=>()=>audioController.stop(),[stage?.id]);
 const previousAudio=useRef<{sceneId:string|undefined;key:string}|null>(null);
 const audioKey=JSON.stringify({actions:scene?.actions,teacher:stage?.teacher});
 useEffect(()=>{if(previousAudio.current&&previousAudio.current.sceneId===scene?.id&&previousAudio.current.key!==audioKey)audioController.stop();previousAudio.current={sceneId:scene?.id,key:audioKey};},[audioKey,scene?.id]);
 const orphanDrafts=stage?Object.entries(allDrafts).filter(([key])=>key.startsWith(stage.id+':')&&!stage.scenes.some(s=>s.actions.some(a=>key===stage.id+':'+s.id+':'+a.id))):[];
 return <section className="course-pane">{stage?<><header className="course-header"><div><small>{stage.scenes.length} / {stage.approvedPlan.pages.length} 页已保存</small><h2>{stage.title}</h2></div><button className="primary" disabled={!scene||!scene.actions.some(a=>a.type==='speech')} onClick={()=>{if(Object.keys(activeDrafts).length){onError('先保存或放弃讲稿草稿，再开始学习');return;}audioController.stop();setLearning(true);}}>开始学习 ▷</button></header>
 <div className="course-content"><div className="thumbnail-list">{stage.approvedPlan.pages.map((p,i)=>{const s=stage.scenes.find(s=>s.planPageId===p.id);return <button key={p.id} className={`thumbnail ${s?.id===selected?'selected':''}`} disabled={!s} onClick={()=>s&&navigate(s.id)}><Thumbnail stage={stage} scene={s}/><small>{i+1}. {p.title}</small></button>;})}</div><div className="course-preview">{scene?<Player ref={player} key={stage.id} stage={stage} selectedSceneId={scene.id} onSelect={navigate}/>:<p className="empty">课程方案已确认，等待第一张页面保存。</p>}
 <details className="course-quality"><summary>课程就绪 · {stage.status==='ready'?'可播放':`${stage.outstanding.length} 项待完善`}</summary>{stage.outstanding.map((item,i)=><p key={i}>{item}</p>)}</details>
 {orphanDrafts.length>0&&<details className="notice"><summary>已移除讲稿的草稿仍保留</summary>{orphanDrafts.map(([key,d])=><pre key={key}>{d.text}</pre>)}</details>}
 <TeacherVoice stage={stage} disabled={busy||!!blocked||Object.keys(allDrafts).some(key=>key.startsWith(stage.id+':'))} onChange={setVoice}/>
 {scene&&<NarrationPanel stage={stage} scene={scene} drafts={activeDrafts} job={job} busy={busy} blocked={!!blocked} onDraft={draft} onSave={save} onDiscard={id=>{const next={...draftsRef.current};delete next[prefix+id];updateDrafts(next);}} onTts={(ids,force)=>void tts(ids,force)} onRefresh={onRefresh} onRebase={rebase} onError={onError}/>}</div></div></>:<div className="empty">还没有已保存的课件。确认课程方案后，第一张页面制作成功时会自动打开。</div>}
 {learning&&stage&&createPortal(<Classroom stage={stage} onClose={()=>setLearning(false)}/>,document.body)}
 {pending&&createPortal(<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="draft-title"><h3 id="draft-title">讲稿还有未保存修改</h3><p>保存后继续，或放弃当前页的修改。</p><div><button className="primary" disabled={busy||!!blocked} onClick={()=>void saveAll().catch(e=>onError(String(e)))}>保存后继续</button><button disabled={busy} onClick={discardAll}>放弃后继续</button><button onClick={()=>setPending(null)}>继续编辑</button></div></section></div>,document.body)}</section>;
});
