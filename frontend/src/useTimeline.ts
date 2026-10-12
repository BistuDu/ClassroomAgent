import { useEffect, useRef, useState } from 'react';
import type { TimelineNode, WorkbenchEvent } from '../../contracts/generated';
import { api } from './api';
export type TimelinePage={nodes:TimelineNode[];snapshotSeq:number;before:number|null;version:number};
export { mergeNodes } from './timelineMerge';
import { mergeNodes } from './timelineMerge';
export function useTimeline(sid:string|undefined,onEvent:(event:WorkbenchEvent)=>void,onError:(message:string)=>void){
 const [nodes,setNodes]=useState<TimelineNode[]>([]),[before,setBefore]=useState<number|null>(null),[loading,setLoading]=useState(false),[ready,setReady]=useState(false);
 const generation=useRef(0),handler=useRef(onEvent),error=useRef(onError);handler.current=onEvent;error.current=onError;
 useEffect(()=>{
  const token=++generation.current;let source:EventSource|undefined;setNodes([]);setBefore(null);setReady(false);setLoading(false);
  if(sid)void api<TimelinePage>(`/api/sessions/${sid}/timeline`).then(page=>{
   if(token!==generation.current)return;setNodes(page.nodes);setBefore(page.before);setReady(true);
   let water=page.snapshotSeq;source=new EventSource(`/api/sessions/${sid}/events?after=${water}`);
   source.onmessage=message=>{if(token!==generation.current)return;const event:WorkbenchEvent=JSON.parse(message.data);if(event.seq<=water)return;water=event.seq;setNodes(old=>mergeNodes(old,event.timeline));handler.current(event);};
  }).catch(e=>{if(token===generation.current)error.current(String(e));});
  return()=>{generation.current++;source?.close();};
 },[sid]);
 async function older(){if(!sid||before===null||loading)return;const token=generation.current;setLoading(true);
  try{const page=await api<TimelinePage>(`/api/sessions/${sid}/timeline?before=${before}`);if(token===generation.current){setNodes(old=>mergeNodes(old,page.nodes));setBefore(page.before);}}
  catch(e){error.current(String(e));}finally{if(token===generation.current)setLoading(false);}
 }
 return {nodes,before,loading,ready,older};
}
