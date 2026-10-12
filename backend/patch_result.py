"""Compact patch acknowledgements; course source is read back by path."""
from collections import Counter

from .models import Scene, Stage, scene_fingerprint, visual_fingerprint, program_fingerprint


def scene_tree(scene: Scene) -> dict:
    tree = {}
    if scene.type == 'slide':
        tree['elements'] = {
            'total': len(scene.content.elements),
            'types': dict(Counter(element.type for element in scene.content.elements)),
        }
    elif scene.type == 'interactive':
        tree.update(htmlChars=len(scene.content.html), variables=len(scene.content.variables),
                    controls=len(scene.content.controls), presets=len(scene.content.presets))
    elif scene.type == 'quiz':
        tree['questions'] = len(scene.content.questions)
    tree['actions'] = {
        'total': len(scene.actions),
        'types': dict(Counter(action.type for action in scene.actions)),
        'speechAudioStatus': dict(Counter(action.audioStatus for action in scene.actions
                                          if action.type == 'speech')),
    }
    return tree


def patch_result(before: Stage, saved: dict, operations: list[dict]) -> dict:
    after = Stage.model_validate(saved)
    previous = {scene.id: scene for scene in before.scenes}
    scene_paths = {}
    stage_paths = []
    ops = []
    for operation in operations:
        path = operation['path']
        detail = {'op': operation['op'], 'path': path}
        if operation['op'] == 'replace_text':
            detail['occurrences'] = 1
        ops.append(detail)
        if operation['op'] == 'test':
            continue
        parts = path.split('/')
        paths = scene_paths.setdefault(int(parts[2]), []) if parts[1] == 'scenes' else stage_paths
        if path not in paths:
            paths.append(path)

    updated = []
    inspection_changed = []
    for index, scene in enumerate(after.scenes):
        old = previous[scene.id]
        if old.model_dump() != scene.model_dump():
            updated.append({
                'sceneId': scene.id, 'slotId':scene.planPageId,'pageId': scene.planPageId, 'index': index,
                'path': f'/scenes/{index}', 'title': scene.title, 'type': scene.type,
                'changedPaths': scene_paths.get(index, []), 'tree': scene_tree(scene),
            })
        if visual_fingerprint(before,old)!=visual_fingerprint(after,scene) or program_fingerprint(before,old)!=program_fingerprint(after,scene):
            inspection_changed.append(scene.id)

    return {
        'stageId': after.id, 'revision': after.revision, 'status': after.status,
        'message': f'已执行 {len(ops)} 项操作，更新 {len(updated)} 个页面、{len(stage_paths)} 项课程字段。',
        'updated': {'stagePaths': stage_paths, 'scenes': updated},
        'ops': ops,
        'quality': {
            'ready': after.status == 'ready', 'outstandingCount': len(after.outstanding),
            'inspectionChangedSceneIds': inspection_changed,
        },
        'readback': '页面源码用 read_stage 按 updated.scenes[].path 分段读取；'
                    '完整待完善清单用 read_stage(path="/outstanding") 或 list_scenes 读取。',
    }
