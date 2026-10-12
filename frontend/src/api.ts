export class ApiError extends Error {
 constructor(message:string,public status:number,public code:string){super(message);}
}
export async function api<T>(url:string,options:RequestInit={}):Promise<T>{
 const response=await fetch(url,{...options,headers:{'Content-Type':'application/json',...options.headers}});
 if(!response.ok){const data=await response.json().catch(()=>({error:'请求失败'}));throw new ApiError(data.error?.message||data.error||data.detail||`HTTP ${response.status}`,response.status,data.error?.code||'HTTP_ERROR');}
 return response.json();
}
