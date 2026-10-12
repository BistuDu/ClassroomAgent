import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { SceneView } from './SceneView';
import type { Scene, Stage } from '../../contracts/generated';
import type { SimulationBridge } from './bridge';

declare global {interface Window {openmaicPreview?:{ready:boolean;request:(type:string,payload?:Record<string,unknown>)=>Promise<unknown>}}}
export function Preview(){
 const params=new URLSearchParams(location.search),[stage,setStage]=useState<Stage>(),[error,setError]=useState(''),bridge=useRef<SimulationBridge | undefined>(undefined);
 const sceneId=params.get('scene'),token=params.get('token');
 useEffect(()=>{api<Stage>(`/api/preview/${params.get('stage')}?token=${encodeURIComponent(token||'')}`).then(value=>{
  if(!value.scenes.some(s=>s.id===sceneId))throw Error('预览页面不存在');
  setStage(value);
 }).catch(e=>setError(String(e)));return()=>{delete window.openmaicPreview;};},[]);
 const scene:Scene|undefined=stage?.scenes.find(s=>s.id===sceneId);
 useEffect(()=>{
  if(!scene)return;
  window.openmaicPreview={ready:scene.type!=='interactive',request:async(type,payload)=>{
   if(!bridge.current)throw Error('实验未就绪');return bridge.current.request(type,payload);
  }};
 },[scene]);
 return error?<div data-preview-error>{error}</div>:stage&&scene?<div className="preview" data-preview-ready={window.openmaicPreview?.ready}>
  <SceneView stage={stage} scene={scene} onBridge={b=>{bridge.current=b;if(window.openmaicPreview)window.openmaicPreview.ready=true;document.body.dataset.previewReady='true';}} onError={setError}/>
 </div>:<p>正在加载预览…</p>;
}
