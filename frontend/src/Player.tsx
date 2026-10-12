import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { Scene, Stage, PlaybackCursor } from '../../contracts/generated';
import { SceneView } from './SceneView';
import type { SimulationBridge } from './bridge';
import { api } from './api';
import { audioController } from './audio';

export type Grade={status:string;results:{questionId:string;selected:string|null;correct:boolean|null;answer?:string;explanation?:string}[]};
export const emptyCursor=(sceneId:string):PlaybackCursor=>({sceneId,actionId:null,phase:'before',audioId:null,audioSignature:null,audioTime:0,experimentState:null,displayState:null,focus:null,laser:null,instanceId:null,playing:false});
export type PlayerHandle={stop:()=>void;play:()=>void;capture:(pause?:boolean)=>Promise<PlaybackCursor>;restore:(cursor:PlaybackCursor)=>Promise<void>;execute:(name:string,parameters:Record<string,unknown>)=>Promise<Record<string,unknown>>};
type Learning={id:string;consumed:Record<string,string>;grade?:Grade;busy?:boolean;control?:{label:string;disabled?:boolean;onClick:()=>void};onProgress:(cursor:PlaybackCursor,markerId?:string)=>Promise<void>;onPlay:(replay?:boolean)=>void;onPause:()=>void};
export const Player=forwardRef<PlayerHandle,{stage:Stage;selectedSceneId:string;onSelect:(id:string,autoplay?:boolean)=>boolean;learning?:Learning}>(function Player({stage,selectedSceneId,onSelect,learning},ref) {
 const page=Math.max(0,stage.scenes.findIndex(s=>s.id===selectedSceneId));
 const [playing,setPlaying]=useState(false),[paused,setPaused]=useState(false),[step,setStep]=useState(0),[error,setError]=useState('');
 const [focus,setFocus]=useState<string>(),[laser,setLaser]=useState<string>(),[caption,setCaption]=useState(''),[answers,setAnswers]=useState<Record<string,string>>({}),[grade,setGrade]=useState<Grade>();
 const control=useRef({generation:0,paused:false,step:0,bridge:undefined as SimulationBridge|undefined,audio:undefined as HTMLAudioElement|undefined,state:undefined as Record<string,unknown>|undefined,cancel:undefined as (()=>void)|undefined});
 const saved=useRef<PlaybackCursor|null>(null),focusRef=useRef<string|undefined>(undefined),laserRef=useRef<string|undefined>(undefined),playingRef=useRef(false);
 focusRef.current=focus;laserRef.current=laser;
 const learningRef=useRef(learning);learningRef.current=learning;
 const scene=stage.scenes[page];
 const priorScene=useRef<{id:string;key:string}|undefined>(undefined);
 useEffect(()=>{control.current.bridge=undefined;},[JSON.stringify(scene?.content)]);
 const sceneKey=JSON.stringify({content:scene?.content,actions:scene?.actions,theme:stage.theme,teacher:stage.teacher});
 function cancel(){const c=control.current;c.generation++;c.cancel?.();c.cancel=undefined;c.audio?.pause();c.audio=undefined;c.paused=false;c.state=undefined;audioController.release(stage.id);playingRef.current=false;setPlaying(false);setPaused(false);}
 function navigate(index:number,autoplay=false){if(!stage.scenes[index]||!onSelect(stage.scenes[index].id,autoplay))return false;audioController.stop();cancel();saved.current=null;control.current.step=0;setStep(0);setFocus(undefined);setLaser(undefined);setCaption('');setError('');setAnswers({});setGrade(undefined);return true;}
 useEffect(()=>()=>{cancel();},[stage.id]);
 useImperativeHandle(ref,()=>({stop:cancel,play:()=>void play(),capture,restore,execute}));
 useEffect(()=>{cancel();control.current.bridge=undefined;control.current.step=0;setStep(0);setFocus(undefined);setLaser(undefined);setCaption('');setAnswers({});setGrade(undefined);},[scene?.id]);
 useEffect(()=>{if(scene){if(priorScene.current?.id===scene.id&&priorScene.current.key!==sceneKey){cancel();control.current.step=0;setStep(0);setCaption('');setFocus(undefined);setLaser(undefined);}priorScene.current={id:scene.id,key:sceneKey};}},[sceneKey,scene?.id]);
 async function validWait(generation:number,ms=0){
  if(ms)await new Promise(resolve=>setTimeout(resolve,ms));
  while(control.current.paused&&control.current.generation===generation)await new Promise(resolve=>setTimeout(resolve,50));
  if(control.current.generation!==generation)throw Error('已切换执行');
 }
 async function bridge(generation:number){
  const started=Date.now();
  while(!control.current.bridge){await new Promise(resolve=>setTimeout(resolve,50));if(control.current.generation!==generation)throw Error('已切换执行');if(Date.now()-started>7000)throw Error('实验尚未就绪');}
  return control.current.bridge;
 }
 async function capture(interrupt=false):Promise<PlaybackCursor>{
  const c=control.current,version=c.generation,action=scene?.actions[c.step];
  const prior=saved.current?.actionId===action?.id?saved.current:null;
  const cursor:PlaybackCursor={...emptyCursor(scene.id),actionId:action?.id||null,phase:c.audio?'playing':c.step>=scene.actions.length?'page_end':prior?.phase||'before',audioId:c.audio?action?.audioId||null:prior?.audioId||null,audioSignature:c.audio?action?.audioSignature||null:prior?.audioSignature||null,audioTime:c.audio?.currentTime??prior?.audioTime??0,focus:focusRef.current||null,laser:laserRef.current||null,playing:playingRef.current&&!c.paused};
  if(interrupt){c.paused=true;c.audio?.pause();cursor.playing=false;}
  if(scene.type==='interactive'){
   const b=await bridge(c.generation);
   if(interrupt)await b.request('PAUSE');
   const reply=await b.request('SNAPSHOT');if(c.generation!==version)throw Error('旧播放现场已撤销');cursor.experimentState=reply.state;cursor.displayState=reply.displayState||null;cursor.instanceId=b.instanceId;
  }
  if(interrupt){saved.current=cursor;cancel();setPaused(true);}
  return cursor;
 }
 async function restore(cursor:PlaybackCursor){
  if(cursor.sceneId!==scene.id)throw Error('恢复页面与当前页面不一致');
  cancel();
  const index=cursor.actionId?scene.actions.findIndex(a=>a.id===cursor.actionId):cursor.phase==='page_end'?scene.actions.length:0;
  if(index<0)throw Error('原播放动作已不存在');
  const action=scene.actions[index];
  if(cursor.audioId&&(action?.audioId!==cursor.audioId||action.audioSignature!==cursor.audioSignature))throw Error('原语音已变化');
  if(scene.type==='interactive'){
   const b=await bridge(control.current.generation);
   if(!cursor.experimentState||!cursor.displayState)throw Error('缺少可恢复实验现场');
   await b.request('RESTORE',{state:cursor.experimentState,displayState:cursor.displayState});
   await b.request('PAUSE');
  }
  control.current.step=index+(cursor.phase==='after'?1:0);setStep(control.current.step);
  saved.current={...cursor,playing:false};setFocus(cursor.focus||undefined);setLaser(cursor.laser||undefined);setCaption('');
 }
 async function execute(name:string,parameters:Record<string,unknown>):Promise<Record<string,unknown>>{
  if(parameters.sceneId!==scene.id)throw Error('工具页面已切换');
  if(name==='spotlight'||name==='laser'){
   const id=String(parameters.elementId);
   if(scene.content.type!=='slide'||!scene.content.elements.some(e=>e.id===id))throw Error('指示元素不存在');
   if(name==='spotlight'){setFocus(id);focusRef.current=id;}
   else{setLaser(id);laserRef.current=id;await new Promise(resolve=>setTimeout(resolve,650));setLaser(undefined);laserRef.current=undefined;}
   return {elementId:id,displayed:true};
  }
  const types:Record<string,string>={widget_setState:'SET_STATE',widget_highlight:'HIGHLIGHT',widget_annotation:'ANNOTATION',widget_reveal:'REVEAL'};
  if(!types[name])throw Error('未知课堂演示工具');
  const b=await bridge(control.current.generation),reply=await b.request(types[name],parameters);
  return {state:reply.state,observation:reply.observation,instanceId:b.instanceId};
 }
 useEffect(()=>{
  if(!learning?.id)return;
  let pending=false;const timer=setInterval(()=>{if(pending)return;pending=true;void capture().then(cursor=>learningRef.current?.onProgress(cursor)).catch(()=>{}).finally(()=>{pending=false});},10000);
  return()=>clearInterval(timer);
 },[learning?.id,scene?.id]);
 useEffect(()=>{setGrade(learning?.grade);},[learning?.grade,scene?.id]);
 async function speech(action:Scene['actions'][number],generation:number){
  if(action.audioStatus!=='ready'||!action.audioId||!action.audioSignature)throw Error('当前讲解音频缺失或已过期，请返回制作台补全');
  setCaption(action.text);
  const audio=new Audio(`/api/media/${action.audioId}`);control.current.audio=audio;audioController.bind(stage.id,audio);
  const offset=saved.current?.actionId===action.id?saved.current.audioTime:0;
  if(offset){audio.onloadedmetadata=()=>{if(control.current.generation!==generation)return;audio.currentTime=Math.min(offset,Math.max(0,audio.duration-.05));if(learningRef.current)void capture().then(cursor=>learningRef.current?.onProgress(cursor)).catch(()=>{});};}
  await new Promise<void>((resolve,reject)=>{
   const cleanup=()=>{audio.onended=null;audio.onerror=null;control.current.cancel=undefined;};
   control.current.cancel=()=>{cleanup();reject(Error('已取消'))};
   audio.onended=()=>{cleanup();resolve()};
   audio.onerror=()=>{cleanup();reject(Error('音频无法加载'))};
   if(control.current.generation!==generation){cleanup();reject(Error('已切换执行'));return;}
   void audio.play().catch(e=>{cleanup();reject(Error('音频播放失败，请点击重试：'+e.message))});
  });
  control.current.audio=undefined;
  saved.current=null;
 }
 async function play(){
  if(!scene||playing)return;
  if(!scene.actions.some(a=>a.type==='speech')){setError('本页尚未生成讲稿与语音，请先补齐老师讲解');return;}
  if(control.current.step>=scene.actions.length){if(learning){if(page+1<stage.scenes.length)navigate(page+1,true);return;}control.current.step=0;setStep(0);}
  const c=control.current,generation=++c.generation;c.paused=false;playingRef.current=true;setPlaying(true);setPaused(false);setError('');
  try{
   audioController.claim(stage.id,cancel);
   if(scene.type==='interactive'){const b=await bridge(generation);await b.request('RESUME');}
   while(c.step<scene.actions.length){
    await validWait(generation);
    const action=scene.actions[c.step];
    if(action.type==='discussion'){
     if(learningRef.current&&!learningRef.current.consumed[action.id]){const cursor=await capture(true);await learningRef.current.onProgress(cursor,action.id);return;}
    }else if(action.type==='speech')await speech(action,generation);
    else if(action.type==='spotlight')setFocus(action.elementId||undefined);
    else if(action.type==='laser'){setLaser(action.elementId||undefined);await validWait(generation,650);setLaser(undefined);}
    else{
     const b=await bridge(generation);
     const types={widget_setState:'SET_STATE',widget_highlight:'HIGHLIGHT',widget_annotation:'ANNOTATION',widget_reveal:'REVEAL'};
     await b.request(types[action.type],{state:action.state,target:action.target,content:action.content});
    }
    await validWait(generation);c.step++;setStep(c.step);
    if(learningRef.current)await learningRef.current.onProgress(await capture());
   }
   if(c.generation!==generation)return;
   playingRef.current=false;setPlaying(false);setCaption('');
   if(scene.type!=='quiz'&&page+1<stage.scenes.length){
    // A new generation owns the next page; its playback is started by the effect below.
    autoNext.current=true;if(!navigate(page+1,true))autoNext.current=false;
   }
  }catch(e){if(c.generation===generation){playingRef.current=false;setPlaying(false);setError(String(e));}}
 }
 const autoNext=useRef(false);
 useEffect(()=>{if(autoNext.current){autoNext.current=false;void play();}},[page]);
 async function pause(){
  const c=control.current;c.paused=true;c.audio?.pause();setPaused(true);
  if(scene.type==='interactive')try{const b=await bridge(c.generation);const reply=await b.request('PAUSE');c.state=reply.state;}catch(e){setError(String(e));}
 }
 async function resume(){
  const c=control.current;
  try{
   if(scene.type==='interactive'){
    const b=await bridge(c.generation);
    if(c.state)await b.request('SET_STATE',{state:c.state});
    await b.request('RESUME');
   }
   c.paused=false;setPaused(false);
   if(c.audio)await c.audio.play();
  }catch(e){setError(String(e));}
 }
 async function submit(skip=false){
  try{
   const result=await api<Grade>(`/api/courses/${stage.id}/quiz-attempts`,{method:'POST',body:JSON.stringify({attemptId:crypto.randomUUID(),sceneId:scene.id,revision:stage.revision,answers,skip,...(learning?.id?{classroomId:learning.id}:{})})});
   setGrade(result);setError('');
   if(skip&&page+1<stage.scenes.length)navigate(page+1);
  }catch(e){setError(String(e));}
 }
 if(!scene)return <p className="empty">课程尚未生成页面。请在制作台继续制作。</p>;
 const quiz=scene.content.type==='quiz'?scene.content:null;
 return <div className="player">
  <div className="player-top"><div><small>P{page+1} / {stage.scenes.length}</small><h2>{scene.title}</h2></div><select aria-label="跳转页面" value={page} onChange={e=>navigate(Number(e.target.value))}>{stage.scenes.map((s,i)=><option key={s.id} value={i}>{i+1}. {s.title}</option>)}</select></div>
  <SceneView stage={stage} scene={scene} focus={focus} laser={laser} onBridge={b=>{control.current.bridge=b}} onError={e=>setError(e)}>
   {quiz&&quiz.questions.map(q=><section key={q.id}><h3>{q.text}</h3>{q.options.map(o=><label key={o.id} className="choice"><input type="radio" name={q.id} value={o.id} disabled={!!grade} checked={answers[q.id]===o.id} onChange={()=>setAnswers({...answers,[q.id]:o.id})}/>{o.text}</label>)}
    {grade&&grade.results.find(r=>r.questionId===q.id)&&(()=>{const result=grade.results.find(r=>r.questionId===q.id)!;return <div className="answer">{grade.status==='skipped'?'已跳过':result.correct?'回答正确':'回答错误'}{result.answer&&<p>正确选项：{q.options.find(o=>o.id===result.answer)?.text}</p>}<p>{result.explanation}</p></div>})()}
   </section>)}
  </SceneView>
  {caption&&<p className="caption">{caption}</p>}
  {error&&<p role="alert" className="error">{error}</p>}
  {paused&&scene.type==='interactive'&&<p className="notice">可以自由调整参数。继续讲解会恢复老师暂停前的演示状态。</p>}
  <div className="play-controls"><button disabled={page===0||learning?.busy} onClick={()=>navigate(page-1)}>上一页</button>
   {learning?.control?<button className="primary" disabled={learning.busy||learning.control.disabled} onClick={learning.control.onClick}>{learning.control.label}</button>:!playing?<button className="primary" disabled={learning?.busy} onClick={()=>learning?learning.onPlay(!error&&step>=scene.actions.length&&step>0):void play()}>{error?'重试当前步骤':step>=scene.actions.length&&step?'重新讲解':step?'从当前步骤播放':'开始讲解'}</button>:paused?<button className="primary" disabled={learning?.busy} onClick={()=>learning?learning.onPlay():void resume()}>{scene.type==='interactive'?'恢复演示并继续':'继续'}</button>:<button disabled={learning?.busy} onClick={()=>learning?learning.onPause():void pause()}>暂停</button>}
   {quiz&&!playing&&!grade&&<><button disabled={quiz.questions.some(q=>!answers[q.id])} onClick={()=>void submit()}>提交答案</button><button onClick={()=>void submit(true)}>跳过测验</button></>}
   <button disabled={page+1>=stage.scenes.length||learning?.busy} onClick={()=>navigate(page+1)}>{grade?'继续课堂':'下一页'}</button>{learning&&<button className="page-replay" title="重播当前页" aria-label="重播当前页" disabled={learning.busy} onClick={()=>learning.onPlay(true)}>↻</button>}<span className="muted">讲解步骤 {step} / {scene.actions.length}</span>
  </div>
  {!!scene.sourceIds.length&&<details><summary>本页参考资料</summary>{stage.sources.filter(s=>scene.sourceIds.includes(s.id)).map(s=><p key={s.id}><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a></p>)}</details>}
 </div>;
});
