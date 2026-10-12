"""Server-owned classroom capabilities, shared by model requests and execution."""
from copy import deepcopy


_DEFINITIONS = (
    ('spotlight', '聚光突出幻灯片元素', {'elementId': {'type': 'string'}}, ['elementId']),
    ('laser', '激光指示幻灯片元素', {'elementId': {'type': 'string'}}, ['elementId']),
    ('widget_setState', '设置当前实验参数并读取真实观察', {'state': {'type': 'object'}}, ['state']),
    ('widget_highlight', '突出实验控件', {'target': {'type': 'string'}}, ['target']),
    ('widget_annotation', '添加临时实验注释', {'target': {'type': 'string'}, 'content': {'type': 'string'}}, ['target', 'content']),
    ('widget_reveal', '显示实验声明内容', {'target': {'type': 'string'}}, ['target']),
)
_REGISTERED = frozenset(name for name, *_ in _DEFINITIONS)
_ROLE_TOOLS = {'teacher': _REGISTERED}
_PAGE_TOOLS = {
    'slide': frozenset(('spotlight', 'laser')),
    'interactive': frozenset(('widget_setState', 'widget_highlight',
                              'widget_annotation', 'widget_reveal')),
    'quiz': frozenset(),
}


def available_tool_names(role: str, page_type: str) -> tuple[str, ...]:
    allowed = _ROLE_TOOLS.get(role, frozenset()) & _PAGE_TOOLS.get(page_type, frozenset()) & _REGISTERED
    return tuple(name for name, *_ in _DEFINITIONS if name in allowed)


def tool_schemas(role: str, page_type: str) -> list[dict]:
    """Fresh nested schemas per request; unknown identities never inherit tools."""
    allowed = available_tool_names(role, page_type)
    result = []
    for name, description, properties, required in deepcopy(_DEFINITIONS):
        if name not in allowed:
            continue
        if name.startswith('widget_'):
            properties = {'sceneId': {'type': 'string'}, **properties}
            required = ['sceneId', *required]
        result.append({'name': name, 'description': description,
                       'parameters': {'type': 'object', 'properties': properties,
                                      'required': required, 'additionalProperties': False}})
    return result


def capability_instructions(tools: list[dict]) -> str:
    """Describe exactly the capabilities sent with this model request."""
    if not tools:
        return '当前页真实证据已由运行层自动提供；当前角色和页面没有可用演示工具。'
    text = '当前页面仅可使用以下课堂工具：' + '；'.join(
        tool['name'] + '（' + tool['description'] + '）' for tool in tools) + '。'
    text += '当前页真实证据已自动提供。演示仅限当前页；先调用操作，收到实际回执再解释，不要猜测结果。'
    if any(tool['name'] in ('spotlight', 'laser') for tool in tools):
        text += '聚光和激光只传 elementId，页面由运行层绑定。'
    return text
