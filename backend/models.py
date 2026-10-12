from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self
from uuid import uuid4
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PlanPage(Model):
    id: str = Field(default_factory=lambda: uid("slot"))
    title: str = Field(min_length=1)
    type: Literal["slide", "interactive", "quiz"]
    brief: str = Field(min_length=1)


class Plan(Model):
    title: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    objectives: list[str] = Field(min_length=1)
    pages: list[PlanPage] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def unique_slots(self) -> Self:
        if len({page.id for page in self.pages}) != len(self.pages):
            raise ValueError("课程方案的页面标识必须唯一")
        return self


class Theme(Model):
    background: str = "#f6f7fb"
    foreground: str = "#142032"
    accent: str = "#1971f5"
    muted: str = "#64748b"
    fontFamily: str = "'PingFang SC', 'Microsoft YaHei', sans-serif"


class Teacher(Model):
    provider: Literal["bailian"] = "bailian"
    model: str
    voice: str
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    language: str = "Chinese"


class Source(Model):
    id: str
    title: str
    url: str
    excerpt: str = ""
    sourceVersion: str = ""
    completeness: Literal['full', 'excerpt_only', 'truncated'] = 'excerpt_only'

    @model_validator(mode="after")
    def public_link(self) -> Self:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("资料链接必须为无凭证的 HTTP(S) URL")
        return self


class ChartPoint(Model):
    x: float = 0
    y: float
    label: str = ""
    series: str = ""


class Element(Model):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    type: Literal["text", "image", "shape", "line", "table", "chart", "formula"]
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    text: str = ""
    mediaId: str | None = None
    alt: str = ""
    shape: Literal["rect", "ellipse", "arrow"] = "rect"
    color: str = "#142032"
    background: str = "transparent"
    stroke: str = "#1971f5"
    strokeWidth: float = Field(default=2, ge=0, le=20)
    fontSize: float = Field(default=26, ge=10, le=120)
    fontWeight: int = Field(default=400, ge=100, le=900)
    align: Literal["left", "center", "right"] = "left"
    radius: float = Field(default=12, ge=0, le=100)
    rotation: float = 0
    opacity: float = Field(default=1, ge=0, le=1)
    rows: list[list[str]] = Field(default_factory=list)
    chartType: Literal["bar", "line", "scatter"] = "bar"
    points: list[ChartPoint] = Field(default_factory=list)
    xLabel: str = ""
    yLabel: str = ""

    @model_validator(mode="after")
    def content_present(self) -> Self:
        if self.type == "image" and not self.mediaId:
            raise ValueError(f"图片 {self.id} 缺少真实 mediaId")
        if self.type in {"text", "formula"} and not self.text.strip():
            raise ValueError(f"元素 {self.id} 缺少文字")
        if self.type == "table" and (not self.rows or len({len(r) for r in self.rows}) != 1):
            raise ValueError(f"表格 {self.id} 必须有等长行")
        if self.type == "chart" and not self.points:
            raise ValueError(f"图表 {self.id} 缺少真实数据")
        return self


class SlideContent(Model):
    type: Literal["slide"] = "slide"
    width: int = Field(default=1280, ge=320, le=3840)
    height: int = Field(default=720, ge=240, le=2160)
    elements: list[Element] = Field(min_length=1)


class Variable(Model):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    label: str
    min: float
    max: float
    default: float
    step: float = Field(default=1, gt=0)
    unit: str = ""
    selector: str = Field(min_length=1)

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if not self.min < self.max or not self.min <= self.default <= self.max:
            raise ValueError(f"变量 {self.name} 的范围或初值无效")
        return self


class Preset(Model):
    name: str
    state: dict[str, Any]


class DragProbe(Model):
    selector: str
    dx: float = 40
    dy: float = 0


class InteractiveContent(Model):
    type: Literal["interactive"] = "interactive"
    html: str = Field(min_length=100, max_length=200000)
    variables: list[Variable] = Field(min_length=1)
    initialState: dict[str, Any]
    presets: list[Preset] = Field(min_length=2, max_length=6)
    controls: list[str] = Field(min_length=1)
    dragProbes: list[DragProbe] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def simulation_contract(self) -> Self:
        if "<html" not in self.html.lower() or "openmaicSimulation" not in self.html:
            raise ValueError("实验必须为完整 HTML，公开 window.openmaicSimulation 契约")
        names = {v.name for v in self.variables}
        if len(names) != len(self.variables):
            raise ValueError("实验变量标识重复")
        for var in self.variables:
            if self.initialState.get(var.name) != var.default or var.selector not in self.controls:
                raise ValueError(f"变量 {var.name} 初值或控件清单不一致")
        for preset in self.presets:
            self.validate_state(preset.state)
        return self

    def validate_state(self, state: dict) -> None:
        allowed = set(self.initialState)
        if not set(state) <= allowed:
            raise ValueError("实验状态包含未声明变量")
        for var in self.variables:
            if var.name in state:
                value = state[var.name]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not var.min <= value <= var.max:
                    raise ValueError(f"实验参数 {var.name} 越界")


