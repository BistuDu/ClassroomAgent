"""Pi SDK discovery and immutable, project-local Skill snapshots."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from . import config
from .courses import fail


TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".css", ".js", ".html"}
LEGACY_ALIASES = {
    "course": "course-authoring",
    "slides": "slide-design",
    "simulation": "interactive-simulation",
    "narration": "narration-actions",
    "inspection": "inspection-quality",
    "quiz": "quiz-design",
}
LEGACY_PATHS = {
    ('course-authoring', 'SKILL.md'): ('stage-design', 'SKILL.md'),
    ('course-authoring', 'references/course-workflow.md'): ('stage-design', 'references/course-workflow.md'),
    ('course-authoring', 'references/course-workflow-legacy.md'): ('stage-design', 'references/course-workflow-legacy.md'),
    ('course-authoring', 'references/legacy-skill-map.md'): ('stage-design', 'references/legacy-skill-map.md'),
    ('slide-design', 'SKILL.md'): ('slide-craft', 'SKILL.md'),
    ('interactive-simulation', 'SKILL.md'): ('stage-dsl', 'references/simulation.md'),
    ('narration-actions', 'SKILL.md'): ('stage-dsl', 'references/actions.md'),
    ('inspection-quality', 'SKILL.md'): ('stage-design', 'references/inspection.md'),
    ('quiz-design', 'SKILL.md'): ('stage-dsl', 'references/quiz.md'),
}


@dataclass(frozen=True)
class SkillSnapshot:
    payload: dict

    def public(self):
        public = copy.deepcopy({k: v for k, v in self.payload.items() if k != 'resources'})
        public['legacyReads'] = {}
        for (old, path), (name, target) in LEGACY_PATHS.items():
            if path != 'SKILL.md' or name not in self.payload['resources']:
                continue
            text = self.payload['resources'][name][target]
            item = next(s for s in self.payload['skills'] if s['skillId'] == name)
            meta = {'canonicalId': name, 'path': target, 'bodyHash': hashlib.sha256(text.encode()).hexdigest(),
                    'bodyBytes': len(text.encode()), 'skillVersion': item['version']}
            public['legacyReads'][old] = meta
            for alias, canonical in LEGACY_ALIASES.items():
                if canonical == old:
                    public['legacyReads'][alias] = meta
        return public

    def read(self, identifier: str, relative_path: str = 'SKILL.md') -> dict:
        name = LEGACY_ALIASES.get(identifier, identifier)
        requested_path = relative_path
        if name in LEGACY_ALIASES.values():
            mapped = LEGACY_PATHS.get((name, relative_path))
            if mapped is None:
                fail('SKILL_SCOPE', '旧 Skill 仅支持已发布的明确兼容路径')
            name, relative_path = mapped
        resources = self.payload['resources'].get(name)
        if resources is None:
            fail('SKILL_NOT_FOUND', f'未注册的 Skill：{identifier}')
        if (not isinstance(relative_path, str) or not relative_path or '\\' in relative_path
                or any(part in ('', '.', '..') for part in relative_path.split('/'))):
            fail('SKILL_SCOPE', 'Skill 读取路径必须是同一 Skill 内的非空 POSIX 相对路径')
        requested = Path(relative_path)
        if (requested.is_absolute() or requested.suffix.lower() not in TEXT_SUFFIXES
                or (relative_path != 'SKILL.md' and requested.parts[0] not in {'references', 'assets'})):
            fail('SKILL_SCOPE', '只允许读取 SKILL.md、references/ 或 assets/ 内的文本资源')
        if relative_path not in resources:
            fail('SKILL_SCOPE', 'Skill 读取路径越界或文件不在本轮快照中')
        item = next(s for s in self.payload['skills'] if s['skillId'] == name)
        return {'skillId': name, 'requestedId': identifier, 'canonicalId': name,
                'requestedPath': requested_path, 'path': relative_path, 'text': resources[relative_path],
                'bodyHash': hashlib.sha256(resources[relative_path].encode('utf-8')).hexdigest(),
                'bodyBytes': len(resources[relative_path].encode('utf-8')), 'offsetUnit': 'unicode_codepoints',
                'skillVersion': item['version'], 'snapshotVersion': self.payload['version'],
                'diagnostics': copy.deepcopy(self.payload['diagnostics'])}


class SkillRegistry:
    def __init__(self, root: Path | None = None):
        self.root = root or config.ROOT
        self.lock = threading.RLock()
        self.current = SkillSnapshot({'version': 'unavailable', 'skills': [], 'resources': {}, 'diagnostics': []})
        self.reload()

    def reload(self) -> dict:
        with self.lock:
            previous = {s['skillId']: s['version'] for s in self.current.payload['skills']}
            try:
                script = Path(__file__).resolve().parent.parent / 'agent-runtime/skill-resources.ts'
                result = subprocess.run(['node', str(script), str(self.root)], cwd=script.parent.parent,
                                        capture_output=True, text=True, timeout=30, check=True)
                payload = json.loads(result.stdout)
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                payload = {'version': 'unavailable', 'skills': [], 'resources': {},
                           'diagnostics': [{'type': 'error', 'message': f'Skill 资源加载失败：{type(exc).__name__}'}],
                           'loadError': f'Skill 资源加载失败：{type(exc).__name__}'}
            current = {s['skillId']: s['version'] for s in payload['skills']}
            payload['changes'] = {
                'added': sorted(current.keys() - previous.keys()),
                'removed': sorted(previous.keys() - current.keys()),
                'changed': sorted(k for k in current.keys() & previous.keys() if current[k] != previous[k]),
            }
            self.current = SkillSnapshot(payload)
            return self.current.public()

    def snapshot(self, *, refresh=False) -> SkillSnapshot:
        with self.lock:
            if refresh:
                self.reload()
            return self.current

    def read(self, identifier: str, relative_path: str = 'SKILL.md') -> dict:
        return self.snapshot().read(identifier, relative_path)

    def index(self) -> list[dict]:
        return self.current.public()['skills']
