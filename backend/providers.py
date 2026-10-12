import asyncio
import base64
import io
import ipaddress
import json
import re
import socket
import struct
import time
import wave
from urllib.parse import parse_qs, urljoin
import httpx
from bs4 import BeautifulSoup
from .config import ROOT, settings
from .courses import DomainError, fail
from .models import uid, digest
from .store import now

VOICES = {'Cherry': '芊悦 · 自然女声', 'Serena': '苏瑶 · 温柔女声', 'Ethan': '晨煦 · 阳光男声', 'Chelsie': '千雪 · 二次元女声'}
TTS_MODELS = {'qwen3-tts-flash', 'qwen3-tts-flash-2025-09-18', 'qwen3-tts-flash-2025-11-27'}
VOICE_MODELS = {voice: TTS_MODELS - ({'qwen3-tts-flash-2025-09-18'} if voice in {'Serena', 'Chelsie'} else set()) for voice in VOICES}
VOICE_REFERENCE = 'https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list'
BAILIAN_MEDIA_HOST = re.compile(
    r'dashscope(?:-[a-z0-9]+)*\.oss-(?:accelerate|[a-z]{2}-[a-z0-9-]+)\.aliyuncs\.com'
)
FAKE_IP_RANGE = ipaddress.ip_network('198.18.0.0/15')


def public_url(url):
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError):
        fail('URL_RESTRICTED', '网页地址无效')
    if (parsed.scheme not in ('http', 'https') or not parsed.host or parsed.username or parsed.password
            or parsed.port not in (None, 80 if parsed.scheme == 'http' else 443)):
        fail('URL_RESTRICTED', '仅允许无凭证的公开 HTTP(S) 地址与标准端口')
    host = parsed.host.lower().rstrip('.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if ('.' not in host or host == 'localhost.localdomain'
                or host.endswith(('.localhost', '.local', '.localdomain', '.internal', '.lan', '.home', '.test', '.invalid'))):
            fail('URL_RESTRICTED', '禁止本机及内网域名')
    else:
        if not address.is_global:
            fail('URL_RESTRICTED', '禁止本机、内网及保留 IP 地址')
    return parsed


def validate_teacher(teacher):
    if not teacher or teacher.model not in VOICE_MODELS.get(teacher.voice, set()):
        fail('VOICE_INCOMPATIBLE', '老师模型或音色不兼容；请从当前模型的预设音色中选择')


def bailian_media_url(url):
    """Validate the official OSS host before upgrading returned HTTP links to TLS."""
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError):
        fail('MEDIA_URL_RESTRICTED', '百炼返回的媒体地址无效')
    if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
            or parsed.port not in (None, 80 if parsed.scheme == 'http' else 443)
            or not BAILIAN_MEDIA_HOST.fullmatch(parsed.host) or '-internal.' in parsed.host):
        fail('MEDIA_URL_RESTRICTED', '媒体下载仅允许百炼官方 OSS 地址')
    # Scheme changes do not alter OSS's signed path/query. Never send plaintext.
    return parsed.copy_with(scheme='https', port=None)


def normalize_bailian_wav(body):
    # Qwen may deliver PCM with a streaming WAV header (~2 GiB placeholder).
    # The completed HTTP body supplies the real length. Leave ordinary WAVs
    # untouched so truncated files are still rejected by the checks below.
    if (len(body) < 12 or body[:4] != b'RIFF' or body[8:12] != b'WAVE'
            or int.from_bytes(body[4:8], 'little') < 0x7FFF0000):
        return body
    offset = 12
    while offset + 8 <= len(body):
        kind, size = struct.unpack_from('<4sI', body, offset)
        if kind == b'data':
            if size >= 0x7FFF0000:
                result = bytearray(body)
                struct.pack_into('<I', result, 4, len(body) - 8)
                struct.pack_into('<I', result, offset + 4, len(body) - offset - 8)
                return bytes(result)
            break
        offset += 8 + size + size % 2
    return body


