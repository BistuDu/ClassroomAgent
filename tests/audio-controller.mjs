import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const elements=[];
class FakeAudio {
 constructor(url){this.url=url;this.paused=false;elements.push(this);}
 pause(){this.paused=true;}
 async play(){this.paused=false;}
}
let sequence=0;
const context={exports:{},Audio:FakeAudio,crypto:{randomUUID:()=>String(++sequence)}};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../frontend/src/audio.ts',import.meta.url),'utf8'),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}
}).outputText,context);
const controller=context.exports.audioController;
let classroomCancelled=false;
controller.claim('course',()=>{classroomCancelled=true;});
const first=controller.audition('first');
assert.equal(classroomCancelled,true);
const ended=elements[0].onended;
const second=controller.audition('second');
assert.equal(elements[0].paused,true);
ended(); // Late completion from the first audition must not stop the second.
assert.equal(elements[1].paused,false);
controller.stop();
assert.equal(elements[1].paused,true);
await Promise.all([first,second]);
const failed=controller.audition('unavailable');
elements[2].onerror();
await assert.rejects(failed,/音频无法加载/);
assert.equal(elements[2].paused,true);
console.log('Audio ownership and late-ended regression passed');
