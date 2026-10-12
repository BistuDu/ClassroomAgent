import test from 'node:test';
import assert from 'node:assert/strict';
import {PiEventAdapter,redact} from '../agent-runtime/events.ts';

test('subscription forwards thinking text without cumulative partials or opaque signatures',()=>{
 const captured=[];const adapter=new PiEventAdapter('user-request',e=>captured.push(e));
 const message={role:'assistant',content:[{type:'text',text:''}],stopReason:'stop'};
 adapter.accept({type:'message_start',message});
 adapter.accept({type:'message_update',assistantMessageEvent:{type:'text_delta',contentIndex:0,delta:'你好',partial:message}});
 message.content[0].text='你好，完整正文';
 adapter.accept({type:'message_update',assistantMessageEvent:{type:'thinking_delta',contentIndex:1,delta:'先核对目标',partial:message}});
 adapter.accept({type:'message_update',assistantMessageEvent:{type:'thinking_end',contentIndex:1,content:'先核对目标，再选择工具。',partial:message}});
 adapter.accept({type:'message_end',message:{...message,content:[...message.content,{type:'thinking',thinking:'先核对目标，再选择工具。',thinkingSignature:'SECRET'}]}});
 assert.equal(captured[1].delta,'你好');assert.equal(captured[1].partial,undefined);
 assert.equal(captured[2].delta,'先核对目标');assert.equal(captured[3].text,'先核对目标，再选择工具。');
 assert.equal(captured.at(-1).content[1].thinking,'先核对目标，再选择工具。');
 assert.ok(!JSON.stringify(captured).includes('SECRET'));
 assert.equal(captured.at(-1).messageId,captured[0].messageId);
});

test('SDK tool result is authoritative; args/results/progress are independent frozen receipts',()=>{
 const captured=[];const adapter=new PiEventAdapter('user',e=>captured.push(e));
 const args={sceneId:'s1',value:'最初'};
 adapter.accept({type:'tool_execution_start',toolCallId:'call',toolName:'patch_stage',args});args.value='后来';
 adapter.accept({type:'tool_execution_update',toolCallId:'call',toolName:'patch_stage',partialResult:{details:{processed:1}}});
 const result={content:[{type:'text',text:'SDK hook 最终结果'}],details:{data:[1,2]},isError:false};
 adapter.accept({type:'tool_execution_end',toolCallId:'call',toolName:'patch_stage',result,isError:false});result.details.data.push(3);
 assert.equal(captured[0].args.value,'最初');assert.deepEqual(captured[2].result.details.data,[1,2]);
 assert.equal(captured[1].eventType,'tool_execution_update');
});

test('SDK retry/compaction retain identity; signed URLs and credentials are masked',()=>{
 const captured=[];const adapter=new PiEventAdapter('user',e=>captured.push(e));
 adapter.accept({type:'auto_retry_start',attempt:1,delayMs:10});adapter.accept({type:'auto_retry_end',success:true});
 adapter.accept({type:'compaction_start',reason:'threshold'});adapter.accept({type:'compaction_end',result:{tokensBefore:100},willRetry:false});
 assert.equal(captured[0].operationId,captured[1].operationId);assert.equal(captured[2].operationId,captured[3].operationId);
 const safe=redact({apiKey:'test-key',audioSignature:'business-hash',url:'https://example.org/img?Signature=secret&Expires=1',text:'test-key'},['test-key']);
 assert.equal(safe.apiKey,'[redacted]');assert.equal(safe.audioSignature,'business-hash');assert.ok(!safe.url.includes('secret'));assert.equal(safe.text,'[redacted]');
});
