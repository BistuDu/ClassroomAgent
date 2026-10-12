// One sound owner for classroom playback and narration audition.
class AudioController {
 private owner=''; private cancel:(()=>void)|undefined; private audio:HTMLAudioElement|undefined;
 claim(owner:string,cancel:()=>void){if(this.owner!==owner)this.stop();this.owner=owner;this.cancel=cancel;}
 bind(owner:string,audio:HTMLAudioElement){if(this.owner!==owner)throw Error('音频执行已切换');this.audio=audio;}
 stop(){const cancel=this.cancel;this.cancel=undefined;this.owner='';this.audio?.pause();this.audio=undefined;cancel?.();}
 release(owner:string){if(this.owner===owner){this.cancel=undefined;this.owner='';this.audio?.pause();this.audio=undefined;}}
 async audition(id:string){
  this.stop();const audio=new Audio(`/api/media/${id}`),owner='audition:'+crypto.randomUUID();
  await new Promise<void>((resolve,reject)=>{
   let settled=false;
   const finish=(error?:Error)=>{if(settled)return;settled=true;audio.onended=null;audio.onerror=null;this.release(owner);if(error)reject(error);else resolve();};
   this.claim(owner,()=>{audio.pause();finish();});this.bind(owner,audio);
   audio.onended=()=>finish();audio.onerror=()=>finish(Error('音频无法加载，请重新生成语音后再试听'));
   void audio.play().catch(error=>finish(error));
  });
 }
}
export const audioController=new AudioController();
