import { randomUUID } from 'node:crypto';

/** Synchronous snapshot at the subscription boundary; never retain mutable partials. */
export class PiEventAdapter {
 messageId='';
 ids=new WeakMap<object,string>();
 toolMessages=new Map<string,string>();
 compactionId=''; retryId='';
 userMessageId:string; emit:(payload:any)=>void;
 constructor(userMessageId:string,emit:(payload:any)=>void) {this.userMessageId=userMessageId;this.emit=emit;}
 accept(event:any) {
  const e=event.type;let payload:any={eventType:e};
  if(e==='message_start'){
   const m=event.message;
   const id=m.role==='user'?this.userMessageId:randomUUID();
   this.ids.set(m,id);if(m.role==='assistant')this.messageId=id;
   payload={...payload,messageId:id,role:m.role,hidden:m.role==='custom'&&m.display===false};
   if(m.role==='user')payload.message=structuredClone(m);
   if(m.role==='toolResult')payload.toolCallId=m.toolCallId;
  }else if(e==='message_update'){
   const v=event.assistantMessageEvent;
   payload={...payload,messageId:this.messageId,updateType:v.type,contentIndex:v.contentIndex};
   if(v.type==='text_delta'||v.type==='thinking_delta')payload.delta=v.delta;
   if(v.type.startsWith('thinking_'))payload.textAvailable=true;
   if(v.type==='thinking_end')payload.text=v.content;
   if(v.type.startsWith('toolcall_')){
    const call=v.type==='toolcall_end'?v.toolCall:v.partial.content[v.contentIndex];
    if(call?.type==='toolCall'){
     this.toolMessages.set(call.id,this.messageId);
     Object.assign(payload,{toolCallId:call.id,toolName:call.name,deltaChars:v.type==='toolcall_delta'?v.delta.length:0});
     if(v.type==='toolcall_end')payload.args=structuredClone(call.arguments);
    }
   }
   // Display the provider's SDK thinking text; opaque signatures stay out of UI.
  }else if(e==='message_end'){
   const m=event.message;const id=this.ids.get(m)||this.messageId;
   if(m.role==='assistant'){
    payload={...payload,messageId:id,role:m.role,stopReason:m.stopReason,errorMessage:m.errorMessage,
     content:m.content.map((c:any)=>c.type==='thinking'?{type:'thinking',thinking:c.thinking}:structuredClone(c))};
   }else payload={...payload,messageId:id,role:m.role,toolCallId:m.toolCallId,hidden:m.role==='custom'&&m.display===false};
  }else if(e.startsWith('tool_execution_')){
   payload={...payload,toolCallId:event.toolCallId,toolName:event.toolName,messageId:this.toolMessages.get(event.toolCallId)||this.messageId};
   if(event.parentToolCallId)payload.parentToolCallId=event.parentToolCallId;
   if(e==='tool_execution_start')payload.args=structuredClone(event.args);
   if(e==='tool_execution_update')payload.partialResult=structuredClone(event.partialResult);
   if(e==='tool_execution_end'){payload.result=structuredClone(event.result);payload.isError=event.isError;}
  }else if(e==='compaction_start'){
   this.compactionId=randomUUID();payload={...payload,operationId:this.compactionId,reason:event.reason};
  }else if(e==='compaction_end'){
   payload={...payload,operationId:this.compactionId,reason:event.reason,aborted:event.aborted,willRetry:event.willRetry,
    tokensBefore:event.result?.tokensBefore,estimatedTokensAfter:event.result?.estimatedTokensAfter,errorMessage:event.errorMessage};
  }else if(e==='auto_retry_start'){
   this.retryId=randomUUID();payload={...payload,operationId:this.retryId,attempt:event.attempt,maxAttempts:event.maxAttempts,delayMs:event.delayMs,errorMessage:event.errorMessage};
  }else if(e==='auto_retry_end')payload={...payload,operationId:this.retryId,success:event.success,attempt:event.attempt,finalError:event.finalError};
  else if(e==='agent_end')payload.willRetry=event.willRetry;
  else if(e==='agent_settled')payload.outcome=event.outcome;
  // Unknown event types retained as facts without guessing their UI semantics.
  this.emit(payload);
 }
}

export function redact(value:any,secrets:string[]):any {
 if(Array.isArray(value))return value.map(v=>redact(v,secrets));
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,/^(api_?key|authorization|password|token|secret|signature|thinkingSignature)$/i.test(k)?'[redacted]':redact(v,secrets)]));
 if(typeof value==='string'){
  for(const secret of secrets.filter(Boolean))value=value.replaceAll(secret,'[redacted]');
  value=value.replace(/([?&](?:signature|x-amz-signature|x-amz-credential|x-amz-security-token|x-oss-signature|x-oss-credential|ossaccesskeyid|access_token|token|api_key)=)[^&\s"<>]+/gi,'$1[redacted]');
 }
 return value;
}
