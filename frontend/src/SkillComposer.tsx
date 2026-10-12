import {useEffect,useRef,useState} from 'react';
import {api} from './api';
export type ComposerSkill={skillId:string;title:string;command:string;description:string;disableModelInvocation:boolean};
type Directory={version:string;skills:ComposerSkill[];legacyReads?:Record<string,unknown>;diagnostics:{message:string}[];loadError?:string};
export function SkillComposer({input,onInput,disabled,canSend,placeholder}:{input:string;onInput:(text:string)=>void;disabled:boolean;canSend:boolean;placeholder:string}){
 const textarea=useRef<HTMLTextAreaElement>(null),composing=useRef(false),ended=useRef(-Infinity);
 const [directory,setDirectory]=useState<Directory>(),[error,setError]=useState(''),[caret,setCaret]=useState(0),[open,setOpen]=useState(false),[selected,setSelected]=useState(0);
 async function load(){try{setDirectory(await api<Directory>('/api/skills'));setError('');}catch(e){setError(String(e));}}
 useEffect(()=>{void load();},[]);
 const prefix=input.slice(0,caret),match=/(?:^|\s)(\/[^\s/`，。！？、,!?；;]*)$/i.exec(prefix);
 const query=match?.[1].slice(1).toLowerCase()||'',start=match?caret-match[1].length:caret;
 const skills=(directory?.skills||[]).filter(s=>!s.disableModelInvocation);
 const options=skills.filter(s=>[s.skillId,s.title,s.description].some(v=>v.toLowerCase().includes(query)));
 const visible=open&&!!match&&!disabled;
 useEffect(()=>{setSelected(0);},[query]);
 const index=Math.min(selected,Math.max(0,options.length-1));
 useEffect(()=>{if(visible)document.getElementById('skill-option-'+index)?.scrollIntoView({block:'nearest'});},[index,visible]);
 function choose(s:ComposerSkill){
  const suffix=/^[^\s/`，。！？、,!?；;]*/.exec(input.slice(caret))?.[0]||'';
  const right=input.slice(caret+suffix.length),space=right&&!/^\s/.test(right)?' ':right?'':' ';
  const text=input.slice(0,start)+s.command+space+right,next=start+s.command.length+space.length;
  onInput(text);setCaret(next);setOpen(false);requestAnimationFrame(()=>{textarea.current?.focus();textarea.current?.setSelectionRange(next,next);});
 }
 function launch(){const el=textarea.current;if(!el)return;const a=el.selectionStart,b=el.selectionEnd;
  const left=input.slice(0,a),right=input.slice(b),token=(left&&!/\s$/.test(left)?' ':'')+'/';
  const separator=right&&!/^\s/.test(right)?' ':'';
  onInput(left+token+separator+right);setCaret(a+token.length);setOpen(true);requestAnimationFrame(()=>{el.focus();el.setSelectionRange(a+token.length,a+token.length);});
 }
 const plain=input.replace(/```[\s\S]*?```|`[^`\n]*`/g,part=>' '.repeat(part.length));
 const unknown=[...plain.matchAll(/(?:^|\s)\/(?:skill:)?([a-z0-9]+(?:-[a-z0-9]+)*)(?=$|\s|[，。！？、,!?；;])/g)].map(m=>m[1]).filter(id=>directory&&!skills.some(s=>s.skillId===id)&&!directory.legacyReads?.[id]);
 return <div className="skill-composer">{visible&&<div className="skill-menu"><div className="skill-menu-title">选择教学方法或参考 <small>↑↓ 选择 · Enter 确认 · Esc 关闭</small></div>{error?<p role="alert">目录加载失败：{error} <button type="button" onClick={()=>void load()}>重试</button></p>:!directory?<p>正在读取可用 Skill…</p>:<div role="listbox" id="skill-options" aria-label="可用 Skill">{options.length?options.map((s,i)=><button id={'skill-option-'+i} key={s.skillId} type="button" role="option" aria-selected={i===index} className={i===index?'selected':''} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(s)}><span><strong>{s.title}</strong><code>{s.command}</code></span><small>{s.description}</small></button>):<p>没有匹配的 Skill，试试中文名称或英文命令。</p>}</div>}{directory?.diagnostics.length? <details><summary>目录诊断 · {directory.diagnostics.length}</summary>{directory.diagnostics.map((d,i)=><p key={i}>{d.message}</p>)}</details>:null}</div>}
 <textarea ref={textarea} role="combobox" aria-label="教学需求或回复" aria-describedby="composer-shortcut" aria-expanded={visible} aria-controls="skill-options" aria-autocomplete="list" aria-activedescendant={visible&&options.length?'skill-option-'+index:undefined} value={input} disabled={disabled} placeholder={placeholder}
 onChange={e=>{onInput(e.target.value);setCaret(e.target.selectionStart);setOpen(true);}} onSelect={e=>setCaret(e.currentTarget.selectionStart)}
 onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={e=>{composing.current=false;ended.current=performance.now();setCaret(e.currentTarget.selectionStart);}}
 onKeyDown={e=>{if(e.nativeEvent.isComposing||e.nativeEvent.keyCode===229||composing.current||performance.now()-ended.current<80)return;
 if(visible&&['ArrowDown','ArrowUp','Escape','Enter'].includes(e.key)&&!e.shiftKey){e.preventDefault();if(e.key==='Escape')setOpen(false);else if(e.key==='Enter'){if(options[index]&&!e.repeat)choose(options[index]);}else setSelected(i=>(i+(e.key==='ArrowDown'?1:-1)+Math.max(1,options.length))%Math.max(1,options.length));return;}
 if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();if(canSend&&!e.repeat)e.currentTarget.form?.requestSubmit();}}}/>
 <div className="skill-entry"><button type="button" disabled={disabled} onClick={launch}>/ Skill <span>选择教学方法</span></button>{error&&<small role="status">Skill目录暂不可用 <button type="button" onClick={()=>void load()}>重试</button></small>}{directory?.loadError&&<small role="alert">{directory.loadError}</small>}{unknown.length>0&&<small role="status">未知命令：{[...new Set(unknown)].map(x=>'/'+x).join('、')}（原文保留）</small>}</div></div>;
}
