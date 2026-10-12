// Test-only injection through Node's --import: production entrypoint and RPC stay unchanged.
import {AgentSession,ModelRuntime} from '@earendil-works/pi-coding-agent';
import {createAssistantMessageEventStream,getCurrentSystemPrompt,getCurrentTools} from '@earendil-works/pi-ai';
import {appendFileSync} from 'node:fs';
const steps=JSON.parse(process.env.OPENMAIC_FIXTURE_STEPS||'[]');
let count=0;
const thinking=process.env.OPENMAIC_FIXTURE_THINKING;
if(process.env.OPENMAIC_FIXTURE_COMPACT){
 const prompt=AgentSession.prototype.prompt;
 AgentSession.prototype.prompt=async function(...args){
  this.settingsManager.applyOverrides({compaction:{enabled:true,reserveTokens:0,keepRecentTokens:0}});
  await this.compact('仅保存任务摘要，不保留 Skill 正文。');
  return prompt.apply(this,args);
 };
}
// Inject at the provider boundary, after production context tracking and policy.
// Never replace Agent.streamFunction: that would bypass the loading gate.
ModelRuntime.prototype.streamSimple=function(model,context){
  const tools=getCurrentTools(context.messages);
  for(const tool of tools){
   if(tool.parameters?.type!=='object')throw new Error(`Provider rejects non-object schema: ${tool.name}`);
  }
  appendFileSync(process.env.OPENMAIC_FIXTURE_CONTEXT,JSON.stringify({messages:context.messages,systemPrompt:getCurrentSystemPrompt(context.messages),tools:tools.map(t=>t.name)})+'\n');
  const step=tools.length?steps.shift():undefined;const content=step?[{type:'toolCall',id:'call_'+(++count),name:step[0],arguments:step[1]}]:[{type:'text',text:'本轮已保存。'}];
  if(thinking)content.unshift({type:'thinking',thinking,thinkingSignature:'fixture-opaque-signature'});
  const offset=thinking?1:0;
  const message={role:'assistant',content,api:model.api,provider:model.provider,model:model.id,
   usage:{input:500,output:50,cacheRead:0,cacheWrite:0,totalTokens:550,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},stopReason:step?'toolUse':'stop',timestamp:Date.now()};
  const stream=createAssistantMessageEventStream();
  queueMicrotask(()=>{
   stream.push({type:'start',partial:{...message,content:[]}});
   if(thinking){
    stream.push({type:'thinking_start',contentIndex:0,partial:message});
    stream.push({type:'thinking_delta',contentIndex:0,delta:thinking.slice(0,4),partial:message});
    stream.push({type:'thinking_delta',contentIndex:0,delta:thinking.slice(4),partial:message});
    stream.push({type:'thinking_end',contentIndex:0,content:thinking,partial:message});
   }
   if(step){
    stream.push({type:'toolcall_start',contentIndex:offset,partial:message});
    stream.push({type:'toolcall_delta',contentIndex:offset,delta:JSON.stringify(content[offset].arguments),partial:message});
    stream.push({type:'toolcall_end',contentIndex:offset,toolCall:content[offset],partial:message});
   }else{
    stream.push({type:'text_start',contentIndex:offset,partial:message});
    stream.push({type:'text_delta',contentIndex:offset,delta:'本轮',partial:message});
    stream.push({type:'text_delta',contentIndex:offset,delta:'已保存。',partial:message});
    stream.push({type:'text_end',contentIndex:offset,content:'本轮已保存。',partial:message});
   }
   stream.push({type:'done',reason:step?'toolUse':'stop',message});stream.end();
  });
  return stream;
};
