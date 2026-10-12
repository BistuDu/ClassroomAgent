import {selectSkills, skillCoverage, actualReads, skillReadOnlyTools, SKILL_LOAD_LIMITS, type RequiredSkill} from './skill-selection.ts';
import { randomUUID } from 'node:crypto';
import { PiEventAdapter, redact } from './events.ts';
import { readFile, mkdir, realpath } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import path from 'node:path';
import { createSkillLoader, minimalSkillLoader, type SkillResources } from './skill-resources.ts';
import {
 createAgentSession, ModelRuntime, SessionManager, SettingsManager,
 type ResourceLoader, type ToolDefinition, type AgentSession,
} from '@earendil-works/pi-coding-agent';

const root = await realpath(process.cwd());
const data = path.resolve(process.env.PI_CODING_AGENT_DIR || path.join(root,'data','pi'));
if(!data.startsWith(path.join(root,'data')+path.sep))throw new Error('SDK 数据目录必须位于 Python 项目 data 内');
await mkdir(path.join(data, 'sessions'), {recursive:true});
const contracts = JSON.parse(await readFile(path.join(root, 'contracts/schema.json'), 'utf8'));
const system = `你是 OpenMAIC 课程制作 Agent。只使用已配置的课程业务工具和 SDK 事件完成工作。\n`+
 `先读取匹配当前任务的 Skill（read_skill 的 skillId/path），再依据真实工具结果操作；允许根据索引按需自动选择Skill；用户要求优先于Skill默认，显式选择优先于自动匹配，有实质冲突先ask_user。把方法落实到plan/pages[].brief、generate_scene.brief和generate_actions.guidance；不建立永久课程绑定。Skill 只提供知识和规则，不能代替审批、权限、课程状态或检查结果。\n`+
 `禁止通用文件读写、shell、脚本执行和任意路径访问。新课必须先 ask_user(plan_approval) 并等待真实批准；写入前核对 stageId/revision；课程只有页面、动作、音频、程序检查和视觉检查都完成才算就绪。`;
