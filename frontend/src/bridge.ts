import type { Scene } from '../../contracts/generated';
export type Reply={state:Record<string,unknown>;observation:unknown;displayState?:Record<string,unknown>;instanceId?:string};
export interface SimulationBridge {instanceId:string;request(type:string,payload?:Record<string,unknown>):Promise<Reply>}
export function simulationDocument(scene:Scene,instanceId:string) {
 if(scene.content.type!=='interactive') return '';
 const config=JSON.stringify({sceneId:scene.id,instanceId,variables:scene.content.variables,controls:scene.content.controls}).replaceAll('<','\\u003c');
 const script=`<script>(()=>{
 const config=${config};
 let api,ready=false;
 const reply=(type,requestId,body={})=>parent.postMessage({channel:'openmaic',sceneId:config.sceneId,instanceId:config.instanceId,type,requestId,...body},'*');
 const target=selector=>{if(!config.controls.includes(selector))throw Error('未声明的实验目标');const node=document.querySelector(selector);if(!node)throw Error('目标不存在');return node;};
 const display=()=>({targets:Object.fromEntries(config.controls.map(selector=>{const n=target(selector);return[selector,{hidden:n.hidden,style:n.getAttribute('style'),highlight:n.hasAttribute('data-teacher-highlight')}];})),notes:[...document.querySelectorAll('[data-teacher-note]')].map(n=>({target:n.dataset.teacherTarget,content:n.textContent}))});
 const clearNotes=()=>document.querySelectorAll('[data-teacher-note]').forEach(n=>n.remove());
 const snapshot=()=>({state:api.getState(),observation:api.observe(),displayState:display()});
 let chain=Promise.resolve();
 addEventListener('message',event=>{
  const m=event.data;
  if(event.source!==parent||!m||m.channel!=='openmaic'||m.sceneId!==config.sceneId||m.instanceId!==config.instanceId)return;
  chain=chain.then(async()=>{try{
   if(!ready)throw Error('实验尚未就绪');
   if(m.type==='RESTORE'){
    const d=m.payload.displayState;
    if(!d||!d.targets)throw Error('缺少可恢复的实验显示现场');
    for(const [selector,value]of Object.entries(d.targets)){target(selector);if(!value||typeof value.hidden!=='boolean'||(value.style!==null&&typeof value.style!=='string'))throw Error('无效显示现场');}
    for(const [name,value]of Object.entries(m.payload.state||{})){const v=config.variables.find(v=>v.name===name);if(v&&(typeof value!=='number'||!Number.isFinite(value)||value<v.min||value>v.max))throw Error('参数越界');if(!(name in api.getState()))throw Error('未声明状态');}
    await api.setState(m.payload.state);clearNotes();
    for(const[selector,value]of Object.entries(d.targets)){const n=target(selector);n.hidden=value.hidden;if(value.style===null)n.removeAttribute('style');else n.setAttribute('style',value.style);if(value.highlight)n.dataset.teacherHighlight='true';else n.removeAttribute('data-teacher-highlight');}
    for(const note of d.notes||[]){const n=target(note.target),span=document.createElement('span');span.dataset.teacherNote='true';span.dataset.teacherTarget=note.target;span.textContent=note.content;span.style.cssText='display:block;color:#b45309;font:16px sans-serif;padding:6px';n.insertAdjacentElement('afterend',span);}
    for(const[name,value]of Object.entries(m.payload.state||{}))if(JSON.stringify(api.getState()[name])!==JSON.stringify(value))throw Error('现场恢复未生效');
   }else if(m.type==='SET_STATE'){
    for(const [name,value]of Object.entries(m.payload.state)){const variable=config.variables.find(v=>v.name===name);if(variable&&(typeof value!=='number'||!Number.isFinite(value)||value<variable.min||value>variable.max))throw Error('参数越界');if(!(name in api.getState()))throw Error('未声明的状态');}
    await api.setState(m.payload.state);
    const actual=api.getState();for(const[name,value]of Object.entries(m.payload.state))if(JSON.stringify(actual[name])!==JSON.stringify(value))throw Error('参数设置未生效');
   }else if(m.type==='PAUSE')await api.pause();
   else if(m.type==='RESUME')await api.resume();
   else if(m.type==='RESET')await api.reset();
   else if(m.type==='HIGHLIGHT'){document.querySelectorAll('[data-teacher-highlight]').forEach(n=>{n.removeAttribute('data-teacher-highlight');n.style.outline='';});const n=target(m.payload.target);n.dataset.teacherHighlight='true';n.style.outline='3px solid #f59e0b';}
   else if(m.type==='ANNOTATION'){const n=target(m.payload.target);let note=[...document.querySelectorAll('[data-teacher-note]')].find(n=>n.dataset.teacherTarget===m.payload.target);if(!note){note=document.createElement('span');note.dataset.teacherNote='true';note.dataset.teacherTarget=m.payload.target;n.insertAdjacentElement('afterend',note);}note.textContent=m.payload.content;note.style.cssText='display:block;color:#b45309;font:16px sans-serif;padding:6px';}
   else if(m.type==='REVEAL'){const n=target(m.payload.target);n.hidden=false;n.style.display='';n.style.visibility='visible';}
   else if(m.type!=='GET_STATE'&&m.type!=='SNAPSHOT')throw Error('未知实验命令');
   reply('ACK',m.requestId,snapshot());
  }catch(error){reply('ERROR',m.requestId,{error:String(error)});}});
 });
 let attempts=0;const poll=setInterval(()=>{api=window.openmaicSimulation;if(api){clearInterval(poll);try{for(const name of['getState','setState','observe','reset','pause','resume'])if(typeof api[name]!=='function')throw Error('缺少实验方法 '+name);ready=true;reply('READY',null,snapshot());}catch(error){reply('ERROR',null,{error:String(error)});}}else if(++attempts>=100){clearInterval(poll);reply('ERROR',null,{error:'实验契约未初始化'});}},50);
})()<\/script>`;
 const csp=`default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob: ${location.origin}/api/media/; font-src data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'`;
 return `<!doctype html><meta http-equiv="Content-Security-Policy" content="${csp}">`+scene.content.html+script;
}
