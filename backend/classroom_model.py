"""Normalize actual model SSE. No SDK authoring events or synthetic actor text."""
import json
from collections.abc import Callable

import httpx

from .config import settings
from .courses import fail


def response_input(messages):
    items = []
    for message in messages:
        if message['role'] == 'tool':
            items.append({'type': 'function_call_output', 'call_id': message['tool_call_id'],
                          'output': message['content']})
        else:
            if message.get('content'):
                items.append({'role': message['role'], 'content': message['content']})
            for call in message.get('tool_calls', []):
                items.append({'type': 'function_call', 'call_id': call['id'],
                              'name': call['function']['name'], 'arguments': call['function']['arguments']})
    return items


class ClassroomModel:
    def __init__(self, config=settings):
        self.settings = config
        self.client = httpx.AsyncClient(timeout=config.classroom_provider_timeout_seconds,
                                       trust_env=False)

    async def close(self):
        await self.client.aclose()

    async def generate(self, system: str, messages: list, tools: list,
                       on_delta: Callable[[str], None]) -> dict:
        config = self.settings.classroom
        # Protect in-flight tool call/result pairs: never silently prune them.
        estimated = len(json.dumps([system, messages, tools], ensure_ascii=False).encode('utf-8')) // 2 + 1
        if estimated > self.settings.classroom_context_tokens:
            fail('CLASSROOM_CONTEXT_BUDGET', '当前页证据与未结算调用超过课堂上下文预算，请缩小问题或开始新一轮')
        if not all(config[k] for k in ('apiKey', 'baseUrl', 'model')):
            fail('MISSING_CONFIG', '课堂模型缺少完整配置，请检查 CLASSROOM_* 或当前制作服务')
        api = config['api']
        if api == 'openai-responses':
            path = '/responses'
            payload = {'model': config['model'], 'instructions': system,
                       'input': response_input(messages), 'store': False, 'stream': True,
                       'max_output_tokens': self.settings.classroom_max_tokens}
            if config['provider'] == 'deepseek':
                payload['reasoning'] = {'effort': 'none'}
            if tools:
                payload['tools'] = [{'type': 'function', **tool} for tool in tools]
        elif api == 'openai-completions':
            path = '/chat/completions'
            payload = {'model': config['model'], 'messages': [{'role': 'system', 'content': system}, *messages],
                       'stream': True, 'max_tokens': self.settings.classroom_max_tokens,
                       'stream_options': {'include_usage': True}}
            if config['provider'] == 'deepseek':
                # DeepSeek Flash defaults to high thinking. Small classroom
                # replies/director JSON must not spend their budget on it.
                payload['thinking'] = {'type': 'disabled'}
            if tools:
                payload['tools'] = [{'type': 'function', 'function': tool} for tool in tools]
        else:
            fail('CLASSROOM_PROTOCOL', '课堂模型协议不受支持')
        text, calls, reason, usage = '', {}, None, {}
        try:
            async with self.client.stream('POST', config['baseUrl'].rstrip('/') + path,
                                          headers={'Authorization': 'Bearer ' + config['apiKey']},
                                          json=payload) as response:
                if response.status_code >= 400:
                    await response.aread()
                    fail('CLASSROOM_MODEL_HTTP', f'课堂模型 HTTP {response.status_code}: ' +
                         self.settings.redact(response.text[:1500]))
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == '[DONE]':
                        continue
                    try:
                        value = json.loads(raw)
                    except ValueError:
                        fail('CLASSROOM_MODEL_STREAM', '模型返回无效流式 JSON')
                    if value.get('error'):
                        fail('CLASSROOM_MODEL_STREAM', self.settings.redact(str(value['error'])[:1500]))
                    if api == 'openai-completions':
                        usage = value.get('usage') or usage
                        for choice in value.get('choices', []):
                            if choice.get('index', 0) != 0:
                                continue
                            delta = choice.get('delta') or {}
                            part = delta.get('content') or ''
                            if isinstance(part, list):
                                part = ''.join(p.get('text', '') for p in part)
                            if part:
                                text += part
                                on_delta(part)
                            for call in delta.get('tool_calls', []):
                                item = calls.setdefault(str(call['index']), {'id': '', 'name': '', 'arguments': ''})
                                if call.get('id'):
                                    item['id'] = call['id']
                                function = call.get('function') or {}
                                item['name'] += function.get('name') or ''
                                item['arguments'] += function.get('arguments') or ''
                            reason = choice.get('finish_reason') or reason
                    else:
                        kind = value.get('type')
                        if kind == 'response.output_text.delta':
                            part = value.get('delta', '')
                            text += part
                            on_delta(part)
                        elif kind == 'response.output_item.added' and value.get('item', {}).get('type') == 'function_call':
                            item = value['item']
                            calls[item['id']] = {'id': item['call_id'], 'name': item['name'],
                                                 'arguments': item.get('arguments') or ''}
                        elif kind == 'response.function_call_arguments.delta':
                            item = calls.get(value['item_id'])
                            if item is None:
                                fail('CLASSROOM_MODEL_STREAM', '工具参数流缺少调用身份')
                            item['arguments'] += value.get('delta', '')
                        elif kind == 'response.output_item.done' and value.get('item', {}).get('type') == 'function_call':
                            item = value['item']
                            calls[item['id']] = {'id': item['call_id'], 'name': item['name'], 'arguments': item['arguments']}
                        elif kind in ('response.completed', 'response.incomplete', 'response.failed'):
                            final = value.get('response') or {}
                            reason = (final.get('incomplete_details') or {}).get('reason') or final.get('status')
                            usage = final.get('usage') or {}
                            if final.get('error'):
                                fail('CLASSROOM_MODEL_STREAM', self.settings.redact(str(final['error'])))
        except httpx.HTTPError as exc:
            fail('CLASSROOM_MODEL_NETWORK', '课堂模型连接中断：' + type(exc).__name__)
        valid = {'stop', 'tool_calls'} if api == 'openai-completions' else {'completed'}
        if reason not in valid:
            fail('CLASSROOM_MODEL_INCOMPLETE', f'课堂模型未完整结束（{reason or "缺少结束事件"}），已显示文字保留')
        result_calls = []
        for call in calls.values():
            if not call['id'] or not call['name']:
                fail('CLASSROOM_MODEL_STREAM', '工具调用缺少 ID 或名称')
            try:
                args = json.loads(call['arguments'])
            except ValueError:
                fail('CLASSROOM_MODEL_STREAM', '工具参数被截断或不是 JSON')
            if not isinstance(args, dict):
                fail('CLASSROOM_MODEL_STREAM', '工具参数必须为对象')
            result_calls.append({**call, 'parameters': args})
        if not text.strip() and not result_calls:
            fail('CLASSROOM_MODEL_EMPTY', '课堂模型没有返回发言或工具')
        return {'text': text, 'calls': result_calls, 'finishReason': reason, 'usage': usage}