class Option(Model):
    id: str
    text: str


class Question(Model):
    id: str
    text: str = Field(min_length=1)
    options: list[Option] = Field(min_length=2, max_length=8)
    answer: str
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_answer(self) -> Self:
        ids = [o.id for o in self.options]
        if len(set(ids)) != len(ids) or self.answer not in ids:
            raise ValueError("选项标识必须唯一且包含正确答案")
        return self


class QuizContent(Model):
    type: Literal["quiz"] = "quiz"
    questions: list[Question] = Field(min_length=1, max_length=10)


class Action(Model):
    id: str = Field(default_factory=lambda: uid("action"))
    type: Literal["speech", "spotlight", "laser", "widget_setState", "widget_highlight", "widget_annotation", "widget_reveal", "discussion"]
    topic: str = ""
    prompt: str = ""
    initiatorId: Literal['curious', 'notetaker', 'thinker'] | None = None
    text: str = ""
    elementId: str | None = None
    target: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    content: str = ""
    audioId: str | None = None
    audioSignature: str | None = None
    audioStatus: Literal["missing", "ready", "stale", "failed"] = "missing"
    duration: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def arguments(self) -> Self:
        if self.type == 'discussion':
            if not self.topic.strip() or self.initiatorId is None:
                raise ValueError('讨论标记需要非空 topic 和有效 initiatorId')
            if self.audioId or self.audioSignature or self.duration or self.audioStatus != 'missing':
                raise ValueError('讨论标记不能绑定预制语音')
            if self.text or self.elementId or self.target or self.state or self.content:
                raise ValueError('讨论标记不能包含其他教学动作参数')
        if self.type == "speech" and not self.text.strip():
            raise ValueError("讲解动作需要 text")
        if self.type in {"spotlight", "laser"} and not self.elementId:
            raise ValueError("幻灯片指示需要 elementId")
        if self.type.startswith("widget_") and self.type != "widget_setState" and not self.target:
            raise ValueError("实验视觉动作需要 target")
        if self.type == "widget_setState" and not self.state:
            raise ValueError("实验参数动作需要 state")
        return self


class Scene(Model):
    id: str = Field(default_factory=lambda: uid("scene"))
    planPageId: str
    title: str
    brief: str
    type: Literal["slide", "interactive", "quiz"]
    content: SlideContent | InteractiveContent | QuizContent = Field(discriminator="type")
    actions: list[Action] = Field(default_factory=list)
    sourceIds: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self) -> Self:
        if self.content.type != self.type:
            raise ValueError("页面类型和内容不匹配")
        if len({a.id for a in self.actions}) != len(self.actions):
            raise ValueError("教学动作标识重复")
        discussions = [i for i, action in enumerate(self.actions) if action.type == 'discussion']
        if len(discussions) > 1 or (discussions and discussions[0] != len(self.actions) - 1):
            raise ValueError('单页至多一个讨论标记，且必须位于全部教学动作末尾')
        ids = set()
        if isinstance(self.content, SlideContent):
            ids = {e.id for e in self.content.elements}
            if len(ids) != len(self.content.elements):
                raise ValueError("幻灯片元素标识重复")
        if isinstance(self.content, QuizContent):
            if len({q.id for q in self.content.questions}) != len(self.content.questions):
                raise ValueError("题目标识重复")
        for action in self.actions:
            if action.type in {"spotlight", "laser"} and action.elementId not in ids:
                raise ValueError(f"动作 {action.id} 的元素不存在")
            if action.type.startswith("widget_"):
                if not isinstance(self.content, InteractiveContent):
                    raise ValueError("实验动作仅适用于实验页")
                if action.type == "widget_setState":
                    self.content.validate_state(action.state)
                elif action.target not in self.content.controls:
                    raise ValueError(f"实验动作目标 {action.target} 不在控件清单中")
        return self


