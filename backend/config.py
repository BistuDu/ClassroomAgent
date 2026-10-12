from pathlib import Path
from pydantic import Field
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    creation_provider: str | None = None
    creation_base_url: str | None = None
    creation_model: str | None = None
    creation_api: Literal['openai-responses', 'openai-completions'] | None = None
    creation_api_key: str | None = None
    creation_context_window: int = Field(default=300000, ge=8192)
    creation_max_tokens: int = Field(default=65536, ge=1024)
    creation_compaction_enabled: bool = True
    creation_compaction_reserve_tokens: int = Field(default=70000, ge=0)
    creation_compaction_keep_recent_tokens: int = Field(default=20000, ge=0)
    creation_thinking_level: Literal['off', 'minimal', 'low', 'medium', 'high'] | None = None
    classroom_provider: str | None = None
    classroom_base_url: str | None = None
    classroom_model: str | None = None
    classroom_api: Literal['openai-responses', 'openai-completions'] | None = None
    classroom_api_key: str | None = None
    classroom_max_tool_calls: int = Field(default=8, ge=1, le=30)
    classroom_max_tokens: int = Field(default=4096, ge=256, le=32768)
    classroom_context_tokens: int = Field(default=24000, ge=4096, le=100000)
    classroom_provider_timeout_seconds: int = Field(default=90, ge=10, le=600)
    classroom_generation_timeout_seconds: int = Field(default=180, ge=30, le=1800)
    classroom_ack_timeout_seconds: int = Field(default=45, ge=10, le=300)
    image_provider: str | None = None
    image_base_url: str | None = None
    image_model: str | None = None
    image_api_key: str | None = None
    image_output_size: str = 'auto'
    image_media_hosts: str = ''
    generation_max_tokens: int = Field(default=65536, ge=1024, le=393216)
    simulation_max_tokens: int = Field(default=65536, ge=1024, le=393216)
    tavily_api_key: str = ""
    bailian_api_key: str = ""
    bailian_base_url: str = "https://dashscope.aliyuncs.com"
    bailian_image_model: str = "wan2.6-t2i"
    bailian_tts_model: str = "qwen3-tts-flash"
    bailian_tts_voice: str = "Cherry"
    openmaic_port: int = 8000
    openmaic_origin: str = "http://127.0.0.1:8000"
    max_tool_calls: int = 120
    run_timeout_seconds: int = 1800
    provider_timeout_seconds: int = 180
    max_repair_rounds: int = Field(default=2, ge=0)

    @property
    def data_dir(self) -> Path:
        return ROOT / "data"

    @property
    def creation(self) -> dict:
        explicit = any(getattr(self, 'creation_' + k) is not None for k in ('provider','base_url','model','api','api_key'))
        if explicit:
            return {'provider': self.creation_provider or 'gateway', 'baseUrl': self.creation_base_url or '',
                    'model': self.creation_model or '', 'api': self.creation_api or 'openai-responses',
                    'apiKey': self.creation_api_key or ''}
        return {'provider': 'deepseek', 'baseUrl': self.deepseek_base_url, 'model': self.deepseek_model,
                'api': 'openai-completions', 'apiKey': self.deepseek_api_key}

    @property
    def classroom(self) -> dict:
        fields = ('provider', 'base_url', 'model', 'api', 'api_key')
        if not any(getattr(self, 'classroom_' + field) is not None for field in fields):
            return dict(self.creation)
        return {'provider': self.classroom_provider or 'gateway',
                'baseUrl': self.classroom_base_url or '', 'model': self.classroom_model or '',
                'api': self.classroom_api or 'openai-responses', 'apiKey': self.classroom_api_key or ''}

    @property
    def image(self) -> dict:
        explicit = any(getattr(self, 'image_' + k) is not None for k in ('provider','base_url','model','api_key'))
        if explicit:
            return {'provider': self.image_provider or 'gateway', 'baseUrl': self.image_base_url or '',
                    'model': self.image_model or '', 'apiKey': self.image_api_key or ''}
        return {'provider': 'bailian', 'baseUrl': self.bailian_base_url, 'model': self.bailian_image_model,
                'apiKey': self.bailian_api_key}

    @property
    def thinking_level(self) -> str:
        return self.creation_thinking_level or ('low' if self.creation['api'] == 'openai-responses' else 'off')

    @property
    def creation_compaction(self) -> dict:
        return {
            'enabled': self.creation_compaction_enabled,
            'reserveTokens': self.creation_compaction_reserve_tokens,
            'keepRecentTokens': self.creation_compaction_keep_recent_tokens,
        }

    def redact(self, text: str) -> str:
        for key in (self.deepseek_api_key, self.tavily_api_key, self.bailian_api_key, self.creation_api_key, self.image_api_key, self.classroom_api_key):
            if key:
                text = text.replace(key, "[redacted]")
        return text

    def capabilities(self) -> dict:
        services = {
            "creation": (all(self.creation[k] for k in ('apiKey','baseUrl','model')), self.creation['provider'], 'CREATION_API_KEY / CREATION_BASE_URL / CREATION_MODEL'),
            "search": (bool(self.tavily_api_key), "Tavily", "TAVILY_API_KEY"),
            "image": (all(self.image[k] for k in ('apiKey','baseUrl','model')), self.image['provider'], 'IMAGE_API_KEY / IMAGE_BASE_URL / IMAGE_MODEL'),
            "tts": (bool(self.bailian_api_key and self.bailian_tts_model), "百炼 TTS", "BAILIAN_API_KEY / BAILIAN_TTS_MODEL"),
            "preview": (any((self.data_dir / "browsers").glob("chromium*")), "浏览器预览", "项目内 Chromium"),
        }
        result = {key: {"available": ok, "provider": name, "missing": None if ok else missing}
                  for key, (ok, name, missing) in services.items()}
        result['creation'].update(model=self.creation['model'], api=self.creation['api'], thinkingLevel=self.thinking_level,
                                  contextWindow=self.creation_context_window, maxTokens=self.creation_max_tokens,
                                  compaction=self.creation_compaction)
        result['image'].update(model=self.image['model'])
        result['tts'].update(model=self.bailian_tts_model)
        result['classroom'] = {
            'available': all(self.classroom[k] for k in ('apiKey', 'baseUrl', 'model')),
            'provider': self.classroom['provider'], 'model': self.classroom['model'],
            'api': self.classroom['api'],
            'maxToolCalls': self.classroom_max_tool_calls, 'maxTokens': self.classroom_max_tokens,
        }
        return result


settings = Settings()
