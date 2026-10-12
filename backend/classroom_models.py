"""Learning contracts are separate from Pi authoring sessions and course documents."""
from typing import Any, Literal

from pydantic import Field

from .models import Model, Stage

RoleId = Literal['teacher', 'curious', 'notetaker', 'thinker']


class ClassroomRole(Model):
    id: RoleId
    name: str
    description: str
    voice: str
    model: str


class PlaybackCursor(Model):
    sceneId: str
    actionId: str | None = None
    phase: Literal['before', 'playing', 'after', 'page_end'] = 'before'
    audioId: str | None = None
    audioSignature: str | None = None
    audioTime: float = Field(default=0, ge=0)
    experimentState: dict[str, Any] | None = None
    displayState: dict[str, Any] | None = None
    focus: str | None = None
    laser: str | None = None
    instanceId: str | None = None
    playing: bool = False


class ClassroomSession(Model):
    id: str
    stageId: str
    ownerId: str
    revision: int
    fingerprint: str
    stage: Stage
    roles: list[ClassroomRole]
    state: Literal['paused', 'lecture', 'discussion_prompt', 'running', 'waiting_user',
                   'waiting_tool', 'waiting_audio', 'audio_error', 'interrupted', 'version_conflict', 'waiting_lesson']
    generation: int = 0
    activeDialogueId: str | None = None
    roundId: str | None = None
    cursor: PlaybackCursor
    returnCursor: PlaybackCursor | None = None
    consumedDiscussions: dict[str, Literal['joined', 'skipped'] ] = Field(default_factory=dict)
    pending: dict[str, Any] | None = None
    attempts: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    summary: str = ''
    lastObservation: dict[str, Any] | None = None
    createdAt: str
    updatedAt: str


class ClassroomDialogue(Model):
    id: str
    ownerId: str
    stageId: str
    sourceClassroomId: str
    sceneId: str
    planPageId: str | None = None
    startingPageNumber: int | None = None
    type: Literal['qa', 'discussion', 'legacy']
    title: str
    status: Literal['active', 'waiting_user', 'completed', 'interrupted']
    endReason: str | None = None
    summary: str = ''
    createdAt: str
    updatedAt: str


class ClassroomEvent(Model):
    seq: int
    eventId: str
    classroomId: str
    dialogueId: str | None = None
    roundId: str | None = None
    generation: int
    source: Literal['classroom_graph', 'classroom_service', 'classroom_player']
    kind: str
    speakerId: RoleId | None = None
    messageId: str | None = None
    toolCallId: str | None = None
    sceneId: str | None = None
    data: dict[str, Any]
    createdAt: str


class NewClassroom(Model):
    stageId: str
    expectedRevision: int = Field(ge=1)
    requestId: str = Field(min_length=1, max_length=200)


class ClassroomCommand(Model):
    requestId: str = Field(min_length=1, max_length=200)
    controllerId: str = Field(min_length=1, max_length=200)
    kind: Literal['question', 'join', 'skip', 'continue', 'pause', 'stop', 'navigate',
                  'start', 'resume_interaction', 'text_only', 'retry_audio']
    text: str = Field(default='', max_length=8000)
    markerId: str | None = None
    cursor: PlaybackCursor | None = None
    sceneId: str | None = None
    confirmEnd: bool = False
    expectedDialogueId: str | None = None
    expectedGeneration: int | None = None


class ClassroomProgress(Model):
    controllerId: str
    generation: int = Field(ge=0)
    cursor: PlaybackCursor
    markerId: str | None = None


class ClassroomAck(Model):
    controllerId: str
    generation: int = Field(ge=0)
    operationId: str
    sceneId: str
    instanceId: str | None = None
    status: Literal['completed', 'failed', 'text_only']
    result: dict[str, Any] = Field(default_factory=dict)


class ClassroomOperation(Model):
    id: str
    classroomId: str
    roundId: str | None
    generation: int
    kind: Literal['model', 'tts', 'tool', 'audio', 'restore']
    requestHash: str
    state: Literal['pending', 'running', 'completed', 'failed', 'unknown', 'cancelled']
    arguments: dict[str, Any]
    deliveryInstanceId: str | None = None
    result: dict[str, Any] | None = None
    createdAt: str
    updatedAt: str
