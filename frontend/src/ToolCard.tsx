import { useEffect, useId, useState } from 'react';
import type { TimelineNode } from '../../contracts/generated';
import { statusNames, toolNames } from './types';
import { api } from './api';
import { Icon } from './Icon';

type ResultDetails={available:boolean;result:unknown;parametersAvailable:boolean;parametersComplete:boolean;parameters:unknown;source?:string};
function useDisclosure(nodeId:string,section:'card'|'parameters'|'result',defaultOpen=false){
 // Earlier versions persisted automatically expanded cards. Start the new layout closed.
 const key=`toolDisclosure:compact:${nodeId}:${section}`;
 const read=()=>{try{const saved=localStorage.getItem(key);return saved===null?defaultOpen:saved==='true';}catch{return defaultOpen;}};
 const [state,setState]=useState(()=>({key,open:read()}));
 const open=state.key===key?state.open:read();
 useEffect(()=>{try{localStorage.setItem(key,String(open));}catch{}},[key,open]);
 return [open,()=>setState({key,open:!open})] as const;
}
function Payload({value}:{value:unknown}){
 const result=value as any;const artifacts=result?.details?.artifacts||[];
 return <><div className="tool-artifacts">{artifacts.map((a:any,i:number)=>a.mimeType?.startsWith('image/')?<a key={i} href={a.url} target="_blank" rel="noreferrer"><img src={a.url} alt="工具截图"/></a>:a.mimeType?.startsWith('audio/')?<audio key={i} controls src={a.url}/>:<a key={i} href={a.url}>媒体附件</a>)}</div><pre className="tool-payload">{typeof value==='string'?value:JSON.stringify(value,null,2)}</pre></>;
}
export function ToolCard({node}:{node:TimelineNode}){
 const d=node.data as Record<string,any>;
 const contentId=useId();
 const [cardOpen,toggleCard]=useDisclosure(node.id,'card');
 const [parametersOpen,toggleParameters]=useDisclosure(node.id,'parameters',true);
 const [resultOpen,toggleResult]=useDisclosure(node.id,'result',true);
 const active=node.status==='running'||node.status==='streaming',preparing=node.status==='streaming';
 const canLoad=!!node.toolCallId&&!!node.runId;
 const [clock,setClock]=useState(Date.now());
 const [details,setDetails]=useState<(ResultDetails&{version:number})|null>(null);
 const [loading,setLoading]=useState(false),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{if(!active)return;const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);},[active]);
 useEffect(()=>{
  if(!cardOpen||(!parametersOpen&&!resultOpen)||!d.detailsAvailable||!node.toolCallId||!node.runId||details?.version===node.lastSeq)return;
  const controller=new AbortController();setLoading(true);setError('');
  const query=new URLSearchParams({nodeId:node.id});
  void api<ResultDetails>(`/api/sessions/${encodeURIComponent(node.sessionId)}/tool-details?${query}`,{signal:controller.signal})
   .then(value=>{if(!controller.signal.aborted)setDetails({...value,version:node.lastSeq});})
   .catch(e=>{if(!controller.signal.aborted)setError(String(e));})
   .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[cardOpen,parametersOpen,resultOpen,active,node.id,node.sessionId,node.toolCallId,node.runId,node.lastSeq,retry]);
 const duration=d.durationMs??((active?clock:Date.parse(node.updatedAt))-Date.parse(d.executingAt||node.createdAt));
 const label=preparing?(d.phase==='ready'?'待执行':'准备调用'):node.status==='completed'&&d.conclusion==='发现问题'?'发现问题':statusNames[node.status]||node.status;
 const parameters=d.parametersComplete?d.parameters:details?.parametersAvailable?details.parameters:null;
 const result=details?.available?details.result:null;
 const failure=d.interruption||(node.status==='failed'&&d.error?.message);
 const progress=d.progress?.details?.segments as any[]|undefined;
 return <article data-timeline-id={node.id} className={`tool-card status-${node.status} ${cardOpen?'is-open':''} ${d.conclusion==='发现问题'?'found-issues':''}`}>
  <button type="button" className="tool-heading" onClick={toggleCard} aria-expanded={cardOpen} aria-controls={`${contentId}-details`} aria-label={`${cardOpen?'折叠':'展开'}工具：${toolNames[d.name]||'工具调用'} ${d.name||''}`}>
   <span className="tool-icon"><Icon name={active?'clock':node.status==='completed'?'check':'alert'} size={14}/></span>
   <span className="tool-identity"><span className="tool-title">{d.pageLabel&&<span className="tool-page-label">{d.pageLabel}</span>}<strong>{toolNames[d.name]||'工具调用'}</strong><code>{d.name||'unknown_tool'}</code></span>{d.target&&<small className="tool-target" title={d.target}>{d.target}</small>}{failure&&<small className="tool-failure-summary" title={failure}>{failure}</small>}</span>
   <span className="tool-state"><span className="tool-status">{label}</span><span className="tool-duration">{Math.max(0,duration/1000).toFixed(1)}s</span></span>
   <span className="tool-disclosure"><span>{cardOpen?'收起详情':'查看详情'}</span><Icon name="chevron" size={14} className={cardOpen?'expanded':''}/></span>
  </button>
  {progress&&active&&<p className="tool-live-progress">{progress.filter(s=>(s.status==='ready'||s.status==='reused')).length}/{progress.length} 段已保存{progress.some(s=>s.status==='failed')?' · 有段落失败':''}</p>}
  <div id={`${contentId}-details`} className="tool-details tool-stacked" hidden={!cardOpen}>
   {cardOpen&&<>
   <section className="tool-section tool-arguments" aria-label="传入参数">
    <button type="button" className="tool-section-heading" onClick={toggleParameters} aria-expanded={parametersOpen} aria-controls={`${contentId}-parameters`} aria-label={`${parametersOpen?'收起':'展开'}传入参数`}><strong>传入参数</strong><span>Arguments</span><span className="tool-disclosure"><Icon name="chevron" size={13} className={parametersOpen?'expanded':''}/></span></button>
    <div id={`${contentId}-parameters`} className="tool-section-body" hidden={!parametersOpen}>
    {parametersOpen&&(parameters!==null?<Payload value={parameters}/>:<p className="tool-empty">{preparing?`正在接收参数 · ${d.argumentChars??0} 字符`:active?'等待完整参数…':loading||canLoad&&!details&&!error?'正在读取完整参数…':'此记录未保存完整参数。'}</p>)}
    {details?.parametersAvailable&&!details.parametersComplete&&!d.parametersComplete&&<p className="tool-empty">旧记录的参数已被截取，Pi 会话中未找到可恢复的完整参数。</p>}
    </div>
   </section>
   <section className="tool-section tool-result" aria-label="返回结果">
    <button type="button" className="tool-section-heading" onClick={toggleResult} aria-expanded={resultOpen} aria-controls={`${contentId}-result`} aria-label={`${resultOpen?'收起':'展开'}返回结果`}><strong>返回结果</strong><span>Result</span><span className="tool-disclosure"><Icon name="chevron" size={13} className={resultOpen?'expanded':''}/></span></button>
    <div id={`${contentId}-result`} className="tool-section-body" hidden={!resultOpen}>
    {error&&<p className="tool-detail-error">{error}<button onClick={()=>setRetry(v=>v+1)}>重试读取</button></p>}
    {resultOpen&&(result!==null?<Payload value={result}/>:<p className="tool-empty">{loading||canLoad&&!active&&!details&&!error?'正在读取完整返回结果…':active?'等待工具返回…':'此调用未保存完整返回结果。'}</p>)}
    </div>
   </section>
   <footer className="tool-detail-footer"><span>{node.source==='legacy'?'旧版历史 · ':''}凭证已脱敏{d.preparationMs?` · 参数准备 ${(d.preparationMs/1000).toFixed(1)}s`:''}</span><code title={node.toolCallId||node.id}>{node.toolCallId||node.id}</code></footer>
   </>}
  </div>
 </article>;
}
