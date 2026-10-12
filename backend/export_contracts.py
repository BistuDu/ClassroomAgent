import json
from .config import ROOT
from .models import Stage, Scene, Action, Plan
from .tool_args import TOOLS
from .timeline import TimelineNode, WorkbenchEvent, BridgeEvent
from .tool_result import ToolDetails, ToolResult
from .classroom_models import (ClassroomSession, ClassroomRole, PlaybackCursor, ClassroomEvent,
                               NewClassroom, ClassroomCommand, ClassroomProgress, ClassroomAck,
                               ClassroomOperation, ClassroomDialogue)


def tool_parameters(model):
    """Keep union validation while exposing an object root to model APIs."""
    schema = model.model_json_schema()
    if schema.get('type') == 'object':
        return schema
    branches = schema.get('oneOf') or schema.get('anyOf')
    if not branches:
        raise ValueError(f'{model.__name__}: tool parameters must be an object')
    definitions = schema.get('$defs', {})
    properties = {}
    required = None
    for branch in branches:
        resolved = definitions[branch['$ref'].split('/')[-1]] if '$ref' in branch else branch
        if resolved.get('type') != 'object':
            raise ValueError(f'{model.__name__}: non-object tool union branch')
        required = set(resolved.get('required', [])) if required is None else required & set(resolved.get('required', []))
        for name, field in resolved.get('properties', {}).items():
            alternatives = properties.setdefault(name, [])
            if field not in alternatives:
                alternatives.append(field)
    # The original oneOf still enforces branch-specific required/extra fields.
    schema.update(type='object', properties={
        name: fields[0] if len(fields) == 1 else {'anyOf': fields}
        for name, fields in properties.items()
    }, required=sorted(required or []), additionalProperties=False)
    return schema


def ts(schema: dict) -> str:
    if '$ref' in schema:
        return schema['$ref'].split('/')[-1]
    if 'const' in schema:
        return json.dumps(schema['const'], ensure_ascii=False)
    if 'enum' in schema:
        return ' | '.join(json.dumps(v, ensure_ascii=False) for v in schema['enum'])
    union = schema.get('anyOf') or schema.get('oneOf')
    if union:
        return '(' + ' | '.join(ts(v) for v in union) + ')'
    kind = schema.get('type')
    if kind == 'array':
        return f'Array<{ts(schema.get("items", {}))}>'
    if kind == 'object':
        if 'properties' not in schema:
            additional = schema.get('additionalProperties', {})
            return f'Record<string, {ts(additional) if isinstance(additional, dict) else "unknown"}>'
        required = list(schema.get('properties', {}))
        return '{ ' + '; '.join(f'{json.dumps(k)}{"" if k in required else "?"}: {ts(v)}' for k, v in schema['properties'].items()) + ' }'
    return {'string': 'string', 'number': 'number', 'integer': 'number', 'boolean': 'boolean', 'null': 'null'}.get(kind, 'unknown')


def main():
    schemas = {m.__name__: m.model_json_schema() for m in (Stage, Scene, Action, Plan, TimelineNode, WorkbenchEvent, BridgeEvent, ToolDetails, ToolResult,
        ClassroomSession, ClassroomRole, PlaybackCursor, ClassroomEvent, NewClassroom,
        ClassroomCommand, ClassroomProgress, ClassroomAck, ClassroomOperation, ClassroomDialogue)}
    tools = {name: {'description': description, 'parameters': tool_parameters(model)} for name, (model, description) in TOOLS.items()}
    (ROOT / 'contracts/schema.json').write_text(json.dumps({'protocolVersion': 2, 'models': schemas, 'tools': tools}, ensure_ascii=False, indent=2))
    definitions = {}
    for name, schema in schemas.items():
        definitions.update(schema.get('$defs', {}))
        definitions[name] = schema
    types = '// Generated from Python models. Run npm run contracts; do not edit.\n'
    types += '\n'.join(f'export type {name} = {ts(schema)};' for name, schema in definitions.items())
    (ROOT / 'contracts/generated.ts').write_text(types + '\n')

if __name__ == '__main__':
    main()