class Stage(Model):
    schemaVersion: Literal[1] = 1
    id: str = Field(default_factory=lambda: uid("stage"))
    title: str
    description: str = ""
    revision: int = Field(default=1, ge=1)
    approvedPlan: Plan
    teacher: Teacher | None = None
    theme: Theme = Field(default_factory=Theme)
    sources: list[Source] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    status: Literal["draft", "ready", "needs_attention"] = "draft"
    outstanding: list[str] = Field(default_factory=list)
    updatedAt: str = ""

    @model_validator(mode="after")
    def unique_references(self) -> Self:
        if len({s.id for s in self.scenes}) != len(self.scenes):
            raise ValueError("页面标识重复")
        if len({s.planPageId for s in self.scenes}) != len(self.scenes):
            raise ValueError("方案页面重复保存")
        slots = {p.id for p in self.approvedPlan.pages}
        page_types = {p.id: p.type for p in self.approvedPlan.pages}
        sources = {s.id for s in self.sources}
        for scene in self.scenes:
            if scene.planPageId not in slots or not set(scene.sourceIds) <= sources:
                raise ValueError("页面方案或来源引用无效")
            if scene.type != page_types[scene.planPageId]:
                raise ValueError("页面类型必须与批准方案一致")
        return self


def audio_signature(action: Action, teacher: Teacher | None) -> str:
    return digest({"text": action.text, "teacher": teacher.model_dump() if teacher else None})


def scene_fingerprint(stage: Stage, scene: Scene) -> str:
    payload = scene.model_dump()
    payload['actions'] = [inspection_action(a) for a in scene.actions]
    return digest({"scene": payload, "theme": stage.theme.model_dump(),
                   "teacher": stage.teacher.model_dump() if stage.teacher else None,
                   "sources": [s.model_dump() for s in stage.sources if s.id in scene.sourceIds],
                   "planPage": next((p.model_dump() for p in stage.approvedPlan.pages if p.id == scene.planPageId), None),
                   "audience": stage.approvedPlan.audience, "objectives": stage.approvedPlan.objectives})


def inspection_digest(value):
    # Pydantic defaults may be ints while a reloaded record contains floats.
    # Equal numeric values must not make persisted reports instantly stale.
    def normalize(v):
        if isinstance(v,float) and v.is_integer():return int(v)
        if isinstance(v,dict):return {k:normalize(x) for k,x in v.items()}
        if isinstance(v,list):return [normalize(x) for x in v]
        return v
    return digest(normalize(value))


def inspection_action(action):
    # Adding optional marker fields must not expire old reports on unchanged actions.
    return action.model_dump(exclude={'topic', 'prompt', 'initiatorId'} if action.type != 'discussion' else set())


def render_fingerprint(stage, scene, width=1280, height=720, state=None, store=None):
    media = []
    if store and scene.type == 'slide':
        for element in scene.content.elements:
            if element.type == 'image':
                m = store.find('media', element.mediaId) or {}
                media.append({'id': element.mediaId, 'sha256': m.get('sha256')})
    return inspection_digest({'version':2,'content':scene.content.model_dump(),'theme':stage.theme.model_dump(),
                   'media':media,'viewport':{'width':width,'height':height},
                   'state':state if state is not None else scene.content.initialState if scene.type=='interactive' else None})


def visual_fingerprint(stage, scene, store=None):
    actions=[{k:v for k,v in inspection_action(a).items() if k not in ('audioId','audioSignature','audioStatus','duration')} for a in scene.actions]
    return inspection_digest({'version':2,'render':render_fingerprint(stage,scene,store=store),'actions':actions,
                   'sources':[s.model_dump() for s in stage.sources if s.id in scene.sourceIds],
                   'planPage':next(p.model_dump() for p in stage.approvedPlan.pages if p.id==scene.planPageId),
                   'audience':stage.approvedPlan.audience,'objectives':stage.approvedPlan.objectives})


def program_fingerprint(stage, scene, store=None):
    from .config import settings
    resources=[]
    ids=[a.audioId for a in scene.actions if a.audioId]
    if scene.type=='slide': ids += [e.mediaId for e in scene.content.elements if e.mediaId]
    if store:
        for id in ids:
            m=store.find('media',id) or {}
            resources.append({'id':id,'sha256':m.get('sha256'),'readable':bool(m.get('file') and (settings.data_dir/'media'/m['file']).is_file())})
    return inspection_digest({'version':2,'semantic':visual_fingerprint(stage,scene,store),'actions':[inspection_action(a) for a in scene.actions],
                   'teacher':stage.teacher.model_dump() if stage.teacher else None,'resources':resources,
                   'protocolCoverage':'1280x720;375x812;declared-presets;manual-controls;drag-probes;widget-ack'})


def report_matches(report, stage, scene, store=None):
    if report.get('fingerprintVersion',1)==1:
        return report.get('fingerprint')==scene_fingerprint(stage,scene)
    expected=visual_fingerprint(stage,scene,store) if report['mode']=='visual' else program_fingerprint(stage,scene,store)
    return report.get('fingerprint')==expected
