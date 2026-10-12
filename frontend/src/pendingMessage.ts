export type PendingMessage={messageId:string;text:string;approve:boolean;stageId:string|null;questionId?:string;planVersion?:number;targetStageIds?:string[]};
export function readPendingMessage(sessionId:string):PendingMessage|null{
 try{const value=JSON.parse(localStorage.getItem('pendingMessage:'+sessionId)||'null');return value&&typeof value.messageId==='string'&&typeof value.text==='string'?value:null;}catch{return null;}
}
