import { useEffect, useState } from 'react';
import type { Stage } from '../../contracts/generated';
import { api } from './api';
import { audioController } from './audio';

type VoiceCatalog={model:string;voices:{id:string;name:string;sampleAudioId?:string}[]};

export function TeacherVoice({stage,disabled,onChange}:{stage:Stage;disabled:boolean;onChange:(voice:string)=>Promise<void>}){
 const [catalog,setCatalog]=useState<VoiceCatalog>(),[error,setError]=useState('');
 useEffect(()=>{let live=true;void api<VoiceCatalog>('/api/voices').then(value=>{if(live)setCatalog(value);}).catch(e=>{if(live)setError(String(e));});return()=>{live=false;};},[]);
 const current=stage.teacher?.voice||'',supported=!!catalog&&catalog.model===stage.teacher?.model&&catalog.voices.some(v=>v.id===current);
 const sample=catalog?.voices.find(v=>supported&&v.id===current)?.sampleAudioId;
 return <section className="teacher-voice"><label>老师声音 <select aria-label="老师声音" value={supported?current:''} disabled={disabled||!catalog} onChange={e=>{setError('');void onChange(e.target.value).catch(e=>setError(String(e)));}}>
 {!supported&&<option value="" disabled>{current?'当前音色不在可选目录':'选择老师音色'}</option>}{catalog?.voices.map(voice=><option key={voice.id} value={voice.id}>{voice.name}</option>)}</select></label>
 {sample&&<button disabled={disabled} onClick={()=>void audioController.audition(sample).catch(e=>setError(String(e)))}>试听音色</button>}
 <small>切换音色后，需重新生成课程语音。</small>{error&&<p className="error" role="alert">{error}</p>}</section>;
}