let session: AgentSession | undefined;
let active: {sessionId:string; runId:string} | undefined;
let waiting = false;
let cancelled = false;
let count = 0;
let assistantError: string | undefined;
const pending = new Map<string, {resolve:(result:any)=>void; update?:(result:any)=>void}>();
let output=Promise.resolve();let seq=0;let acked=0;let outputBytes=0;let transportError:unknown;
let secrets:string[]=[];
const ackWaiters=new Set<()=>void>();
const send = (type:string, body:any={}) => {
 const line=JSON.stringify({protocolVersion:2,...active,type,...redact(body,secrets)})+'\n';
 outputBytes+=Buffer.byteLength(line);
 if(outputBytes>32_000_000){transportError=Error('事件队列超限');cancelled=true;void session?.abort();return;}
 output=output.then(()=>new Promise<void>((resolve,reject)=>process.stdout.write(line,error=>{outputBytes-=Buffer.byteLength(line);error?reject(error):resolve();}))).catch(error=>{transportError=error;cancelled=true;void session?.abort();});
};
async function flush(){await output;if(transportError)throw transportError;}
async function drainEvents(){
 await flush();if(acked>=seq)return;
 await new Promise<void>((resolve,reject)=>{
  const timer=setTimeout(()=>{ackWaiters.delete(check);reject(Error('事件持久化确认超时'));},15000);
  const check=()=>{if(acked>=seq){clearTimeout(timer);ackWaiters.delete(check);resolve();}};
  ackWaiters.add(check);check();
 });
}
function inline(schema:any, defs:any):any {
 if (Array.isArray(schema)) return schema.map(v=>inline(v,defs));
 if (!schema || typeof schema !== 'object') return schema;
 if (schema.$ref) return inline(defs[schema.$ref.split('/').at(-1)],defs);
 return Object.fromEntries(Object.entries(schema).filter(([k])=>k!=='$defs').map(([k,v])=>[k,inline(v,defs)]));
}
async function start(message:any) {
 if (active) throw new Error('已有活动运行');
 active = {sessionId:message.sessionId,runId:message.runId};
 secrets=[message.config.apiKey];
 const timeout = setTimeout(()=>{cancelled=true; void session?.abort();},message.config.runTimeoutMs);
 try {
  if (!message.config.apiKey) throw new Error('缺少 CREATION_API_KEY');
  let resources: SkillResources = message.skillResources || {version:'unavailable',skills:[],diagnostics:[{type:'error',message:'缺少本轮 Skill 快照'}]};
  let loader: ResourceLoader = createSkillLoader(root,data,system,resources);
  try { await loader.reload(); } catch (error) {
   resources={version:'unavailable',skills:[],diagnostics:[{type:'error',message:String(error)}],loadError:String(error)};
   loader=minimalSkillLoader(system,resources);
  }
  const runtime = await ModelRuntime.create({authPath:path.join(data,'auth.json'),modelsPath:path.join(data,'models.json'),modelsStorePath:path.join(data,'catalog.json'),allowModelNetwork:false});
  const providerId = 'openmaic-' + message.config.provider;
  const thinkingLevel = message.config.thinkingLevel as 'off'|'minimal'|'low'|'medium'|'high';
  runtime.registerProvider(providerId, {name:message.config.provider,baseUrl:message.config.baseUrl,
   api:message.config.api,authHeader:true,models:[{id:message.config.model,name:message.config.model,
    api:message.config.api,input:['text','image'],reasoning:thinkingLevel!=='off',contextWindow:message.config.contextWindow,
    maxTokens:message.config.maxTokens,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]});
  await runtime.setRuntimeApiKey(providerId,message.config.apiKey);
  const model = runtime.getModel(providerId,message.config.model);
  if(!model) throw new Error('制作模型注册失败');
  let manager;
  if (message.sessionFile) {
   const file = await realpath(message.sessionFile);
   if (!file.startsWith(path.join(data,'sessions')+path.sep)) throw new Error('会话路径超出项目范围');
   manager = SessionManager.open(file,path.join(data,'sessions'),root);
  } else manager = SessionManager.create(root,path.join(data,'sessions'));
  const customTools:ToolDefinition[] = Object.entries(contracts.tools).map(([name,raw])=>{
   const spec = raw as any;
   if(spec.parameters?.type!=='object')throw new Error(`工具 ${name} 的参数 schema 顶层必须为 object，请运行 npm run contracts`);
   return {name,label:name,description:spec.description,parameters:inline(spec.parameters,spec.parameters.$defs||{}),executionMode:'sequential',
    execute:async(requestId,params,signal,onUpdate)=>{
     if(waiting||cancelled) throw new Error('正在等待用户或运行已取消');
     if(++count>message.config.maxToolCalls) {cancelled=true; throw new Error('工具调用预算耗尽');}
     const result = await new Promise<any>((resolve)=>{
      const abort=()=>{pending.delete(requestId);resolve({ok:false,error:{code:'CANCELLED',message:'已取消'}});};
      pending.set(requestId,{resolve:(v)=>{signal?.removeEventListener('abort',abort);resolve(v);},update:(v)=>onUpdate?.(v)});
      signal?.addEventListener('abort',abort,{once:true});
      send('tool_request',{requestId,name,args:params as Record<string,unknown>});
     });
     if(result.waiting) waiting=true;
     const content=result.content||[{type:'text',text:JSON.stringify(result.error||{code:'PROTOCOL_RESULT',message:'工具缺少结果契约'})}];
     return {content:redact(content,secrets),details:redact(result.details,secrets),isError:result.isError??!result.ok,terminate:waiting||cancelled||result.terminate};
    }};
  });
  ({session}=await createAgentSession({cwd:root,agentDir:data,modelRuntime:runtime,model,thinkingLevel,resourceLoader:loader,
   sessionManager:manager,settingsManager:SettingsManager.inMemory({enableSkillCommands:false,compaction:message.config.compaction,retry:{enabled:true,maxRetries:2}}),
   noTools:'builtin',tools:Object.keys(contracts.tools),customTools}));
  session.agent.toolExecution='sequential';
  const selection=selectSkills(message.text,resources);
  const dependent=new Map<string,RequiredSkill>(selection.required.map(r=>[r.canonicalId+':'+r.path,r]));
  let effectiveMessages:any[]=[];
  let loadBlocks=0;
  const missing=()=>[...dependent.values()].filter(r=>!skillCoverage(effectiveMessages,r,resources.version).complete);
  const selectionError=selection.unknown.length||selection.unloaded.length ? {unknown:selection.unknown,unloaded:selection.unloaded.map(s=>s.requestedId),limits:SKILL_LOAD_LIMITS} : undefined;
  const originalStream=session.agent.streamFunction;
  session.agent.streamFunction=async(model,context,options)=>{
   const controller=new AbortController();const abort=()=>controller.abort(options?.signal?.reason);
   if(options?.signal?.aborted)abort();else options?.signal?.addEventListener('abort',abort,{once:true});
   const timer=setTimeout(()=>controller.abort(Error('制作模型请求超时')),message.config.providerTimeoutMs);
   const cleanup=()=>{clearTimeout(timer);options?.signal?.removeEventListener('abort',abort);};
   // This is the exact context after SDK transformations, immediately before the provider.
   effectiveMessages=context.messages;
   const pendingSkills=missing();
   const policy=selectionError ? 'Skill选择不可执行，先用ask_user说明未知/超预算项目并缩小选择：'+JSON.stringify(selectionError) : pendingSkills.length ? '业务生成/写入前必须真实read_skill分页读完下列冻结正文；历史摘要不算加载：'+JSON.stringify(pendingSkills.map(r=>({skillId:r.requestedId,path:'SKILL.md',nextOffset:skillCoverage(effectiveMessages,r,resources.version).nextOffset}))) : '';
   const requestContext={...context,messages:context.messages.map(m=>m.role==='system'&&policy?{...m,sections:{...m.sections,'openmaic-skill-loading':'<skill_loading_policy>'+policy+'</skill_loading_policy>'}}:m)};
   try{const stream=await originalStream(model,requestContext,{...options,signal:controller.signal});void stream.result().then(cleanup,cleanup);return stream;}
   catch(error){cleanup();throw error;}
  };
  let feedbackRounds=0;let previousIssues='';
  const before=session.agent.beforeToolCall,after=session.agent.afterToolCall,finish=session.agent.finishTurn;
  session.agent.beforeToolCall=async(ctx,signal)=>{
   if(waiting||cancelled)return {block:true,reason:'等待用户或已停止，禁止后续工具',terminate:true};
   // Count blocked attempts as well, so ignoring the loading policy cannot loop forever.
   if((!skillReadOnlyTools.has(ctx.toolCall.name)||ctx.toolCall.name==='ask_user'&&(ctx.args as any)?.kind==='plan_approval')&&(selectionError||missing().length)){
    loadBlocks++;
    const reason=selectionError ? 'SKILL_SELECTION_REQUIRED：先ask_user澄清未知/超预算选择 '+JSON.stringify(selectionError) : 'SKILL_LOAD_REQUIRED：先真实读取完整同版本正文 '+JSON.stringify(missing().map(r=>({skillId:r.requestedId,path:'SKILL.md',nextOffset:skillCoverage(effectiveMessages,r,resources.version).nextOffset})));
    if(loadBlocks>=3)assistantError='Skill加载未完成，连续写入尝试已停止：'+reason;
    return {block:true,reason,terminate:loadBlocks>=3};
   }
   return before?.(ctx,signal);
  };
  session.agent.afterToolCall=async(ctx,signal)=>{
   const original=await after?.(ctx,signal);
   // Record only real reads in this run, never inherited history as a permanent selection.
   if(ctx.toolCall.name==='read_skill'&&!ctx.isError){
    const reads=actualReads([{role:'toolResult',toolName:'read_skill',content:ctx.result.content}],resources);
    for(const r of reads)dependent.set(r.canonicalId+':'+r.path,r);
   }
   return waiting||cancelled?{...original,terminate:true}:original;
  };
  // finishTurn stops mixed batches even when results before ask_user had terminate=false.
  session.agent.finishTurn=async(turn,signal)=>{
   if(waiting||cancelled||loadBlocks>=3)return {action:'end'};
   const decision=await finish?.(turn,signal);if(decision?.action==='end')return decision;
   if(turn.message.stopReason==='error'||turn.message.stopReason==='aborted'||turn.message.stopReason==='length'||turn.message.content.some(c=>c.type==='toolCall')||decision)return decision||undefined;
   if(feedbackRounds>=2||count>=message.config.maxToolCalls)return undefined;
   if(selectionError||missing().length){
    feedbackRounds++;
    await session!.sendCustomMessage({customType:'skill-loading-feedback',display:false,content:selectionError?'必须ask_user澄清Skill选择：'+JSON.stringify(selectionError):'尚未完整加载本轮Skill，请真实read_skill分页读取：'+JSON.stringify(missing()),details:{round:feedbackRounds}},{triggerTurn:false});
    return {action:'continue'};
   }
   const id='completion:'+randomUUID();
   const feedback=await new Promise<any>(resolve=>{
    pending.set(id,{resolve});send('completion_request',{requestId:id});
   });
   const signature=JSON.stringify((feedback.issues||[]).map((i:any)=>({stageId:i.stageId,code:i.code,status:i.status,slotId:i.slotId,sceneId:i.sceneId,actionId:i.actionId,mode:i.mode}))); 
   if(!feedback.allowed||!feedback.issues?.length||signature===previousIssues)return undefined;
   previousIssues=signature;feedbackRounds++;
   await session!.sendCustomMessage({customType:'course-completion-feedback',display:false,content:JSON.stringify(feedback),details:{round:feedbackRounds}},{triggerTurn:false});
   return {action:'continue'};
  };
  const adapter=new PiEventAdapter(message.userMessageId||randomUUID(),payload=>send('pi_event',{seq:++seq,capturedAt:new Date().toISOString(),payload}));
  session.subscribe(event=>{
   adapter.accept(event);
   if(event.type==='message_end'&&event.message.role==='assistant'&&['error','length'].includes(event.message.stopReason))assistantError=event.message.errorMessage||'制作模型回复被截断';
  });
  send('skill_diagnostics',resources);
  await session.sendCustomMessage({customType:'skill-diagnostics',display:false,content:JSON.stringify(resources),details:resources},{triggerTurn:false});
  send('session_ready',{sessionFile:manager.getSessionFile(),tools:Object.keys(contracts.tools),skills:resources.skills});
  await session.sendCustomMessage({customType:'course-context',display:false,content:JSON.stringify(message.context)}, {triggerTurn:false});
  // SDK slash expansion reads live disk; route explicit invocations through the snapshot tool.
  await session.prompt(message.text,{expandPromptTemplates:false});
  await drainEvents();
  send('session_saved',{sessionFile:manager.getSessionFile()});
  if(assistantError) throw new Error(assistantError);
  if(!waiting&&!cancelled&&(selectionError||missing().length))throw new Error('SKILL_LOAD_INCOMPLETE：本轮 Skill 选择或正文加载未完成，未放行业务写入');
  send('settled',{waiting,cancelled,toolCalls:count});
  await flush();
 } catch(error) {
  const text=String(error).replaceAll(message.config.apiKey||'__no_key__','[redacted]');
  await drainEvents().catch(()=>{});send('failed',{error:text,errorCode:/image.*(unsupported|not support)|(unsupported|not support).*image/i.test(text)?'MODEL_IMAGE_UNSUPPORTED':'AGENT_FAILED'});await flush().catch(()=>{});
 } finally {
  clearTimeout(timeout);session?.dispose();session=undefined;
  for(const item of pending.values()) item.resolve({ok:false,error:{message:'运行已结束'}});
  pending.clear();process.exitCode=0;process.stdin.pause();
 }
}
const lines=createInterface({input:process.stdin,crlfDelay:Infinity});
lines.on('line',line=>{
 try {
  const message=JSON.parse(line);
  if(message.protocolVersion!==2) throw new Error('协议版本不兼容');
  if(message.type==='start_run'||message.type==='answer_question') {void start(message);return;}
  if(message.sessionId!==active?.sessionId||message.runId!==active?.runId) throw new Error('消息关联标识不匹配');
  if(message.type==='tool_result'||message.type==='completion_result') pending.get(message.requestId)?.resolve(message.result),pending.delete(message.requestId);
  else if(message.type==='tool_progress')pending.get(message.requestId)?.update?.(message.result);
  else if(message.type==='event_ack'){acked=Math.max(acked,message.seq);for(const check of ackWaiters)check();}
  else if(message.type==='cancel_run') {cancelled=true;void session?.abort();}
  else throw new Error('未知协议消息');
 } catch(error) {send('failed',{error:String(error)});void session?.abort();}
});
