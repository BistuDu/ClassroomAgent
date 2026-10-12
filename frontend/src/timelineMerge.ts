import type { TimelineNode } from '../../contracts/generated';
export function mergeNodes(prior:TimelineNode[],incoming:TimelineNode[]){
 const map=new Map(prior.map(n=>[n.id,n]));for(const n of incoming){const old=map.get(n.id);if(!old||n.lastSeq>=old.lastSeq)map.set(n.id,n);}
 return [...map.values()].sort((a,b)=>a.firstSeq-b.firstSeq||a.id.localeCompare(b.id));
}
