import test from 'node:test';
import assert from 'node:assert/strict';
import {readPendingMessage} from '../frontend/src/pendingMessage.ts';
const data=new Map();globalThis.localStorage={getItem:key=>data.get(key)??null};
test('pending legacy payload survives byte-for-byte semantic fields independent of draft/preview',()=>{
 const original={messageId:'accepted-id',text:'给 A 补语音',approve:false,stageId:'a',targetStageIds:['a'],questionId:'q',planVersion:2};
 data.set('pendingMessage:s',JSON.stringify(original));data.set('chatDraft:s','新的正文');data.set('activeStageId','b');
 assert.deepEqual(readPendingMessage('s'),original);assert.equal(data.get('chatDraft:s'),'新的正文');
});
test('invalid cache is ignored without manufacturing a new message',()=>{
 data.set('pendingMessage:invalid','{broken');assert.equal(readPendingMessage('invalid'),null);
 data.set('pendingMessage:invalid',JSON.stringify({text:'没有 ID'}));assert.equal(readPendingMessage('invalid'),null);
});
