import { useState, type KeyboardEvent } from 'react';
import type { Capability, CourseSummary, SessionSummary } from './types';
import { Icon } from './Icon';
export function SessionSidebar({sessions,courses,capabilities,current,activeCourse,linked,onNew,onSession,onCourse,onCollapse}:{sessions:SessionSummary[];courses:CourseSummary[];capabilities:Record<string,Capability>;current?:string;activeCourse?:string|null;linked:string[];onNew:()=>void;onSession:(id:string)=>void;onCourse:(id:string)=>void;onCollapse:()=>void}){
 const [query,setQuery]=useState('');
 const [tab,setTab]=useState<'sessions'|'courses'>('sessions');
 const matches=(s:string)=>s.toLocaleLowerCase().includes(query.toLocaleLowerCase());
 const visibleSessions=sessions.filter(s=>matches(s.title));
 const visibleCourses=courses.filter(c=>matches(c.title));
 function switchWithKeyboard(e:KeyboardEvent<HTMLButtonElement>){
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();
  const next=e.key==='Home'?'sessions':e.key==='End'?'courses':tab==='sessions'?'courses':'sessions';
  setTab(next);
  const buttons=e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
  buttons?.[next==='sessions'?0:1]?.focus();
 }
 return <aside className="session-sidebar">
  <div className="sidebar-brand"><span className="brand-symbol"><Icon name="sparkles" size={20}/></span><strong>在线课堂Agent <small>小课堂</small></strong><button onClick={onCollapse} aria-label="收起导航"><Icon name="panel" size={15}/></button></div>
  <button className="new-chat" onClick={onNew}><Icon name="plus" size={15}/>新建对话</button>
  <div className="sidebar-tabs" role="tablist" aria-label="导航分类">
   <button id="sidebar-sessions-tab" type="button" role="tab" aria-selected={tab==='sessions'} aria-controls="sidebar-list-panel" tabIndex={tab==='sessions'?0:-1} onClick={()=>setTab('sessions')} onKeyDown={switchWithKeyboard}>对话</button>
   <button id="sidebar-courses-tab" type="button" role="tab" aria-selected={tab==='courses'} aria-controls="sidebar-list-panel" tabIndex={tab==='courses'?0:-1} onClick={()=>setTab('courses')} onKeyDown={switchWithKeyboard}>课程</button>
  </div>
  <label className="sidebar-search"><Icon name="search" size={14}/><input type="search" placeholder="按名称筛选" value={query} onChange={e=>setQuery(e.target.value)} aria-label={tab==='sessions'?'搜索对话':'搜索课程'}/></label>
  <div id="sidebar-list-panel" className="sidebar-list" role="tabpanel" aria-labelledby={tab==='sessions'?'sidebar-sessions-tab':'sidebar-courses-tab'} tabIndex={0}>
   {tab==='sessions'?<>
    {visibleSessions.map(s=><button className={`session-link ${s.id===current?'selected':''}`} key={s.id} title={s.title} aria-current={s.id===current?'true':undefined} onClick={()=>onSession(s.id)}><span>{s.title}</span><small>{s.state==='running'?'正在制作':s.state==='waiting_for_user'?'等待回答':new Date(s.updatedAt).toLocaleDateString()}</small></button>)}
    {!visibleSessions.length&&<p className="sidebar-empty">{query?'没有匹配的对话':'还没有对话'}</p>}
   </>:<>
    {visibleCourses.map(c=><button className={`session-link ${c.id===activeCourse?'selected':''}`} key={c.id} title={c.title} aria-current={c.id===activeCourse?'true':undefined} onClick={()=>onCourse(c.id)}><span>{c.title}</span><small>{c.id===activeCourse?'当前预览 · ':linked.includes(c.id)?'已关联 · ':''}{c.status==='ready'?'可播放':`待完善 · ${c.outstanding.length} 项`}</small></button>)}
    {!visibleCourses.length&&<p className="sidebar-empty">{query?'没有匹配的课程':'还没有课程'}</p>}
   </>}
  </div>
  <details className="capabilities"><summary>服务状态</summary>{Object.entries(capabilities).map(([id,c])=><p key={id}><span className={c.available?'dot good':'dot'}/>{{creation:'制作',image:'图片',search:'搜索',tts:'语音',preview:'预览'}[id as 'creation'|'image'|'search'|'tts'|'preview']} · {c.provider}<small>{c.model}{c.api&&` · ${c.api}`}{!c.available&&` · 需配置 ${c.missing}`}</small></p>)}<small>已配置表示配置齐全；实际能力以调用结果为准。</small></details>
 </aside>;
}
