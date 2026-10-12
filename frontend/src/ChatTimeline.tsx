import { useLayoutEffect, useRef, useState } from 'react';
import { Streamdown } from 'streamdown';
import { createMathPlugin } from '@streamdown/math';
const math=createMathPlugin({singleDollarTextMath:true});
import { useStickToBottom } from 'use-stick-to-bottom';
import type { TimelineNode, Plan } from '../../contracts/generated';
import type { Question, Session } from './types';
import { statusNames } from './types';
import { ToolCard } from './ToolCard';
import { Icon } from './Icon';
import {SkillComposer} from './SkillComposer';
function ToolGroup({nodes}:{nodes:TimelineNode[]}){
 const [open,setOpen]=useState(()=>nodes.map(n=>localStorage.getItem('group:'+n.id)).find(v=>v!==null)!=='false');
 const active=nodes.some(n=>n.status==='running')?'正在执行':nodes.some(n=>n.status==='streaming')?'正在准备调用':'查看过程';
 const complete=nodes.filter(n=>n.status==='completed').length,failed=nodes.filter(n=>n.status==='failed').length;
 return <div className="tool-group"><button className="tool-group-heading" onClick={()=>{setOpen(!open);for(const node of nodes)localStorage.setItem('group:'+node.id,String(!open));}} aria-expanded={open}><Icon name="tool" size={14}/><strong>工具调用</strong><span className="tool-group-count">{nodes.length}</span><small>{active==='查看过程'?`${complete} 已完成${failed?` · ${failed} 失败`:''}`:active}</small><Icon name="chevron" size={14} className={open?'expanded':''}/></button><div className="tool-group-items" hidden={!open}>{open&&nodes.map(n=><ToolCard key={n.id} node={n}/>)}</div></div>;
}
function ReasoningCard({node}:{node:TimelineNode}){
 const [open,setOpen]=useState(()=>localStorage.getItem('reasoningExpanded:'+node.id)!=='false');
 const text=String(node.data.text||''),streaming=node.status==='streaming';
 return <article data-timeline-id={node.id} className={`reasoning-card status-${node.status}`}><button className="reasoning-heading" aria-expanded={open} onClick={()=>{setOpen(!open);localStorage.setItem('reasoningExpanded:'+node.id,String(!open));}}><Icon name="sparkles" size={14} className="reasoning-icon"/><strong>{node.source==='pi'?'思考过程':'思考摘要'}</strong><small>{streaming?'正在思考':statusNames[node.status]||node.status}</small><Icon name="chevron" size={14} className={open?'expanded':''}/></button><div hidden={!open} className="reasoning-content">{text?<div className="markdown"><Streamdown plugins={{math}} controls={false} isAnimating={streaming}>{text}</Streamdown></div>:<p className="muted">{streaming?'正在接收推理文本…':node.data.textAvailable?'本次未返回推理文本。':'此历史记录未保存推理文本。'}</p>}</div></article>;
}
function QuestionCard({node,active,busy,onAnswer}:{node:TimelineNode;active?:Question|null;busy:boolean;onAnswer:(approve:boolean,text?:string)=>void}){
 const d=node.data as Record<string,any>,plan=d.plan as Plan|null,pending=node.status==='waiting'&&active?.id===d.id;
 return <article data-timeline-id={node.id} className={`question ${pending?'pending':'answered'}`}><small className="question-state">{pending?'等待你的决定':node.status==='answered'?'已回答':'问题记录'}</small><h3>{d.question}</h3>{plan&&<details className="course-plan" open={pending}><summary>课程方案 <span>{plan.pages.length} 页 · {plan.audience}</span></summary><ul className="plan-objectives">{plan.objectives.map((t,i)=><li key={i}>{t}</li>)}</ul><ol className="plan-pages">{plan.pages.map(p=><li key={p.id}><div><strong>{p.title}</strong><span className="badge">{{slide:'幻灯片',interactive:'实验',quiz:'测验'}[p.type]}</span></div><p>{p.brief}</p></li>)}</ol></details>}
 {pending&&(plan?<><button className="primary" disabled={busy} onClick={()=>onAnswer(true)}>确认方案，开始制作</button><p className="muted">如需调整，请在下方输入修改意见。</p></>:<div className="question-options">{(d.options||[]).map((option:string)=><button key={option} disabled={busy} onClick={()=>onAnswer(false,option)}>{option}</button>)}</div>)}{d.answer&&<div className="question-answer"><small>你的回答{d.approved?' · 已批准方案':''}</small><p>{d.answer}</p></div>}</article>;
}
export function ChatTimeline({nodes,session,input,onInput,onSend,onStop,busy,error,before,loading,older,followToken,workbench}:{workbench?:string;nodes:TimelineNode[];session?:Session;input:string;onInput:(text:string)=>void;onSend:(approve?:boolean,text?:string)=>void;onStop:()=>void;busy:boolean;error:string;before:number|null;loading:boolean;older:()=>Promise<void>;followToken:number}){
 const {scrollRef,contentRef,isAtBottom,scrollToBottom}=useStickToBottom({initial:'instant',resize:'smooth'});
 const anchor=useRef<{id:string;offset:number}|null>(null);

 const canSend=!!input.trim()&&!busy&&session?.state!=='running'&&!session?.operation;
 useLayoutEffect(()=>{if(anchor.current&&scrollRef.current){const node=scrollRef.current.querySelector(`[data-timeline-id="${CSS.escape(anchor.current.id)}"]`);if(node)scrollRef.current.scrollTop+=node.getBoundingClientRect().top-anchor.current.offset;anchor.current=null;}},[nodes[0]?.id]);
 useLayoutEffect(()=>{if(followToken)void scrollToBottom();},[followToken]);
 const groups:TimelineNode[][]=[];for(const n of nodes){const last=groups.at(-1);if(n.kind==='tool'&&last?.[0].kind==='tool')last.push(n);else groups.push([n]);}
 const current=[...nodes].reverse().find(n=>n.runId===session?.runId&&(n.status==='running'||n.status==='streaming'));
 const activity=current?.data.phase==='compaction'?'正在整理上下文…':current?.kind==='tool'?(current.status==='running'?'正在执行工具…':current.data.phase==='ready'?'工具参数已就绪，等待执行…':'正在生成工具调用参数…'):current?.kind==='reasoning'?'正在思考…':current?.kind==='assistant'?'正在输出回复…':'正在生成回复…';
 async function load(){if(scrollRef.current){const top=scrollRef.current.getBoundingClientRect().top;const first=[...scrollRef.current.querySelectorAll<HTMLElement>('[data-timeline-id]')].find(n=>n.getBoundingClientRect().bottom>top);if(first)anchor.current={id:first.dataset.timelineId!,offset:first.getBoundingClientRect().top};}await older();}
 return <section className="chat">{workbench&&<div className="workbench-status" role="status" aria-label="工作台状态"><Icon name="panel" size={13}/><strong>工作台</strong><span>{workbench}</span></div>}<div ref={scrollRef} className="chat-scroll"><div ref={contentRef} className="timeline-content">
 {before!==null&&<button className="load-history" disabled={loading} onClick={()=>void load()}>{loading?'加载中…':'加载更早的过程'}</button>}
 {!nodes.length&&<div className="intro"><span className="intro-mark">✦</span><h2>你想教什么？</h2><p>一起确认方案，再制作课件、实验与老师讲解。</p><button onClick={()=>onInput('为初中生讲解光的折射，包含可操作的角度实验和基础测验，约10分钟。')}>光的折射 · 互动小课堂 ↗</button></div>}
 {groups.map(group=>{const n=group[0],d=n.data as Record<string,any>;if(n.kind==='tool')return group.length>1?<ToolGroup key={n.id} nodes={group}/>:<ToolCard key={n.id} node={n}/>;
 if(n.kind==='reasoning')return <ReasoningCard key={n.id} node={n}/>;
 if(n.kind==='question')return <QuestionCard key={n.id} node={n} active={session?.pendingQuestion} busy={busy} onAnswer={onSend}/>;
 if(n.kind==='user'||n.kind==='assistant')return <article key={n.id} data-timeline-id={n.id} className={`message ${n.kind}`}><small className="message-label">{n.kind==='assistant'&&<Icon name="sparkles" size={13}/>}<span>{n.kind==='user'?'你':'制作助手'}</span>{n.status==='streaming'&&<span className="message-streaming">正在回复</span>}</small><div className="markdown"><Streamdown plugins={{math}} controls={false} isAnimating={n.status==='streaming'}>{String(d.text||'')}</Streamdown></div>{d.legacy&&<small>旧版对话记录，段落边界详情不可用。</small>}</article>;
 if(n.kind==='course')return <article key={n.id} data-timeline-id={n.id} className="artifact-card"><span><Icon name="file" size={22}/></span><div><strong>{d.title||'课程成果'}</strong><small>{d.sceneCount===0?'课程已建立 · 尚无保存页面':`${d.sceneCount??'已有'} 页已保存 · 版本 ${d.revision}`}</small></div></article>;
 if(n.kind==='operation')return <article key={n.id} data-timeline-id={n.id} className="operation-card"><strong>{d.label||'用户操作'} · {statusNames[n.status]||n.status}</strong>{d.target&&<small>{d.target}</small>}{d.segments?.map((s:any)=><p key={s.actionId}>{s.actionId.slice(-8)} · {statusNames[s.status]||s.status}{s.error&&` · ${s.error.message}`}</p>)}</article>;
 return <article key={n.id} data-timeline-id={n.id} className="system-card">{d.error||d.message||`制作已结束${d.outstanding?.length?` · ${d.outstanding.length} 项待完善`:''}`}</article>;
 })}{session?.state==='running'&&<div className="stream-activity" role="status"><Icon name="clock" size={14}/>{activity}</div>}</div></div>{!isAtBottom&&<button className="return-latest" onClick={()=>void scrollToBottom()}>↓ 返回最新内容</button>}
 {error&&<p role="alert" className="error">{error}</p>}<form className="composer" onSubmit={e=>{e.preventDefault();if(!canSend)return;onSend();void scrollToBottom();}}><SkillComposer input={input} onInput={onInput} disabled={session?.state==='running'} canSend={canSend} placeholder={session?.pendingQuestion?'输入你的回答或修改意见…':'例如：/workshop-style 制作折射实验课…'}/><div><small id="composer-shortcut">{session?.state==='running'?'正在自主制作…':session?.pendingQuestion?'等待你的决定 · Enter 发送，Shift+Enter 换行':'Enter 发送 · Shift+Enter 换行'}</small>{session?.state==='running'?<button type="button" className="stop-button" onClick={onStop}><span/>停止制作</button>:<button className="primary send-button" disabled={!canSend}>发送<Icon name="arrow" size={14}/></button>}</div></form></section>;
}
