import type { CSSProperties } from 'react';

type IconName='tool'|'check'|'clock'|'chevron'|'arrow'|'menu'|'panel'|'search'|'plus'|'file'|'sparkles'|'close'|'alert';
const paths:Record<IconName,string>={
 tool:'M14.5 6.5a5 5 0 0 0-6.2 6.2L3 18l3 3 5.3-5.3a5 5 0 0 0 6.2-6.2l-3 3-3-3z',
 check:'m5 12 4 4L19 6',clock:'M12 8v4l3 2',chevron:'m8 10 4 4 4-4',
 arrow:'M12 19V5m-6 6 6-6 6 6',menu:'M4 6h16M4 12h16M4 18h16',
 panel:'M9 3v18M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2',
 search:'m16 16 4 4',plus:'M12 5v14M5 12h14',
 file:'M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6v6h6M8 13h8M8 17h5',
 sparkles:'m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7z',
 close:'m6 6 12 12M6 18 18 6',alert:'M12 7v6m0 4h.01',
};
export function Icon({name,size=16,className,style}:{name:IconName;size?:number;className?:string;style?:CSSProperties}){
 return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className} style={style}>{(name==='clock'||name==='alert')&&<circle cx="12" cy="12" r="9"/>}{name==='search'&&<circle cx="10.5" cy="10.5" r="6.5"/>}<path d={paths[name]}/></svg>;
}
