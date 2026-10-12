import { useEffect, useRef, useState } from 'react';
import type { Stage, WorkbenchEvent } from '../../contracts/generated';
import { api } from './api';
import { useTimeline } from './useTimeline';
import { SessionSidebar } from './SessionSidebar';
import { WorkspaceShell } from './WorkspaceShell';
import { ChatTimeline } from './ChatTimeline';
import { CoursePane, readPane, writePane, type CoursePaneHandle } from './CoursePane';
import { audioController } from './audio';
import { readPendingMessage, type PendingMessage } from './pendingMessage';
import type { Capability, CourseSummary, Session, SessionSummary } from './types';
export function App(){
 const [capabilities,setCapabilities]=useState<Record<string,Capability>>({}),[courses,setCourses]=useState<CourseSummary[]>([]),[sessions,setSessions]=useState<SessionSummary[]>([]),[session,setSession]=useState<Session>(),[stage,setStage]=useState<Stage>(),[selected,setSelected]=useState<string|null>(null),[showCourse,setShowCourse]=useState(false),[showSidebar,setShowSidebar]=useState(()=>localStorage.getItem('showSidebar')!=='false'),[input,setInput]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[followToken,setFollowToken]=useState(0),[workbench,setWorkbench]=useState(''),[pending,setPending]=useState<PendingMessage|null>(null);
 const active=useRef<string|undefined>(undefined),switchVersion=useRef(0),coursePane=useRef<CoursePaneHandle>(null),stageRef=useRef<Stage|undefined>(undefined),sessionRef=useRef<Session|undefined>(undefined),draftRef=useRef(input),sending=useRef(false),watermark=useRef(0),manualPreview=useRef(false),newCourses=useRef(new Set<string>()),refreshVersion=useRef(0),courseFetchVersion=useRef(0),updateVersions=useRef<Record<string,number>>({}),navigationTail=useRef<Promise<void>>(Promise.resolve());draftRef.current=input;
 function acceptSession(value:Session){sessionRef.current=value;setSession(value);}
 function acceptStage(value:Stage,explicit=false,auto=false){
  if(stageRef.current?.id===value.id&&stageRef.current.revision>value.revision)return;
  const pane=readPane(value.id);
  if(auto&&value.scenes.length&&!pane.consumed){pane.consumed=true;pane.visible=true;pane.selectedSceneId=value.scenes[0].id;}
  if(explicit&&value.scenes.length){pane.visible=true;pane.consumed=true;}
  if(!value.scenes.some(s=>s.id===pane.selectedSceneId))pane.selectedSceneId=value.scenes[0]?.id||null;
  writePane(value.id,pane);stageRef.current=value;setStage(value);setSelected(pane.selectedSceneId);setShowCourse(pane.visible&&value.scenes.length>0);
 }
 async function lists(){const [c,s]=await Promise.all([api<CourseSummary[]>('/api/courses'),api<SessionSummary[]>('/api/sessions')]);setCourses(c);setSessions(s);}
 async function load(id:string,explicit=false){
  const version=++switchVersion.current;++refreshVersion.current;++courseFetchVersion.current;
  if(active.current)localStorage.setItem('chatDraft:'+active.current,draftRef.current);
  audioController.stop();const value=await api<Session>(`/api/sessions/${id}`);
  const course=value.activeStageId?await api<Stage>(`/api/courses/${value.activeStageId}`):undefined;
  if(version!==switchVersion.current)return;
  active.current=id;manualPreview.current=false;newCourses.current.clear();setWorkbench(value.state==='failed'?'上次运行中断，已保存成果保留':value.state==='cancelled'?'上次运行已停止':value.state==='waiting_for_user'?'等待你回答当前问题':'');watermark.current=value.snapshotSeq||0;acceptSession(value);setInput(localStorage.getItem('chatDraft:'+id)||'');
  localStorage.removeItem('courseReferences:'+id);setPending(readPendingMessage(id));
  localStorage.setItem('openmaicSession',id);setError('');
  if(course)acceptStage(course,explicit);else{stageRef.current=undefined;setStage(undefined);setSelected(null);setShowCourse(false);}
 }
 async function refresh(){
  const sid=active.current,version=switchVersion.current,request=++refreshVersion.current;if(!sid)return;
  const value=await api<Session>(`/api/sessions/${sid}`);
  if(active.current!==sid||version!==switchVersion.current||request!==refreshVersion.current)return;
  if((value.snapshotSeq||0)>=watermark.current)acceptSession(value);
  if(value.activeStageId){const fetch=++courseFetchVersion.current;const course=await api<Stage>(`/api/courses/${value.activeStageId}`);if(active.current===sid&&version===switchVersion.current&&fetch===courseFetchVersion.current&&sessionRef.current?.activeStageId===course.id)acceptStage(course,false,!manualPreview.current&&newCourses.current.has(course.id));}
  void lists().catch(e=>setError(String(e)));
 }
 async function refreshCourse(targetId?:string){
  const sid=active.current,id=targetId||stageRef.current?.id,version=switchVersion.current;if(!id||!sid)throw Error('当前没有课程');
  const course=await api<Stage>(`/api/courses/${id}`);
  if(active.current===sid&&version===switchVersion.current&&sessionRef.current?.activeStageId===id)acceptStage(course);
  void lists().catch(e=>setError(String(e)));return course;
 }
 async function selectCourse(id:string,manual=true){
  const sid=active.current;if(!sid){await open(id);return;}
  const version=++switchVersion.current;++refreshVersion.current;++courseFetchVersion.current;
  if(manual)manualPreview.current=true;
  audioController.stop();
  const request=navigationTail.current.catch(()=>{}).then(()=>api<Session>(`/api/sessions/${sid}/active-course`,{method:'PATCH',body:JSON.stringify({stageId:id})}));
  navigationTail.current=request.then(()=>{});
  const value=await request;
  const course=await api<Stage>(`/api/courses/${id}`);
  if(active.current!==sid||version!==switchVersion.current)return;
  acceptSession(value);acceptStage(course,manual,!manual);void lists().catch(e=>setError(String(e)));
 }
 async function updateCourse(id:string){
  const sid=active.current,version=switchVersion.current,fetch=(updateVersions.current[id]||0)+1;updateVersions.current[id]=fetch;if(!sid)return;
  const course=await api<Stage>(`/api/courses/${id}`);
  if(sid!==active.current||version!==switchVersion.current||fetch!==updateVersions.current[id])return;
  if(!manualPreview.current&&newCourses.current.has(id)&&course.scenes.length&&!readPane(id).consumed){
   requestNavigation(()=>{if(!manualPreview.current)void selectCourse(id,false).catch(e=>setError(String(e)));});
  }else if(sessionRef.current?.activeStageId===id)acceptStage(course,false,!manualPreview.current&&newCourses.current.has(id));
  void refresh().catch(e=>setError(String(e)));
 }
 function event(event:WorkbenchEvent){const d=event.data as Record<string,any>;if(event.sessionId!==active.current)return;watermark.current=Math.max(watermark.current,event.seq);
  if(event.kind==='run_started'&&sessionRef.current)acceptSession({...sessionRef.current,state:'running',runId:d.runId,operation:{kind:'agent',id:d.runId}});
  if(event.kind==='question'&&sessionRef.current)acceptSession({...sessionRef.current,state:'waiting_for_user',pendingQuestion:d as any});
  if(event.kind==='question_answered'&&sessionRef.current)acceptSession({...sessionRef.current,pendingQuestion:null});
  if(event.source==='pi'&&event.kind==='tool_execution_end'&&d.toolName==='check_scene')void refresh().catch(e=>setError(String(e)));
  if(event.source==='workbench'){
   if(event.kind==='run_started')setWorkbench('制作运行已启动');
   if(event.kind==='course_created'){newCourses.current.add(d.stageId);setWorkbench(`已建立 ${d.title} · 等待页面保存`);}
   if(event.kind==='course_updated')setWorkbench(`${d.title||d.stageId} · 已保存 ${d.sceneCount??0} 页 · 版本 ${d.revision}`);
   if(event.kind==='user_operation')setWorkbench(`${courses.find(c=>c.id===d.stageId)?.title||d.stageId||''} · ${d.label||'手动操作'} · ${d.status}${d.segments?` · ${d.segments.filter((s:any)=>(s.status==='ready'||s.status==='reused')).length}/${d.segments.length} 段已保存`:''}`);
   if(event.kind==='message_submitted')setWorkbench('消息已接收，等待 SDK 开始处理');
   if(event.kind==='run_settled')setWorkbench(d.state==='waiting_for_user'?'等待你的决定':d.courses?.length?`本轮执行结束 · ${d.courses.map((c:any)=>`${c.title}：${c.taskReady??c.ready?'任务完成':`${c.outstanding.length} 项待处理`}${c.courseReady===false?` · 整课仍有 ${c.courseOutstandingCount??'其他'} 项待完善`:''}`).join('；')}`:`本轮执行结束${d.outstanding?.length?` · ${d.outstanding.length} 项待完善`:''}`);
   if(['run_failed','run_cancelled','interrupted'].includes(event.kind))setWorkbench(d.error||d.message||'制作已停止，已保存成果保留');
  }
  if(['course_created','course_updated'].includes(event.kind)&&d.stageId)void updateCourse(d.stageId).catch(e=>setError(String(e)));
  else if(['question','run_settled','run_failed','run_cancelled','interrupted','user_operation'].includes(event.kind))void refresh().catch(e=>setError(String(e)));
 }
 const timeline=useTimeline(session?.id,event,setError);
 useEffect(()=>{void api<Record<string,Capability>>('/api/capabilities').then(setCapabilities).catch(e=>setError(String(e)));void lists().catch(e=>setError(String(e)));const id=localStorage.getItem('openmaicSession');if(id)void load(id).catch(e=>{localStorage.removeItem('openmaicSession');setError(String(e));});return()=>audioController.stop();},[]);
 function requestNavigation(action:()=>void){if(coursePane.current)coursePane.current.requestNavigation(action);else action();}
 function changeInput(text:string){setInput(text);if(active.current)localStorage.setItem('chatDraft:'+active.current,text);}
 async function open(stageId?:string){try{const value=await api<Session>('/api/sessions',{method:'POST',body:JSON.stringify({stageId})});await load(value.id,!!stageId);await lists();}catch(e){setError(String(e));}}
 async function send(approve=false,option?:string,retry?:PendingMessage){
  const text=retry?.text??option??input;if((!text.trim()&&!approve&&!retry?.approve)||sending.current)return;
  if(!retry&&active.current&&readPendingMessage(active.current)){setError('上一条消息的发送状态尚未确认，请先重试原消息或放弃重试。');return;}
  sending.current=true;setBusy(true);setError('');
  const preview=stageRef.current?.id||null;manualPreview.current=false;newCourses.current.clear();
  try{let sid=active.current;if(!sid){const value=await api<Session>('/api/sessions',{method:'POST',body:'{}'});sid=value.id;await load(sid);}
   const question=sessionRef.current?.pendingQuestion,storageKey='pendingMessage:'+sid;
   const message:PendingMessage=retry??{messageId:crypto.randomUUID(),text,questionId:question?.id,planVersion:question?.planVersion,approve,stageId:preview};
   localStorage.setItem(storageKey,JSON.stringify(message));if(active.current===sid)setPending(message);
   await api(`/api/sessions/${sid}/messages`,{method:'POST',body:JSON.stringify(message)});localStorage.removeItem(storageKey);
   if(active.current===sid){setPending(null);if(!retry||draftRef.current===text)changeInput('');setFollowToken(t=>t+1);await refresh();}
  }catch(e){setError(String(e));}finally{setBusy(false);sending.current=false;}
 }
 function discardPending(){if(!active.current)return;localStorage.removeItem('pendingMessage:'+active.current);setPending(null);setError('');}
 function choose(id:string){if(!stageRef.current)return;manualPreview.current=true;const pane=readPane(stageRef.current.id);pane.selectedSceneId=id;writePane(stageRef.current.id,pane);setSelected(id);}
 function toggleCourse(){manualPreview.current=true;if(!stage?.scenes.length){setError('第一张有效页面保存后才会显示课件。');return;}const pane=readPane(stage.id);pane.visible=!showCourse;pane.consumed=true;writePane(stage.id,pane);setShowCourse(pane.visible);if(!pane.visible)audioController.stop();}
 function saved(value:Stage){if(value.id===sessionRef.current?.activeStageId)acceptStage(value);void lists().catch(e=>setError(String(e)));}
 return <WorkspaceShell showCourse={showCourse} showSidebar={showSidebar} onToggleCourse={toggleCourse} onToggleSidebar={()=>{setShowSidebar(!showSidebar);localStorage.setItem('showSidebar',String(!showSidebar));}}
 sidebar={<SessionSidebar sessions={sessions} courses={courses} capabilities={capabilities} current={session?.id} activeCourse={session?.activeStageId} linked={session?.linkedStageIds||[]} onNew={()=>requestNavigation(()=>void open())} onSession={id=>requestNavigation(()=>void load(id))} onCourse={id=>requestNavigation(()=>void selectCourse(id).catch(e=>setError(String(e))))} onCollapse={()=>{setShowSidebar(false);localStorage.setItem('showSidebar','false');}}/>}
 chat={<><div className="course-context-bar"><label>当前预览 <select aria-label="当前预览课程" value={session?.activeStageId||''} onChange={e=>requestNavigation(()=>void selectCourse(e.target.value).catch(e=>setError(String(e))))}><option value="" disabled>尚未选择课程</option>{courses.filter(c=>session?.linkedStageIds.includes(c.id)).map(c=><option key={c.id} value={c.id}>{c.title}</option>)}</select></label><span>直接说出课程名称与修改要求</span></div>{pending&&!busy&&<div className="pending-message" role="status"><div><strong>上一条消息待确认</strong><p>{pending.text||'确认课程方案'}</p><small>重试会发送原消息，保留发送时的课程提示。放弃仅停止本地重试，已接收的任务仍可继续运行。</small></div><div><button disabled={busy} onClick={()=>void send(false,undefined,pending)}>重试原消息</button><button disabled={busy} onClick={discardPending}>放弃重试</button></div></div>}<ChatTimeline nodes={timeline.nodes} session={session} input={input} onInput={changeInput} onSend={(approve,text)=>void send(approve,text)} onStop={()=>session?.runId&&void api(`/api/runs/${session.runId}/cancel`,{method:'POST',body:'{}'}).catch(e=>setError(String(e)))} busy={busy||!!pending} error={error} before={timeline.before} loading={timeline.loading} older={timeline.older} followToken={followToken} workbench={workbench}/></>}
 course={<CoursePane key={stage?.id||'empty'} ref={coursePane} stage={stage} session={session} selected={selected} onSelect={choose} onSaved={saved} onRefresh={()=>refreshCourse(stage?.id)} onError={setError}/>}/>;
}
