import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import katex from 'katex';
import type { Element, Scene, Stage } from '../../contracts/generated';
import { simulationDocument, type SimulationBridge, type Reply } from './bridge';

function Chart({element:e}:{element:Element}) {
 const points=e.points||[],max=Math.max(1,...points.map(p=>p.y)),min=Math.min(0,...points.map(p=>p.y));
 const xMin=Math.min(...points.map(p=>p.x)),xMax=Math.max(xMin+1,...points.map(p=>p.x));
 const py=(v:number)=>160-(v-min)/(max-min)*130,px=(v:number)=>40+(v-xMin)/(xMax-xMin)*230;
 return <svg viewBox="0 0 320 200" width="100%" height="100%" style={{display:'block'}} role="img" aria-label={`${e.xLabel}与${e.yLabel}图表`}>
  <path d="M40 25 V160 H295" fill="none" stroke={e.color}/>
  {e.chartType==='bar'?points.map((p,i)=><g key={i}><rect x={45+i*245/points.length} y={Math.min(py(p.y),py(0))} width={180/points.length} height={Math.abs(py(p.y)-py(0))} fill={e.stroke}/><text x={45+i*245/points.length} y={180} fontSize={11}>{p.label||p.x}</text><text x={45+i*245/points.length} y={py(p.y)-5} fontSize={11}>{p.y}</text></g>):<>
   {e.chartType==='line'&&<polyline points={points.map(p=>`${px(p.x)},${py(p.y)}`).join(' ')} fill="none" stroke={e.stroke} strokeWidth="3"/>}
   {points.map((p,i)=><g key={i}><circle cx={px(p.x)} cy={py(p.y)} r={5} fill={e.stroke}/><text x={px(p.x)+7} y={py(p.y)-6} fontSize={11}>{p.label||p.y}</text></g>)}
  </>}
  <text x={310} y={198} textAnchor="end" fontSize={12}>{e.xLabel}</text><text x={8} y={18} fontSize={12}>{e.yLabel}</text>
 </svg>;
}
function Formula({text}:{text:string}) {
 const ref=useRef<HTMLDivElement>(null);
 useEffect(()=>{try{katex.render(text,ref.current!,{throwOnError:true,displayMode:true,trust:false});}catch(error){if(ref.current){ref.current.textContent=String(error);ref.current.dataset.renderError='formula';}}},[text]);
 return <div ref={ref}/>;
}
function VisualElement({element:e}:{element:Element}) {
 const style:CSSProperties={position:'absolute',left:e.x,top:e.y,width:e.width,height:e.height,color:e.color,background:e.type==='shape'?'transparent':e.background,fontSize:e.fontSize,fontWeight:e.fontWeight,textAlign:e.align,opacity:e.opacity,transform:`rotate(${e.rotation}deg)`,borderRadius:e.radius,boxSizing:'border-box'};
 let body;
 if(e.type==='image')body=<img src={`/api/media/${e.mediaId}`} alt={e.alt||e.text} style={{display:'block',width:'100%',height:'100%',objectFit:'contain'}}/>;
 else if(e.type==='formula')body=<Formula text={e.text}/>;
 else if(e.type==='chart')body=<Chart element={e}/>;
 else if(e.type==='table')body=<table style={{fontSize:e.fontSize,width:'100%',height:'100%',borderCollapse:'collapse'}}><tbody>{e.rows.map((r,i)=><tr key={i}>{r.map((v,j)=><td key={j} style={{padding:8,border:`1px solid ${e.stroke}`}}>{v}</td>)}</tr>)}</tbody></table>;
 else if(e.type==='shape')body=<svg width="100%" height="100%" style={{display:'block'}} viewBox={`0 0 ${e.width} ${e.height}`}>
  {e.shape==='ellipse'?<ellipse cx={e.width/2} cy={e.height/2} rx={Math.max(1,e.width/2-e.strokeWidth)} ry={Math.max(1,e.height/2-e.strokeWidth)} fill={e.background} stroke={e.stroke} strokeWidth={e.strokeWidth}/>:e.shape==='arrow'?<path d={`M0 ${e.height*.25} H${e.width*.65} V0 L${e.width} ${e.height/2} L${e.width*.65} ${e.height} V${e.height*.75} H0Z`} fill={e.background} stroke={e.stroke} strokeWidth={e.strokeWidth}/>:<rect x={e.strokeWidth/2} y={e.strokeWidth/2} width={Math.max(1,e.width-e.strokeWidth)} height={Math.max(1,e.height-e.strokeWidth)} rx={e.radius} fill={e.background} stroke={e.stroke} strokeWidth={e.strokeWidth}/>}
 </svg>;
 else if(e.type==='line')body=<svg width="100%" height="100%" style={{display:'block'}}><line x1="0" y1="0" x2="100%" y2="100%" stroke={e.stroke} strokeWidth={e.strokeWidth}/></svg>;
 else body=<div style={{whiteSpace:'pre-wrap',lineHeight:1.35,width:'100%',height:'100%'}}>{e.text}</div>;
 return <div data-element-id={e.id} data-element-type={e.type} style={style}>{body}</div>;
}
export function Slide({stage,scene,focus,laser}:{stage:Stage;scene:Scene;focus?:string;laser?:string}) {
 const container=useRef<HTMLDivElement>(null),[width,setWidth]=useState(1280);
 const [zoom,setZoom]=useState(false);
 useEffect(()=>{const observer=new ResizeObserver(entries=>setWidth(entries[0].contentRect.width));if(container.current)observer.observe(container.current);return()=>observer.disconnect();},[]);
 if(scene.content.type!=='slide')return null;
 const content=scene.content,scale=zoom?1:Math.min(1,width/content.width),target=content.elements.find(e=>e.id===focus),pointer=content.elements.find(e=>e.id===laser);
 return <div className="slide-shell" ref={container}>
  <button className="zoom" onClick={()=>setZoom(!zoom)} aria-label="放大幻灯片">{zoom?'适应窗口':'放大查看'}</button>
  <div className="slide-scroll"><div style={{width:content.width*scale,height:content.height*scale,position:'relative'}}>
   <div data-canvas style={{width:content.width,height:content.height,position:'absolute',transform:`scale(${scale})`,transformOrigin:'top left',background:stage.theme.background,color:stage.theme.foreground,fontFamily:stage.theme.fontFamily}}>
    {content.elements.map(e=><VisualElement key={e.id} element={e}/>)}
    {target&&<div className="spotlight" style={{left:target.x-8,top:target.y-8,width:target.width+16,height:target.height+16}}/>}
    {pointer&&<div className="laser" style={{left:pointer.x+pointer.width/2,top:pointer.y+pointer.height/2}}/>}
   </div>
  </div></div>
 </div>;
}
export function Simulation({scene,onBridge,onError}:{scene:Scene;onBridge:(bridge:SimulationBridge)=>void;onError:(error:string)=>void}) {
 const iframe=useRef<HTMLIFrameElement>(null);
 const simulationKey=JSON.stringify(scene.content);
 const instance=useMemo(()=>crypto.randomUUID(),[scene.id,simulationKey]);
 const pending=useRef(new Map<string,{resolve:(v:Reply)=>void;reject:(e:Error)=>void;timer:ReturnType<typeof setTimeout>}>());
 const [ready,setReady]=useState(false);
 const document=useMemo(()=>simulationDocument(scene,instance),[simulationKey,scene.id,instance]);
 const callbacks=useRef({onBridge,onError});callbacks.current={onBridge,onError};
 useEffect(()=>{
  setReady(false);
  let live=true;
  const request:SimulationBridge['request']=(type,payload={})=>new Promise((resolve,reject)=>{
   const requestId=crypto.randomUUID(),timer=setTimeout(()=>{pending.current.delete(requestId);reject(Error('实验反馈超时'));},5000);
   pending.current.set(requestId,{resolve,reject,timer});
   iframe.current?.contentWindow?.postMessage({channel:'openmaic',sceneId:scene.id,instanceId:instance,requestId,type,payload},'*');
  });
  const timeout=setTimeout(()=>callbacks.current.onError('实验未能在限定时间就绪'),7000);
  const receive=(event:MessageEvent)=>{
   const m=event.data;
   if(!live||event.source!==iframe.current?.contentWindow||!m||m.channel!=='openmaic'||m.sceneId!==scene.id||m.instanceId!==instance)return;
   if(m.type==='READY'){clearTimeout(timeout);setReady(true);callbacks.current.onBridge({request,instanceId:instance});}
   else if(m.type==='ACK'||m.type==='ERROR'){
    const waiter=pending.current.get(m.requestId);
    if(waiter){clearTimeout(waiter.timer);pending.current.delete(m.requestId);m.type==='ACK'?waiter.resolve(m):waiter.reject(Error(m.error));}
    else if(!m.requestId&&m.type==='ERROR')callbacks.current.onError(m.error);
   }
  };
  window.addEventListener('message',receive);
  return()=>{live=false;clearTimeout(timeout);window.removeEventListener('message',receive);for(const p of pending.current.values()){clearTimeout(p.timer);p.reject(Error('实验实例已切换'));}pending.current.clear();};
 },[scene.id,instance]);
 return <div data-simulation-ready={ready}><iframe title={scene.title} ref={iframe} sandbox="allow-scripts" referrerPolicy="no-referrer" srcDoc={document} className="simulation"/></div>;
}
export function SceneView({stage,scene,focus,laser,onBridge,onError,children}:{stage:Stage;scene:Scene;focus?:string;laser?:string;onBridge:(b:SimulationBridge)=>void;onError:(e:string)=>void;children?:React.ReactNode}) {
 return scene.type==='slide'?<Slide {...{stage,scene,focus,laser}}/>:scene.type==='interactive'?<Simulation {...{scene,onBridge,onError}}/>:<div className="quiz-sheet"><h2>{scene.title}</h2>{children|| (scene.content.type==='quiz'&&scene.content.questions.map(q=><section key={q.id}><h3>{q.text}</h3>{q.options.map(o=><p key={o.id}>{o.id}. {o.text}</p>)}</section>))}</div>;
}
