import json
import unittest

import httpx

from backend.classroom_model import ClassroomModel
from backend.classroom_tools import tool_schemas
from backend.config import Settings
from backend.courses import DomainError


class ModelStreamTests(unittest.IsolatedAsyncioTestCase):
    async def run_stream(self, api, frames, status=200, provider='compatible', tools=None):
        config = Settings(_env_file=None, classroom_model='fixture', classroom_base_url='https://model.invalid/v1',
                          classroom_api_key='fixture-key', classroom_api=api, classroom_provider=provider)
        model = ClassroomModel(config)
        await model.client.aclose()
        received, deltas = [], []
        def respond(request):
            received.append(json.loads(request.content))
            if not hasattr(self, 'captured_requests'):
                self.captured_requests = []
            self.captured_requests.append({'api': api, 'payload': received[-1]})
            content = ''.join('data: ' + json.dumps(f) + '\n\n' for f in frames)
            return httpx.Response(status, content=content, headers={'content-type': 'text/event-stream'})
        model.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            result = await model.generate('教师职责', [{'role': 'user', 'content': '问题'}],
                tools if tools is not None else [{'name': 'read', 'description': '读取', 'parameters': {'type': 'object', 'properties': {}}}], deltas.append)
            return result, received, deltas
        finally:
            await model.close()

    async def test_completions_fragments_and_tools(self):
        frames = [
            {'choices': [{'delta': {'content': '先看', 'tool_calls': [{'index': 0, 'id': 'c1', 'function': {'name': 'read', 'arguments': '{'}}]}}]},
            {'choices': [{'delta': {'content': '数据', 'tool_calls': [{'index': 0, 'function': {'arguments': '}'}}]}, 'finish_reason': 'tool_calls'}], 'usage': {'total_tokens': 8}},
        ]
        result, requests, deltas = await self.run_stream('openai-completions', frames)
        self.assertEqual(result['text'], '先看数据')
        self.assertEqual(deltas, ['先看', '数据'])
        self.assertEqual(result['calls'][0]['parameters'], {})
        self.assertEqual(requests[0]['tools'][0]['function']['parameters']['type'], 'object')

    async def test_responses_stream_and_terminal(self):
        frames = [
            {'type': 'response.output_text.delta', 'delta': '观察'},
            {'type': 'response.output_item.added', 'item': {'type': 'function_call', 'id': 'item', 'call_id': 'c1', 'name': 'read', 'arguments': ''}},
            {'type': 'response.function_call_arguments.delta', 'item_id': 'item', 'delta': '{}'},
            {'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'output_tokens': 8}}},
        ]
        result, requests, deltas = await self.run_stream('openai-responses', frames)
        self.assertEqual(result['calls'][0]['id'], 'c1')
        self.assertEqual(requests[0]['tools'][0]['parameters']['type'], 'object')
        self.assertEqual(deltas, ['观察'])

    async def test_truncation_and_service_error_are_not_final_success(self):
        with self.assertRaises(DomainError) as exc:
            await self.run_stream('openai-completions', [{'choices': [{'delta': {'content': '半句'}, 'finish_reason': 'length'}]}])
        self.assertEqual(exc.exception.code, 'CLASSROOM_MODEL_INCOMPLETE')
        with self.assertRaises(DomainError) as exc:
            await self.run_stream('openai-responses', [], status=503)
        self.assertEqual(exc.exception.code, 'CLASSROOM_MODEL_HTTP')

    async def test_deepseek_classroom_disables_default_thinking(self):
        _, requests, _ = await self.run_stream('openai-completions',
            [{'choices': [{'delta': {'content':'回答'}, 'finish_reason':'stop'}]}], provider='deepseek')
        self.assertEqual(requests[0]['thinking'], {'type':'disabled'})
        _, requests, _ = await self.run_stream('openai-responses',
            [{'type':'response.output_text.delta','delta':'回答'},
             {'type':'response.completed', 'response':{'status':'completed'}}], provider='deepseek')
        self.assertEqual(requests[0]['reasoning'], {'effort':'none'})

    async def test_role_page_matrix_in_both_protocol_payloads(self):
        for api in ('openai-completions', 'openai-responses'):
            frames = ([{'choices': [{'delta': {'content': '回答'}, 'finish_reason': 'stop'}]}]
                      if api == 'openai-completions' else
                      [{'type': 'response.output_text.delta', 'delta': '回答'},
                       {'type': 'response.completed', 'response': {'status': 'completed'}}])
            for role in ('teacher', 'curious', 'notetaker', 'thinker', 'director', 'unknown'):
                for page_type in ('slide', 'interactive', 'quiz', 'unknown'):
                    with self.subTest(api=api, role=role, page=page_type):
                        tools = tool_schemas(role, page_type)
                        _, requests, _ = await self.run_stream(api, frames, tools=tools)
                        payload = requests[0]
                        if not tools:
                            self.assertNotIn('tools', payload)
                            continue
                        actual = ([t['function'] for t in payload['tools']]
                                  if api == 'openai-completions' else
                                  [{k: v for k, v in t.items() if k != 'type'} for t in payload['tools']])
                        self.assertEqual(actual, tools)
                        self.assertTrue(all(t['parameters']['type'] == 'object' for t in actual))
                        for tool in actual:
                            schema = tool['parameters']
                            self.assertFalse(schema['additionalProperties'])
                            if tool['name'] in ('spotlight', 'laser'):
                                self.assertEqual(schema['properties'], {'elementId': {'type': 'string'}})
                                self.assertEqual(schema['required'], ['elementId'])
                            else:
                                self.assertIn('sceneId', schema['required'])
