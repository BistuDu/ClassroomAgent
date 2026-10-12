import type { Plan, Stage } from '../../contracts/generated';
export type Question={id:string;kind:string;question:string;plan:Plan|null;planVersion:number;options:string[];stageId?:string|null};
export type Session={id:string;stageId:string|null;activeStageId:string|null;linkedStageIds:string[];state:string;runId:string|null;pendingQuestion:Question|null;snapshotSeq?:number;operation?:{id:string;kind:string}|null};
export type SessionSummary={id:string;stageId:string|null;activeStageId:string|null;linkedStageIds:string[];title:string;state:string;updatedAt:string};
export type CourseSummary=Pick<Stage,'id'|'title'|'revision'|'status'|'outstanding'|'updatedAt'>;
export type Capability={available:boolean;provider:string;model?:string;api?:string;missing:string|null};
export const toolNames:Record<string,string>={web_search:'查找资料',fetch_url:'阅读资料',create_stage:'建立课程',generate_scene:'制作页面',generate_actions:'编写讲解',generate_image:'生成配图',generate_tts:'合成语音',render_scene_preview:'预览页面',check_scene:'检查页面',patch_stage:'修改页面',edit_deck:'调整目录',ask_user:'询问你',read_skill:'读取制作指导',read_stage:'读取课程',list_scenes:'查看制作进度',set_teacher_voice:'设置老师声音',list_voices:'查看音色',list_stages:'查看课程',grep_stage:'检索课程'};
export const statusNames:Record<string,string>={running:'进行中',streaming:'正在回复',failed:'失败',completed:'完成',cancelled:'已停止',interrupted:'已中断',partial:'部分完成',waiting:'等待回答',answered:'已回答',pending:'等待配音',requesting:'正在合成',downloading:'正在下载',ready:'可试听',uncertain:'结果未知',stale:'已过期',missing:'缺少语音'};