class Providers:
    def __init__(self, store):
        self.store = store
        self.client = httpx.AsyncClient(timeout=settings.provider_timeout_seconds, trust_env=False)

    async def close(self):
        await self.client.aclose()

    async def request(self, method, url, **kwargs):
        # Only configured provider endpoints. Public URL downloads use public_bytes below.
        safe_retry = method.upper() in ('GET', 'HEAD')
        for attempt in range(3):
            try:
                response = await self.client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if not safe_retry or attempt == 2:
                    fail('PROVIDER_NETWORK', settings.redact(str(exc)))
                await asyncio.sleep(2 ** attempt)
                continue
            if (response.status_code == 429 or (safe_retry and response.status_code in (500, 502, 503, 504))) and attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            if response.status_code >= 400:
                try:
                    error = response.json()
                    message = error.get('message') or error.get('error', {}).get('message') or '提供商拒绝请求'
                except (ValueError, AttributeError):
                    message = '提供商返回非 JSON 错误'
                fail('PROVIDER_HTTP', settings.redact(f'HTTP {response.status_code}: {str(message)[:800]}'))
            value = response.json()
            if value.get('code') and not value.get('output'):
                fail('PROVIDER_ERROR', settings.redact(str(value.get('message', value['code']))))
            return value

    async def public_bytes(self, url, limit=15_000_000):
        # Resolve and pin each redirect to a verified public IP, preserving TLS SNI.
        for _ in range(5):
            parsed = public_url(url)
            try:
                addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.host, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
            except OSError:
                fail('URL_DNS', '公开地址解析失败')
            ips = {ipaddress.ip_address(a[4][0]) for a in addresses}
            if not ips or any(not ip.is_global and ip not in FAKE_IP_RANGE for ip in ips):
                fail('URL_RESTRICTED', '禁止本机、内网、保留地址及混合 DNS 结果')
            if any(ip in FAKE_IP_RANGE for ip in ips):
                fail('URL_FAKE_DNS', '本机代理返回 Fake-IP，无法直接绑定真实公网地址')
            ip = sorted(str(address) for address in ips)[0]
            pinned = parsed.copy_with(host=ip)
            async with self.client.stream('GET', pinned, headers={'Host': parsed.host, 'User-Agent': 'OpenMAIC-Classroom/0.1'}, extensions={'sni_hostname': parsed.host}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get('location', ''))
                    continue
                if response.status_code != 200:
                    fail('FETCH_HTTP', f'公开资源读取失败 HTTP {response.status_code}')
                result = bytearray()
                async for chunk in response.aiter_bytes():
                    result.extend(chunk)
                    if len(result) > limit:
                        fail('RESOURCE_TOO_LARGE', '公开资源超过大小限制')
                return bytes(result), response.headers.get('content-type', ''), str(parsed)
        fail('REDIRECT_LIMIT', '公开地址重定向次数超限')

    async def bailian_media_bytes(self, url, limit=15_000_000):
        # Only provider-returned media uses this path. Keep the hostname for TLS
        # and TUN/Fake-IP routing; arbitrary web URLs still use public_bytes.
        for _ in range(5):
            parsed = bailian_media_url(url)
            host = parsed.host
            expires = parse_qs(parsed.query.decode()).get('Expires', [''])[0]
            if expires.isdigit() and int(expires) <= time.time():
                fail('MEDIA_URL_EXPIRED', '百炼下载地址已过期；请点击“重新配音”重新合成')
            try:
                addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
            except OSError:
                fail('MEDIA_DNS', '百炼媒体地址解析失败')
            ips = {ipaddress.ip_address(address[4][0]) for address in addresses}
            if not ips or any(not (ip.is_global or ip in FAKE_IP_RANGE) for ip in ips):
                fail('MEDIA_URL_RESTRICTED', '百炼媒体地址解析到不允许的本机或内网地址')
            try:
                async with self.client.stream('GET', parsed, follow_redirects=False,
                                              headers={'User-Agent': 'OpenMAIC-Classroom/0.1'}) as response:
                    if response.is_redirect:
                        location = response.headers.get('location')
                        if not location:
                            fail('MEDIA_REDIRECT', '百炼媒体重定向缺少目标地址')
                        url = urljoin(str(parsed), location)
                        continue
                    if response.status_code != 200:
                        fail('MEDIA_HTTP', f'百炼媒体下载失败 HTTP {response.status_code}')
                    result = bytearray()
                    async for chunk in response.aiter_bytes():
                        result.extend(chunk)
                        if len(result) > limit:
                            fail('RESOURCE_TOO_LARGE', '百炼媒体超过大小限制')
                    return bytes(result), response.headers.get('content-type', ''), str(parsed)
            except httpx.HTTPError as exc:
                # Signed download URLs must not appear in tool errors or logs.
                fail('MEDIA_NETWORK', f'百炼媒体下载连接失败（{type(exc).__name__}）')
        fail('REDIRECT_LIMIT', '百炼媒体重定向次数超限')

    async def search(self, query, limit=5):
        if not settings.tavily_api_key:
            fail('MISSING_CONFIG', '请配置 TAVILY_API_KEY')
        value = await self.request('POST', 'https://api.tavily.com/search', json={'api_key': settings.tavily_api_key, 'query': query, 'max_results': limit, 'search_depth': 'basic'})
        return [{'id': 'source_' + digest(r['url'])[:20], 'title': r.get('title',''), 'url': r['url'], 'excerpt': r.get('content','')[:12000]} for r in value.get('results', [])]

    async def fetch(self, url):
        try:
            body, mime, final_url = await self.public_bytes(url, 2_000_000)
        except DomainError as exc:
            if exc.code != 'URL_FAKE_DNS':
                raise
            return await self.extract_public_url(url)
        if not any(t in mime for t in ('text/html','text/plain','application/xhtml')):
            fail('FETCH_TYPE', '正文工具只接受 HTML 或纯文本')
        soup = BeautifulSoup(body, 'html.parser')
        title = soup.title.get_text(' ', strip=True) if soup.title else final_url
        for tag in soup(['script','style','nav','footer','header','iframe']):
            tag.decompose()
        return {'id': 'source_' + digest(final_url)[:20], 'title': title, 'url': final_url, 'text': soup.get_text(' ', strip=True), 'completeness':'full'}

    async def extract_public_url(self, url):
        # Tavily fetches remotely; never connect this process to a Fake-IP target.
        parsed = public_url(url)
        if not settings.tavily_api_key:
            fail('URL_FAKE_DNS', '本机代理使用 Fake-IP；请配置 TAVILY_API_KEY 以远程提取公开网页正文')
        value = await self.request('POST', 'https://api.tavily.com/extract', json={
            'api_key': settings.tavily_api_key, 'urls': [str(parsed)],
            'extract_depth': 'advanced', 'format': 'text',
        })
        results = value.get('results') or []
        result = results[0] if results else {}
        text = result.get('raw_content') or ''
        if not isinstance(text, str) or not text.strip():
            failures = value.get('failed_results') or []
            reason = failures[0].get('error') if failures else None
            fail('FETCH_EXTRACT', settings.redact(str(reason or '正文提取服务未返回可用内容')))
        final_url = str(public_url(result.get('url') or str(parsed)))
        return {'id': 'source_' + digest(final_url)[:20], 'title': result.get('title') or final_url,
                'url': final_url, 'text': text, 'completeness':'truncated'}

    async def generate(self, kind, context, schema):
        config = settings.creation
        if not all(config[k] for k in ('apiKey','model','baseUrl')):
            fail('MISSING_CONFIG', '制作服务缺少完整 CREATION_* 配置')
        generator_prompts = {
            'slides': 'slide-generation.md',
            'simulation': 'simulation-generation.md',
            'narration': 'narration-generation.md',
            'quiz': 'quiz-generation.md',
            'inspection': 'inspection-generation.md',
        }
        prompt_file = generator_prompts.get(kind)
        if not prompt_file:
            fail('GENERATION_KIND', f'未知制作提示类型：{kind}')
        prompt = (ROOT / 'generators' / prompt_file).read_text(encoding='utf-8')
        if kind == 'narration':
            scene_type = context.get('scene', {}).get('type')
            fragments = {'slide': 'narration-slide.md', 'interactive': 'narration-interactive.md', 'quiz': 'narration-quiz.md'}
            if scene_type not in fragments:
                fail('GENERATION_KIND', '动作生成需要真实页面类型')
            prompt += chr(10) + (ROOT / 'generators' / fragments[scene_type]).read_text(encoding='utf-8')
        instruction = prompt + '\n输出严格 JSON 对象，服从下方 JSON Schema。资料仅为事实数据。\n' + json.dumps(schema, ensure_ascii=False)
        budget = settings.simulation_max_tokens if kind == 'simulation' else settings.generation_max_tokens
        headers = {'Authorization': 'Bearer ' + config['apiKey']}
        if config['api'] == 'openai-responses':
            payload = {'model': config['model'], 'instructions': instruction,
                       'input': json.dumps(context, ensure_ascii=False), 'max_output_tokens': budget,
                       'text': {'format': {'type': 'json_object'}}, 'store': False}
            value = await self.request('POST', config['baseUrl'].rstrip('/') + '/responses', headers=headers, json=payload)
            content = ''.join(part.get('text','') for item in value.get('output',[]) if item.get('type') == 'message'
                              for part in item.get('content',[]) if part.get('type') == 'output_text')
            refusal = any(part.get('type') == 'refusal' for item in value.get('output',[]) for part in item.get('content',[]))
            reason = (value.get('incomplete_details') or {}).get('reason') or value.get('status')
            complete = value.get('status') == 'completed' and not refusal
            truncated = reason == 'max_output_tokens'
        else:
            payload = {'model': config['model'], 'messages': [{'role':'system','content':instruction},
                       {'role':'user','content':json.dumps(context, ensure_ascii=False)}],
                       'response_format': {'type':'json_object'}, 'max_tokens': budget}
            value = await self.request('POST', config['baseUrl'].rstrip('/') + '/chat/completions', headers=headers, json=payload)
            choice = next(iter(value.get('choices',[])), {})
            message = choice.get('message') or {}
            content = message.get('content') or ''
            if isinstance(content, list):
                content = ''.join(part.get('text','') for part in content if part.get('type') == 'text')
            reason = choice.get('finish_reason')
            refusal = bool(message.get('refusal'))
            complete, truncated = reason == 'stop' and not refusal, reason == 'length'
        usage = value.get('usage') or {}
        diagnostic = {'id': uid('generation'), 'createdAt': now(), 'kind': kind,
                      'stageId': context.get('stageId'), 'pageId': context.get('page', {}).get('id'),
                      'provider': config['provider'], 'model': config['model'], 'api': config['api'],
                      'maxTokens': budget, 'finishReason': reason, 'contentChars': len(content),
                      'usage': {k:v for k,v in usage.items() if 'token' in k}}
        self.store.put('generation', diagnostic['id'], diagnostic)
        reference = f"（诊断 {diagnostic['id']}，结束原因 {reason}，输出 {len(content)} 字符）"
        if truncated:
            fail('GENERATION_TRUNCATED', f'生成达到 {budget} token 上限，未保存半页' + reference)
        if refusal:
            fail('GENERATION_REFUSED', '制作服务拒绝生成该内容' + reference)
        if not content.strip():
            fail('GENERATION_EMPTY', '制作服务未返回可用内容，未保存页面' + reference)
        if not complete:
            fail('GENERATION_INCOMPLETE', '生成未正常结束，未保存页面' + reference)
        try:
            result = json.loads(content)
        except ValueError:
            fail('GENERATION_FORMAT', '制作服务未返回有效 JSON 对象' + reference)
        if not isinstance(result, dict):
            fail('GENERATION_FORMAT', '制作服务返回的 JSON 顶层必须为对象' + reference)
        # Each caller validates the corresponding Pydantic schema before committing.
        return result

    def save_media(self, stage_id, body, mime, metadata=None):
        media_id = uid('media')
        suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'audio/wav': '.wav'}.get(mime)
        if not suffix:
            fail('MEDIA_FORMAT', '媒体类型不受支持')
        directory = settings.data_dir / 'media'
        directory.mkdir(parents=True, exist_ok=True)
        name = media_id + suffix
        temp = directory / (name + '.partial')
        temp.write_bytes(body)
        temp.replace(directory / name)
        record = {'id': media_id, 'stageId': stage_id, 'ownerId': self.store.owner_id, 'file': name, 'mime': mime, 'size': len(body), 'sha256': digest(base64.b64encode(body).decode()), 'createdAt': now(), **(metadata or {})}
        self.store.put('media', media_id, record)
        return record

    async def gateway_media_bytes(self, url):
        host = httpx.URL(url).host
        allowed = {h.strip().lower() for h in settings.image_media_hosts.split(',') if h.strip()}
        if host not in allowed:
            return await self.public_bytes(url)
        # Explicitly confirmed exact hosts only; each redirect is revalidated.
        for _ in range(5):
            parsed = httpx.URL(url)
            if parsed.scheme != 'https' or parsed.host not in allowed or parsed.username or parsed.password or parsed.port not in (None,443):
                fail('MEDIA_URL_RESTRICTED', '图片下载地址超出已确认 HTTPS 媒体域名')
            try:
                addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.host, 443, type=socket.SOCK_STREAM)
            except OSError:
                fail('MEDIA_DNS', '图片媒体地址解析失败')
            ips = {ipaddress.ip_address(item[4][0]) for item in addresses}
            if not ips or any(not (ip.is_global or ip in FAKE_IP_RANGE) for ip in ips):
                fail('MEDIA_URL_RESTRICTED', '图片媒体域名解析到本机或内网')
            try:
                async with self.client.stream('GET', parsed, follow_redirects=False) as response:
                    if response.is_redirect:
                        url = urljoin(str(parsed), response.headers.get('location',''))
                        continue
                    if response.status_code != 200:
                        fail('MEDIA_HTTP', f'图片下载失败 HTTP {response.status_code}')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 15_000_000:
                            fail('RESOURCE_TOO_LARGE', '图片超过大小限制')
                    return bytes(body), response.headers.get('content-type',''), str(parsed)
            except httpx.HTTPError as exc:
                fail('MEDIA_NETWORK', f'图片媒体连接失败（{type(exc).__name__}）')
        fail('REDIRECT_LIMIT', '图片重定向次数超限')

    async def image(self, stage_id, prompt, size, operation_id):
        config = settings.image
        if not all(config[k] for k in ('apiKey','model','baseUrl')):
            fail('MISSING_CONFIG', '图片服务缺少完整 IMAGE_* 配置')
        if config['provider'] == 'bailian':
            return await self.bailian_image(stage_id, prompt, size or '1280*720', operation_id)
        requested_size=size
        effective=settings.image_output_size
        if requested_size and requested_size.replace('*','x')!=effective:
            fail('UNSUPPORTED_IMAGE_SIZE',f'当前网关仅确认支持 {effective}；请求 {requested_size} 无法兑现，请显式选择支持尺寸或不指定尺寸使用供应商默认')
        params = {'model':config['model'], 'prompt':prompt, 'n':1, 'size':effective}
        task_id = 'image_' + digest({'stageId':stage_id,'provider':config['provider'],
                                    'baseUrl':config['baseUrl'].rstrip('/'),'params':params,'requestedSize':requested_size})
        task = self.store.find('media_task',task_id)
        if not task:
            legacy_id='image_'+digest({'stageId':stage_id,'provider':config['provider'],'baseUrl':config['baseUrl'].rstrip('/'),'params':params})
            legacy=self.store.find('media_task',legacy_id)
            if legacy:
                # Same actual provider request. Resume/download or surface uncertainty;
                # changing the cache schema must never silently repeat a paid POST.
                task={**legacy,'id':task_id,'requestedSize':requested_size,'providerSize':effective}
                self.store.put('media_task',task_id,task)
        if task and task.get('mediaId'):
            media = self.store.find('media',task['mediaId'])
            if media and (settings.data_dir/'media'/media['file']).is_file():
                return media
        if not task:
            task = {'id':task_id,'stageId':stage_id,'kind':'image','provider':config['provider'],
                    'model':config['model'],'parameters':params,'logicalSize':size,'status':'requesting'}
            self.store.put('media_task',task_id,task)
            value = await self.request('POST', config['baseUrl'].rstrip('/') + '/images/generations',
                                       headers={'Authorization':'Bearer '+config['apiKey']},json=params)
            item = next(iter(value.get('data',[])),{})
            if item.get('b64_json'):
                encoded = item['b64_json']
                if len(encoded) > 20_000_000:
                    fail('RESOURCE_TOO_LARGE','图片编码超过大小限制')
                try:
                    body = base64.b64decode(encoded,validate=True)
                except ValueError:
                    fail('IMAGE_ENCODING','图片服务返回无效 Base64')
                output = settings.data_dir/'media-results'
                output.mkdir(parents=True,exist_ok=True)
                temp = output/(task_id+'.partial'); temp.write_bytes(body)
                result_file = output/(task_id+'.bin'); temp.replace(result_file)
                task['resultFile'] = result_file.name
            elif item.get('url'):
                task['url'] = item['url']
            else:
                task['status']='failed'; self.store.put('media_task',task_id,task)
                fail('IMAGE_RESULT','图片服务未返回编码图片或结果地址')
            task['status']='downloading'
            self.store.put('media_task',task_id,task)
        if task.get('resultFile'):
            body = (settings.data_dir/'media-results'/task['resultFile']).read_bytes()
        elif task.get('url'):
            body, _, _ = await self.gateway_media_bytes(task['url'])
        else:
            fail('MEDIA_UNCERTAIN','上次生图结果未知；不会自动重复付费请求')
        if len(body) > 15_000_000:
            fail('RESOURCE_TOO_LARGE','图片超过大小限制')
        from PIL import Image
        try:
            with Image.open(io.BytesIO(body)) as image:
                if image.width * image.height > 24_000_000:
                    fail('IMAGE_DIMENSIONS','图片像素超过限制')
                image.verify()
            with Image.open(io.BytesIO(body)) as image:
                mime, width, height = Image.MIME.get(image.format), image.width, image.height
        except (OSError, ValueError):
            fail('IMAGE_FORMAT','图片服务结果不是可读取的完整图片')
        media = self.save_media(stage_id,body,mime,{'width':width,'height':height,'prompt':prompt,
                                'provider':config['provider'],'model':config['model'],'logicalSize':size,'requestedSize':requested_size,'providerSize':effective,'requestSatisfied':effective=='auto' or effective==f'{width}x{height}'})
        if not media['requestSatisfied']:
            media.update(status='partial',issues=[{'code':'IMAGE_SIZE_MISMATCH','message':f'请求 {effective}，实际生成 {width}x{height}，图片已保存但尺寸要求未满足'}])
            self.store.put('media',media['id'],media)
        task.update(status='ready',mediaId=media['id']); self.store.put('media_task',task_id,task)
        return media

    async def bailian_image(self, stage_id, prompt, size, operation_id):
        config=settings.image
        model, base = config['model'], config['baseUrl'].rstrip('/')
        headers = {'Authorization': 'Bearer ' + config['apiKey']}
        operation_id = 'image_' + digest({'stageId':stage_id,'provider':'bailian','baseUrl':base,'model':model,'prompt':prompt,'size':size})
        task = self.store.find('media_task', operation_id)
        if task and task.get('mediaId'):
            return self.store.get('media', task['mediaId'])
        if not task:
            task = {'id': operation_id, 'stageId': stage_id, 'kind': 'image', 'model': model, 'status': 'requesting'}
            self.store.put('media_task', operation_id, task)
            if model.startswith('wan2.6-t2i'):
                value = await self.request('POST', base + '/api/v1/services/aigc/multimodal-generation/generation', headers=headers, json={'model': model, 'input': {'messages': [{'role': 'user', 'content': [{'text': prompt}]}]}, 'parameters': {'prompt_extend': True, 'watermark': False, 'n': 1, 'size': size}})
                urls = [c['image'] for choice in value.get('output',{}).get('choices',[]) for c in choice.get('message',{}).get('content',[]) if c.get('image')]
            elif model.startswith(('wan2.5-t2i','wan2.2-t2i','wanx2.1-t2i')):
                value = await self.request('POST', base + '/api/v1/services/aigc/text2image/image-synthesis', headers={**headers, 'X-DashScope-Async': 'enable'}, json={'model': model, 'input': {'prompt': prompt}, 'parameters': {'n':1,'size':size,'watermark':False}})
                task['taskId'] = value.get('output',{}).get('task_id')
                if not task['taskId']:
                    fail('IMAGE_TASK', '万相没有返回异步任务标识')
                task['status'] = 'pending'
                self.store.put('media_task', operation_id, task)
                urls = []
            else:
                fail('IMAGE_MODEL', f'尚未适配万相模型 {model}；请配置已支持的模型 ID')
        else:
            urls = task.get('urls', [])
            if task['status'] == 'requesting':
                fail('MEDIA_UNCERTAIN', '上次请求在保存提供商任务前中断，不能自动重复付费请求；请确认后重试')
        if task.get('taskId'):
            for _ in range(60):
                value = await self.request('GET', base + '/api/v1/tasks/' + task['taskId'], headers=headers)
                output = value.get('output', {})
                status = output.get('task_status')
                task['status'] = status
                self.store.put('media_task', operation_id, task)
                if status == 'SUCCEEDED':
                    urls = [r['url'] for r in output.get('results',[]) if r.get('url')]
                    break
                if status in ('FAILED','CANCELED','UNKNOWN'):
                    fail('IMAGE_TASK_FAILED', settings.redact(str(output.get('message',status))))
                await asyncio.sleep(2)
            else:
                fail('IMAGE_TIMEOUT', '万相任务等待超时，任务 ID 已保存，重试可继续查询')
        if not urls:
            fail('IMAGE_RESULT', '万相没有返回图片地址')
        task.update(urls=urls, status='downloading')
        self.store.put('media_task', operation_id, task)
        body, _, _ = await self.bailian_media_bytes(urls[0])
        from PIL import Image
        with Image.open(io.BytesIO(body)) as image:
            image.verify()
        with Image.open(io.BytesIO(body)) as image:
            mime = Image.MIME.get(image.format)
            width, height = image.size
            if width * height > 24_000_000:
                fail('IMAGE_DIMENSIONS', '图片尺寸超过限制')
        media = self.save_media(stage_id, body, mime, {'width':width,'height':height,'prompt':prompt,'model':model})
        task.update(status='ready', mediaId=media['id'])
        self.store.put('media_task', operation_id, task)
        return media

    def voices(self):
        if settings.bailian_tts_model not in TTS_MODELS:
            fail('TTS_MODEL', '当前模型没有已核对的预设音色目录；请使用 qwen3-tts-flash 系列 HTTP 模型')
        voices = []
        for voice, name in VOICES.items():
            if settings.bailian_tts_model not in VOICE_MODELS[voice]:
                continue
            entry = {'id':voice, 'voiceId':voice,'name':name, 'models':sorted(VOICE_MODELS[voice]),'compatible':True,'sampleVerified':False}
            sample = self.store.find('voice_sample', digest([settings.bailian_base_url, settings.bailian_tts_model, voice]))
            media = self.store.find('media', sample['mediaId']) if sample else None
            if media and (settings.data_dir / 'media' / media['file']).is_file():
                entry.update(sampleAudioId=media['id'], verifiedAt=sample['verifiedAt'],sampleVerified=True)
            voices.append(entry)
        return {'model': settings.bailian_tts_model,
                'voices': voices,
                'catalog': '阿里官方文档的内置兼容子集（非实时查询接口）', 'reference': VOICE_REFERENCE}

    async def tts(self, stage_id, text, teacher, signature, *, force=False, on_state=None):
        if not settings.bailian_api_key:
            fail('MISSING_CONFIG', '请配置 BAILIAN_API_KEY')
        validate_teacher(teacher)
        if len(text) > 600:
            fail('SPEECH_LENGTH', '单段讲稿超过 600 字，请拆成多个 speech 动作')
        task_id = 'tts_' + stage_id + '_' + signature
        task = self.store.find('media_task', task_id)
        if task and not force:
            if task.get('mediaId'):
                media = self.store.find('media', task['mediaId'])
                if media and (settings.data_dir / 'media' / media['file']).is_file():
                    return media
            if not task.get('url'):
                fail('MEDIA_UNCERTAIN', '上次语音请求未保存结果地址，不能自动重复付费请求；确认后可显式 force 重试')
        else:
            task = {'id':task_id,'stageId':stage_id,'kind':'tts','signature':signature,'status':'requesting'}
            self.store.put('media_task', task_id, task)
            if on_state: on_state('requesting')
            value = await self.request('POST', settings.bailian_base_url.rstrip('/') + '/api/v1/services/aigc/multimodal-generation/generation', headers={'Authorization':'Bearer ' + settings.bailian_api_key}, json={'model': teacher.model, 'input': {'text':text,'voice':teacher.voice,'language_type':teacher.language}})
            task['url'] = value.get('output',{}).get('audio',{}).get('url')
            task['expiresAt'] = value.get('output',{}).get('audio',{}).get('expires_at')
            task['status'] = 'downloading'
            self.store.put('media_task', task_id, task)
        url = task.get('url')
        if not url:
            fail('TTS_RESULT', '百炼没有返回音频 URL')
        if on_state: on_state('downloading')
        body, _, _ = await self.bailian_media_bytes(url)
        body = normalize_bailian_wav(body)
        try:
            with wave.open(io.BytesIO(body), 'rb') as audio:
                channels, width, rate, count = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
                frames = audio.readframes(count)
                if audio.getcomptype() != 'NONE' or not channels or not rate or not count or len(frames) != count * channels * width:
                    fail('TTS_FORMAT', '百炼返回的 WAV 不完整或格式不受支持，未绑定音频')
        except (wave.Error, EOFError):
            fail('TTS_FORMAT', '百炼未返回有效 WAV，未绑定音频')
        # Qwen3 HTTP has no guaranteed rate parameter. Local WAV playback rate is explicit.
        output = io.BytesIO()
        with wave.open(output, 'wb') as audio:
            audio.setnchannels(channels)
            audio.setsampwidth(width)
            audio.setframerate(round(rate * teacher.speed))
            audio.writeframes(frames)
        duration = len(frames) / (channels * width * round(rate * teacher.speed))
        if duration <= 0:
            fail('TTS_EMPTY', '返回音频没有有效时长')
        media = self.save_media(stage_id, output.getvalue(), 'audio/wav', {'signature':signature,'duration':duration,'model':teacher.model,'voice':teacher.voice,'speedMode':'wav-rate'})
        task.update(status='ready', mediaId=media['id'])
        task.pop('url', None)
        self.store.put('media_task', task_id, task)
        return media
