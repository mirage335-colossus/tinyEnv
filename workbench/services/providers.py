"""Bounded provider adapters for the optional workbench (Python 3.9+, stdlib).

Importing this module never reads credentials or contacts a service. A production
request needs ``network_enabled=True``; injected transports are for offline tests.
Provider-native search/plugins are deliberately unavailable: retrieval belongs to
the curated research service, whose source records can accompany a completion.
"""

from dataclasses import dataclass, field
from datetime import date
import base64
import binascii
import http.client
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping, Optional, Sequence
import urllib.error
import urllib.parse
import urllib.request
import uuid


CLOUD_BASES = {
    'openai': 'https://api.openai.com/v1',
    'openrouter': 'https://openrouter.ai/api/v1',
}
OLLAMA_BASE = 'http://127.0.0.1:11434'
# Reviewed provider base slugs, 2026-10-07. OpenRouter still enforces no-training
# metadata, supported parameters, the price ceiling and no fallback outside this
# allowlist. Exact reviewed knowledge profiles retain their endpoint variants.
OPENROUTER_DEFAULT_ROUTING_PROVIDERS = ('deepinfra', 'together', 'mistral')
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_MODEL_CHARS = 200
MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_CATALOG_MODELS = 2048
MAX_CATALOG_RECORDS = 10000
PARAMETERS = {
    'max_tokens', 'num_predict', 'num_keep', 'num_ctx', 'temperature', 'top_p',
    'reasoning_effort', 'service_tier', 'nitro', 'keep_alive', 'think',
}
PURPOSES = {'chat', 'agent', 'evaluate', 'evaluation', 'scribble', 'ref'}
KNOWLEDGE_PURPOSES = {'evaluate', 'evaluation', 'scribble', 'ref'}
METADATA_FIELDS = {
    'model', 'publisher', 'open_weights', 'terms_reviewed', 'terms_url',
    'reviewed_at', 'input_usd_per_million', 'output_usd_per_million',
    'private_route_available', 'catalog_url', 'license_url',
}


def model_profiles():
    """Reviewed identities, not an automatic model substitution or live listing.

    Catalog/routing review: 2026-10-07. Privacy and prices are also constrained
    by OpenRouter at request time. Retention uses the provider's default.
    """
    entries = (
        ('nvidia/nemotron-3-ultra-550b-a55b', 'nvidia', .50, 2.20, 'deepinfra/fp4', True,
         'https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16'),
        ('deepseek/deepseek-r1-0528', 'deepseek', .50, 2.15, 'deepinfra/fp4', True,
         'https://github.com/deepseek-ai/DeepSeek-R1/blob/main/LICENSE'),
        ('mistralai/mistral-large-4-0', 'mistralai', .68, 2.09, 'mistral', False, ''),
        ('moonshotai/kimi-k3', 'moonshotai', 2.85, 14.25, 'deepinfra/mxfp4', True,
         'https://huggingface.co/moonshotai/Kimi-K3/raw/main/LICENSE'),
        ('nvidia/nemotron-3.5-lightning', 'nvidia', .06, .16, 'deepinfra/bf16', True,
         'https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16'),
    )
    result = []
    for model, publisher, prompt, output, route, opened, license_url in entries:
        metadata = {
            'model': model, 'publisher': publisher, 'open_weights': opened,
            'terms_reviewed': bool(route), 'terms_url': (
                'https://legal.mistral.ai/terms/commercial-terms-of-service/'
                if publisher == 'mistralai' else 'https://deepinfra.com/terms'),
            'reviewed_at': '2026-10-07', 'input_usd_per_million': prompt,
            'output_usd_per_million': output, 'private_route_available': publisher != 'mistralai',
            'catalog_url': 'https://openrouter.ai/api/v1/models/' + model + '/endpoints',
            'license_url': license_url,
        }
        result.append({'provider': 'openrouter', 'model': model,
                       'routing_providers': [route] if route else [],
                       'model_metadata': metadata})
    return result


class ProviderError(RuntimeError):
    """A safe diagnostic: never include service bodies or submitted input."""


def _number(value, minimum, maximum, message, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not minimum <= value <= maximum
            or (integer and not isinstance(value, int))):
        raise ProviderError(message)
    return value


def _base_url(provider, value):
    if not isinstance(value, str):
        raise ProviderError('Invalid provider endpoint.')
    value = value.rstrip('/')
    if provider in CLOUD_BASES:
        if value != CLOUD_BASES[provider]:
            raise ProviderError('Cloud providers require their fixed HTTPS API endpoint.')
        return value
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except ValueError:
        raise ProviderError('Invalid local provider endpoint.') from None
    host = parts.hostname
    try:
        local = bool(host and ipaddress.ip_address(host).is_loopback)
    except ValueError:
        local = host == 'localhost'
    if (parts.scheme != 'http' or not local or parts.username or parts.password
            or parts.query or parts.fragment or parts.path or port is None
            or not 1 <= port <= 65535):
        raise ProviderError('Ollama requires an HTTP loopback endpoint with an explicit port.')
    return value


def _model_name(provider, model):
    if not isinstance(model, str) or not model.strip():
        raise ProviderError('Choose a model in AI: select Available models or Configured models, '
                            'or enter a model ID.')
    if len(model) > MAX_MODEL_CHARS:
        raise ProviderError('Model identifier exceeds the 200-character limit.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*', model):
        raise ProviderError('Invalid model identifier.')
    if any(part in ('', '.', '..') for part in model.split('/')):
        raise ProviderError('Invalid model path.')
    if provider == 'openrouter' and ('/' not in model or model.startswith('openrouter/')):
        raise ProviderError('Choose an explicit publisher/model slug; automatic routers are unavailable.')
    if any(tag in model.lower() for tag in (':online', ':extended', ':floor')):
        raise ProviderError('Unreviewed model routing variants are unavailable.')
    return model


def _parameters(provider, values):
    if not isinstance(values, Mapping) or any(key not in PARAMETERS for key in values):
        raise ProviderError('Unsupported provider parameter; native web tools and plugins are unavailable.')
    # An absent/JSON-null optional generation number asks for the real provider
    # default. Do not turn a blank UI setting into a client-generated limit.
    optional_numbers = {'max_tokens', 'num_predict', 'num_keep', 'num_ctx', 'temperature', 'top_p'}
    result = {name: value for name, value in values.items()
              if value is not None or name not in optional_numbers}
    for name in ('max_tokens', 'num_predict'):
        if name in result:
            _number(result[name], 16 if provider == 'openai' else 1, 65536,
                    'Output tokens must be bounded between 1 and 65536 (OpenAI minimum 16).', True)
    if 'max_tokens' in result and 'num_predict' in result and result['max_tokens'] != result['num_predict']:
        raise ProviderError('Conflicting output token limits.')
    if 'temperature' in result:
        _number(result['temperature'], 0, 2, 'Temperature must be between 0 and 2.')
    if 'top_p' in result:
        _number(result['top_p'], 0, 1, 'Top-p must be between 0 and 1.')
    for name, minimum, maximum in (('num_ctx', 128, 8388608), ('num_keep', 0, 8388608)):
        if name in result:
            _number(result[name], minimum, maximum, 'Invalid bounded Ollama context setting.', True)
    if result.get('num_keep', 0) > result.get('num_ctx', 8388608):
        raise ProviderError('Ollama num_keep cannot exceed num_ctx.')
    if 'reasoning_effort' in result and result['reasoning_effort'] not in (
            'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        raise ProviderError('Invalid reasoning effort.')
    if 'service_tier' in result and result['service_tier'] not in ('auto', 'default', 'flex', 'priority'):
        raise ProviderError('Invalid service tier.')
    if 'nitro' in result and not isinstance(result['nitro'], bool):
        raise ProviderError('Nitro must be a boolean.')
    if 'keep_alive' in result and not re.fullmatch(r'(?:0|[0-9]{1,4}[smh])', str(result['keep_alive'])):
        raise ProviderError('Invalid bounded Ollama keep-alive setting.')
    if 'think' in result and (not isinstance(result['think'], (str, bool))
            or isinstance(result['think'], str) and result['think'] not in ('low', 'medium', 'high')):
        raise ProviderError('Invalid Ollama thinking setting.')
    if provider != 'ollama' and any(name in result for name in ('num_keep', 'num_ctx', 'keep_alive', 'think')):
        raise ProviderError('Context retention parameters are supported only by Ollama.')
    if provider != 'openrouter' and ('nitro' in result or ':nitro' in values.get('model', '')):
        raise ProviderError('Nitro is supported only by OpenRouter.')
    if provider == 'ollama' and any(name in result for name in ('reasoning_effort', 'service_tier')):
        raise ProviderError('Use Ollama thinking settings instead of cloud parameters.')
    return result


@dataclass(frozen=True)
class ProviderConfig:
    provider: str = 'ollama'
    model: str = ''
    base_url: str = ''
    parameters: Mapping[str, Any] = field(default_factory=dict)
    network_enabled: bool = False
    timeout: float = 30
    max_input_bytes: int = 16 * 1024 * 1024
    max_response_bytes: int = 1024 * 1024
    max_output_chars: int = 524288
    max_price_per_million: float = 3.0
    zdr: bool = False  # Legacy input only; retention follows the provider default.
    routing_providers: Sequence[str] = field(default_factory=tuple)
    model_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, values):
        """Only nonsecret settings can be persisted with a chat."""
        if not isinstance(values, Mapping):
            raise ProviderError('Provider settings must be an object.')
        allowed = set(cls.__dataclass_fields__) | {'endpoint'} | PARAMETERS
        if any(key not in allowed for key in values):
            raise ProviderError('Unsupported provider setting; credentials and web plugins cannot be stored with chats.')
        data = dict(values)
        if 'endpoint' in data:
            endpoint = data.pop('endpoint')
            if 'base_url' in data and data['base_url'] != endpoint:
                raise ProviderError('Conflicting provider endpoints.')
            data['base_url'] = endpoint
        parameters = data.get('parameters', {})
        if not isinstance(parameters, Mapping):
            raise ProviderError('Provider parameters must be an object.')
        parameters = dict(parameters)
        for key in PARAMETERS:
            if key in data:
                if key in parameters:
                    raise ProviderError('Duplicate provider parameter.')
                parameters[key] = data.pop(key)
        data['parameters'] = parameters
        data.setdefault('base_url', CLOUD_BASES.get(data.get('provider', 'ollama'), OLLAMA_BASE))
        if data.get('provider') == 'openrouter':
            selected = data.get('model', '')
            selected = selected[:-6] if isinstance(selected, str) and selected.endswith(':nitro') else selected
            profile = next((item for item in model_profiles() if item['model'] == selected), None)
            if profile is not None:
                data.setdefault('model_metadata', profile['model_metadata'])
                data.setdefault('routing_providers', profile['routing_providers'])
        result = cls(**data)
        result.validate()
        data['base_url'] = _base_url(result.provider, result.base_url if result.base_url != '' else
                                     CLOUD_BASES.get(result.provider, OLLAMA_BASE))
        data['parameters'] = _parameters(result.provider, result.parameters)
        data['routing_providers'] = list(result.resolved_routing_providers())
        result = cls(**data)
        return result

    def validate(self):
        if self.provider not in ('openai', 'openrouter', 'ollama'):
            raise ProviderError('Choose OpenAI Responses, OpenRouter, or Ollama.')
        _model_name(self.provider, self.model)
        if self.provider != 'openrouter' and ':nitro' in self.model:
            raise ProviderError('Nitro is supported only by OpenRouter.')
        _base_url(self.provider, self.base_url or CLOUD_BASES.get(self.provider, OLLAMA_BASE))
        if not isinstance(self.network_enabled, bool):
            raise ProviderError('Network permission must be a boolean.')
        if not isinstance(self.zdr, bool):
            raise ProviderError('Optional zero-retention routing must be a boolean.')
        _number(self.timeout, 1, 120, 'Timeout must be between 1 and 120 seconds.')
        _number(self.max_input_bytes, 1024, MAX_INPUT_BYTES, 'Invalid input byte limit.', True)
        _number(self.max_response_bytes, 1024, MAX_RESPONSE_BYTES, 'Invalid response byte limit.', True)
        _number(self.max_output_chars, 1, MAX_RESPONSE_BYTES, 'Invalid output character limit.', True)
        _number(self.max_price_per_million, 0, 100, 'Invalid model price ceiling.')
        _parameters(self.provider, self.parameters)
        if not isinstance(self.routing_providers, (list, tuple)) or len(self.routing_providers) > 8:
            raise ProviderError('Routing providers must be a short explicit allowlist.')
        if any(not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,100}', item)
               for item in self.routing_providers):
            raise ProviderError('Invalid routing provider identifier.')
        if not isinstance(self.model_metadata, Mapping):
            raise ProviderError('Model metadata must be an object.')
        if any(key not in METADATA_FIELDS for key in self.model_metadata):
            raise ProviderError('Unsupported model metadata field; credentials cannot be persisted.')
        for name, value in self.model_metadata.items():
            if name in ('open_weights', 'terms_reviewed', 'private_route_available'):
                if not isinstance(value, bool):
                    raise ProviderError('Invalid model policy flag.')
            elif name in ('input_usd_per_million', 'output_usd_per_million'):
                _number(value, 0, 100000, 'Invalid reviewed model price.')
            elif not isinstance(value, str) or len(value) > 2048:
                raise ProviderError('Invalid model metadata text.')

    def resolved_routing_providers(self):
        """Empty routes use reviewed defaults without selecting another model."""
        if self.provider != 'openrouter' or self.routing_providers:
            return tuple(self.routing_providers)
        model = self.model[:-6] if self.model.endswith(':nitro') else self.model
        profile = next((item for item in model_profiles() if item['model'] == model), None)
        return (tuple(profile['routing_providers']) if profile is not None else
                OPENROUTER_DEFAULT_ROUTING_PROVIDERS)

    def to_dict(self):
        self.validate()
        return {
            'provider': self.provider, 'model': self.model,
            'base_url': self.base_url or CLOUD_BASES.get(self.provider, OLLAMA_BASE),
            'parameters': _parameters(self.provider, self.parameters), 'network_enabled': self.network_enabled,
            'timeout': self.timeout, 'max_input_bytes': self.max_input_bytes,
            'max_response_bytes': self.max_response_bytes, 'max_output_chars': self.max_output_chars,
            'max_price_per_million': self.max_price_per_million,
            'routing_providers': list(self.resolved_routing_providers()), 'model_metadata': dict(self.model_metadata),
        }

    def validate_purpose(self, purpose):
        """Check local eligibility before any research, credential, or API work."""
        self.validate()
        if purpose not in PURPOSES:
            raise ProviderError('Unsupported provider request purpose.')
        _knowledge_policy(self, purpose)


@dataclass(frozen=True)
class ModelCatalogConfig:
    """Nonsecret settings for an explicit catalog refresh, with no chosen model."""
    provider: str = 'ollama'
    base_url: str = ''
    network_enabled: bool = False
    timeout: float = 30
    max_response_bytes: int = MAX_CATALOG_BYTES
    max_models: int = MAX_CATALOG_MODELS

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, Mapping):
            raise ProviderError('Model catalog settings must be an object.')
        if set(values) - set(cls.__dataclass_fields__) - {'endpoint'}:
            raise ProviderError('Unsupported model catalog setting; credentials cannot be stored.')
        data = dict(values)
        if 'endpoint' in data:
            endpoint = data.pop('endpoint')
            if 'base_url' in data and data['base_url'] != endpoint:
                raise ProviderError('Conflicting provider endpoints.')
            data['base_url'] = endpoint
        if data.get('provider', 'ollama') not in ('openai', 'openrouter', 'ollama'):
            raise ProviderError('Choose OpenAI, OpenRouter, or Ollama for model refresh.')
        data.setdefault('base_url', CLOUD_BASES.get(data.get('provider', 'ollama'), OLLAMA_BASE))
        result = cls(**data)
        result.validate()
        data['base_url'] = _base_url(result.provider, result.base_url if result.base_url != '' else
                                     CLOUD_BASES.get(result.provider, OLLAMA_BASE))
        return cls(**data)

    def validate(self):
        if self.provider not in ('openai', 'openrouter', 'ollama'):
            raise ProviderError('Choose OpenAI, OpenRouter, or Ollama for model refresh.')
        _base_url(self.provider, self.base_url or CLOUD_BASES.get(self.provider, OLLAMA_BASE))
        if not isinstance(self.network_enabled, bool):
            raise ProviderError('Network permission must be a boolean.')
        _number(self.timeout, 1, 120, 'Timeout must be between 1 and 120 seconds.')
        _number(self.max_response_bytes, 1024, MAX_CATALOG_BYTES, 'Invalid model catalog byte limit.', True)
        _number(self.max_models, 1, MAX_CATALOG_MODELS, 'Invalid model catalog count limit.', True)

    def to_dict(self):
        self.validate()
        return {'provider': self.provider,
                'base_url': self.base_url or CLOUD_BASES.get(self.provider, OLLAMA_BASE),
                'network_enabled': self.network_enabled, 'timeout': self.timeout,
                'max_response_bytes': self.max_response_bytes, 'max_models': self.max_models}


@dataclass(frozen=True)
class RequestSpec:
    url: str
    method: str
    payload: Optional[Mapping[str, Any]] = field(default=None, repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    timeout: float = 30
    max_response_bytes: int = 1024 * 1024


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Mapping[str, Any]
    sources: Sequence[Mapping[str, Any]]
    provider: str
    model: str

    def to_dict(self):
        return {'text': self.text, 'usage': dict(self.usage),
                'sources': [dict(source) for source in self.sources],
                'provider': self.provider, 'model': self.model}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def request_json(spec):
    """One attempt, no redirects/proxy inheritance, bounded socket and body reads."""
    payload = None if spec.payload is None else json.dumps(spec.payload, allow_nan=False).encode('utf-8')
    request = urllib.request.Request(spec.url, data=payload, headers=dict(spec.headers), method=spec.method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=spec.timeout) as response:
            raw = response.read(spec.max_response_bytes + 1)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code in (401, 403):
            raise ProviderError('Provider authentication or access failed.') from None
        if code == 402:
            raise ProviderError('Provider credit is unavailable.') from None
        if code == 429:
            raise ProviderError('Provider rate limit reached.') from None
        if 300 <= code < 400:
            raise ProviderError('Provider redirect refused.') from None
        raise ProviderError('Provider rejected the request (HTTP ' + str(code) + ').') from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise ProviderError('Provider connection failed or timed out.') from None
    if len(raw) > spec.max_response_bytes:
        raise ProviderError('Provider response exceeds the byte limit.')
    try:
        value = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError, RecursionError):
        raise ProviderError('Provider returned invalid JSON.') from None
    if not isinstance(value, dict) or value.get('error'):
        raise ProviderError('Provider returned a failed or invalid response.')
    return value


class _StreamText:
    """Bound output and redact a credential even when split between deltas."""
    def __init__(self, callback, maximum, key):
        self.callback, self.maximum, self.key = callback, maximum, key
        self.parts, self.size, self.pending, self.safe_size = [], 0, '', 0
        self.prefix = [0] * len(key)
        matched = 0
        for index in range(1, len(key)):
            while matched and key[index] != key[matched]:
                matched = self.prefix[matched - 1]
            if key[index] == key[matched]:
                matched += 1
            self.prefix[index] = matched

    def _emit(self, text):
        if not text:
            return
        self.safe_size += len(text)
        if self.safe_size > self.maximum:
            raise ProviderError('Provider text exceeds the output character limit.')
        try:
            self.callback(text)
        except Exception:
            raise ProviderError('Provider text callback failed; no retry was made.') from None

    def add(self, text):
        if not isinstance(text, str):
            raise ProviderError('Provider returned an invalid text delta.')
        try:
            text.encode('utf-8')
        except UnicodeError:
            raise ProviderError('Provider returned invalid UTF-8 text.') from None
        self.size += len(text)
        if self.size > self.maximum:
            raise ProviderError('Provider text exceeds the output character limit.')
        if not text:
            return
        self.parts.append(text)
        if not self.key:
            self._emit(text)
            return
        safe = (self.pending + text).replace(self.key, _redaction_marker(self.key))
        keep = 0
        tail = safe[-(len(self.key) - 1):] if len(self.key) > 1 else ''
        for char in tail:
            while keep and char != self.key[keep]:
                keep = self.prefix[keep - 1]
            if char == self.key[keep]:
                keep += 1
        self.pending = safe[-keep:] if keep else ''
        self._emit(safe[:-keep] if keep else safe)

    def content(self):
        return ''.join(self.parts)

    def finish(self):
        # Never flush a possible credential prefix from an interrupted stream.
        self._emit(self.pending)
        self.pending = ''


def _stream_lines(chunks, maximum):
    """Frame bytes before UTF-8 decoding; CR, LF and split CRLF are valid."""
    pending, size, skip_lf, scanned = bytearray(), 0, False, 0
    try:
        iterator = iter(chunks)
    except Exception:
        raise ProviderError('Provider stream transport failed.') from None
    while True:
        try:
            chunk = next(iterator)
        except StopIteration:
            break
        except Exception:
            raise ProviderError('Provider stream connection failed or timed out.') from None
        if not isinstance(chunk, bytes):
            raise ProviderError('Provider returned an invalid stream chunk.')
        size += len(chunk)
        if size > maximum:
            raise ProviderError('Provider response exceeds the byte limit.')
        pending.extend(chunk)
        while pending:
            if skip_lf:
                if pending.startswith(b'\n'):
                    del pending[:1]
                skip_lf = False
            cr, lf = pending.find(b'\r', scanned), pending.find(b'\n', scanned)
            candidates = [index for index in (cr, lf) if index >= 0]
            if not candidates:
                scanned = len(pending)
                break
            end = min(candidates)
            line, skip_lf = bytes(pending[:end]), pending[end] == 13
            del pending[:end + 1]
            scanned = 0
            try:
                yield line.decode('utf-8')
            except UnicodeError:
                raise ProviderError('Provider returned invalid UTF-8 stream data.') from None
    if pending:
        try:
            yield pending.decode('utf-8')
        except UnicodeError:
            raise ProviderError('Provider returned invalid UTF-8 stream data.') from None


def _stream_records(chunks, provider, maximum):
    data, event = [], ''
    for line in _stream_lines(chunks, maximum):
        if provider == 'ollama':
            if line.strip():
                yield '', line
            continue
        if not line:
            if data:
                yield event, '\n'.join(data)
            data, event = [], ''
            continue
        if line.startswith(':'):
            continue
        name, separator, value = line.partition(':')
        if separator and value.startswith(' '):
            value = value[1:]
        if name == 'data':
            data.append(value)
        elif name == 'event':
            event = value
    if data:
        raise ProviderError('Provider stream ended in an incomplete event.')


def _stream_json(data):
    def reject_constant(unused):
        raise ValueError('Non-JSON numeric constant.')
    try:
        value = json.loads(data, parse_constant=reject_constant)
    except (ValueError, RecursionError):
        raise ProviderError('Provider returned invalid stream JSON.') from None
    if not isinstance(value, dict) or value.get('error'):
        raise ProviderError('Provider returned a failed or invalid stream response.')
    return value


class _StreamResponse:
    def __init__(self, provider, text):
        self.provider, self.text = provider, text
        self.terminal, self.done, self.response, self.usage = None, False, None, {}
        self.text_part = None

    def accept(self, event, data):
        if self.done:
            raise ProviderError('Provider sent data after the stream ended.')
        if data == '[DONE]':
            if self.provider == 'ollama' or self.terminal is None:
                raise ProviderError('Provider stream ended without a successful completion.')
            self.done = True
            return
        value = _stream_json(data)
        if event == 'error' or value.get('type') == 'error':
            raise ProviderError('Provider returned a failed stream response; no retry was made.')
        if self.provider == 'openrouter':
            self._router(value)
        elif self.provider == 'openai':
            self._openai(event, value)
        else:
            self._ollama(value)

    def _router(self, value):
        choices = value.get('choices')
        if not isinstance(choices, list) or len(choices) > 1:
            raise ProviderError('Provider returned an invalid streaming choice.')
        if not choices:
            if not isinstance(value.get('usage'), Mapping):
                raise ProviderError('Provider returned an invalid streaming accounting frame.')
        else:
            choice = choices[0]
            if not isinstance(choice, Mapping) or choice.get('index', 0) != 0:
                raise ProviderError('Provider returned an invalid streaming choice.')
            delta = choice.get('delta')
            if not isinstance(delta, Mapping):
                raise ProviderError('Provider returned an invalid text delta.')
            if delta.get('role', 'assistant') != 'assistant':
                raise ProviderError('Provider returned an invalid assistant role.')
            if delta.get('tool_calls') or delta.get('function_call') or delta.get('refusal'):
                raise ProviderError('Provider tool request or refusal cannot be treated as a completed inference.')
            reason = choice.get('finish_reason')
            if reason is not None and reason not in ('stop', 'end_turn'):
                raise ProviderError('Provider response is incomplete or requested unavailable tools.')
            if choice.get('native_finish_reason') in ('length', 'max_tokens', 'max_output_tokens',
                                                     'error', 'content_filter', 'tool_calls', 'function_call'):
                raise ProviderError('Provider response is incomplete or requested unavailable tools.')
            content = delta.get('content')
            if self.terminal is not None:
                # OpenRouter repeats the terminal choice on its final usage frame.
                if (content not in (None, '') or reason != self.terminal
                        or not isinstance(value.get('usage'), Mapping)):
                    raise ProviderError('Provider sent unexpected data after its terminal choice.')
            elif content is not None:
                self.text.add(content)
            if reason is not None:
                self.terminal = reason
        if 'usage' in value:
            if not isinstance(value['usage'], Mapping):
                raise ProviderError('Provider returned invalid streaming usage.')
            self.usage = dict(value['usage'])

    def _openai(self, event, value):
        kind = value.get('type')
        if not isinstance(kind, str) or event and event != kind:
            raise ProviderError('Provider returned an invalid Responses stream event.')
        if self.terminal is not None:
            raise ProviderError('Provider sent data after its completed response.')
        if kind in ('error', 'response.failed', 'response.incomplete', 'response.cancelled'):
            raise ProviderError('Provider response is incomplete or failed; no retry was made.')
        if kind.startswith('response.refusal.'):
            raise ProviderError('Provider declined this request.')
        if kind in ('response.output_item.added', 'response.output_item.done'):
            item = value.get('item')
            if not isinstance(item, Mapping) or item.get('type') not in ('message', 'reasoning'):
                raise ProviderError('Unexpected provider tool output was refused.')
            if item.get('type') == 'message':
                parts = item.get('content', [])
                if item.get('role', 'assistant') != 'assistant' or not isinstance(parts, list):
                    raise ProviderError('Provider returned an invalid assistant message.')
                for part in parts:
                    if not isinstance(part, Mapping) or part.get('type') not in ('output_text',):
                        raise ProviderError('Provider tool request or refusal was refused.')
        elif kind.startswith(('response.function_call', 'response.web_search', 'response.file_search',
                              'response.code_interpreter', 'response.computer_call', 'response.mcp_',
                              'response.shell_call', 'response.image_generation', 'response.custom_tool')):
            raise ProviderError('Unexpected provider tool output was refused.')
        elif kind == 'response.content_part.added' or kind == 'response.content_part.done':
            part = value.get('part')
            if not isinstance(part, Mapping) or part.get('type') != 'output_text':
                raise ProviderError('Provider tool request or refusal was refused.')
        elif kind == 'response.output_text.delta':
            index = (value.get('output_index', 0), value.get('content_index', 0))
            if any(not isinstance(part, int) or isinstance(part, bool) or part < 0 for part in index):
                raise ProviderError('Provider returned an invalid output text index.')
            if self.text_part is not None and index != self.text_part:
                if index < self.text_part:
                    raise ProviderError('Provider text parts arrived in an unsupported order.')
                self.text.add('\n')
            self.text_part = index
            self.text.add(value.get('delta'))
        elif kind == 'response.completed':
            response = value.get('response')
            final, unused = _response_text(response, 'openai')
            current = self.text.content()
            if not final.startswith(current):
                raise ProviderError('Provider completed text disagrees with its streamed text.')
            self.text.add(final[len(current):])
            self.response, self.terminal = response, 'completed'
        # Reasoning deltas, annotations and text.done snapshots are never chat text.

    def _ollama(self, value):
        if self.terminal is not None:
            raise ProviderError('Local provider sent data after its completed response.')
        message = value.get('message')
        if not isinstance(message, Mapping) or not isinstance(value.get('done'), bool):
            raise ProviderError('Local provider returned an invalid stream response.')
        if message.get('role', 'assistant') != 'assistant':
            raise ProviderError('Local provider returned an invalid assistant role.')
        if message.get('tool_calls') or message.get('function_call') or message.get('refusal'):
            raise ProviderError('Local provider requested unavailable tools or declined the request.')
        if value['done'] and value.get('done_reason', 'stop') != 'stop':
            raise ProviderError('Local provider response is incomplete.')
        self.text.add(message.get('content', ''))
        if value['done']:
            self.response, self.terminal = dict(value), 'stop'
            self.response['message'] = {'content': self.text.content()}

    def finish(self):
        if self.terminal is None or self.provider == 'openrouter' and not self.done:
            raise ProviderError('Provider stream ended without a successful completion.')
        if self.provider == 'openrouter':
            self.response = {'choices': [{'finish_reason': self.terminal,
                                        'message': {'content': self.text.content()}}], 'usage': self.usage}
        content, unused = _response_text(self.response, self.provider)
        if not content.strip():
            raise ProviderError('Provider returned no usable text.')
        self.text.finish()
        return self.response


def parse_stream(chunks, provider, on_text, *, max_response_bytes, max_output_chars, key=''):
    """Consume one bounded native stream; callbacks are provisional until return."""
    text = _StreamText(on_text, max_output_chars, key)
    stream = _StreamResponse(provider, text)
    for event, data in _stream_records(chunks, provider, max_response_bytes):
        stream.accept(event, data)
    return stream.finish()


def request_stream(spec, provider, on_text, *, max_output_chars, key=''):
    """One streaming request, no redirects, inherited proxies or retry."""
    payload = json.dumps(spec.payload, allow_nan=False).encode('utf-8')
    request = urllib.request.Request(spec.url, data=payload, headers=dict(spec.headers), method=spec.method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=spec.timeout) as response:
            def chunks():
                # read1 returns available bytes instead of waiting for a full block.
                read = getattr(response, 'read1', response.read)
                while True:
                    raw = read(min(16384, spec.max_response_bytes + 1))
                    if not raw:
                        return
                    yield raw
            return parse_stream(chunks(), provider, on_text, max_response_bytes=spec.max_response_bytes,
                                max_output_chars=max_output_chars, key=key)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code in (401, 403):
            raise ProviderError('Provider authentication or access failed.') from None
        if code == 402:
            raise ProviderError('Provider credit is unavailable.') from None
        if code == 429:
            raise ProviderError('Provider rate limit reached.') from None
        if 300 <= code < 400:
            raise ProviderError('Provider redirect refused.') from None
        raise ProviderError('Provider rejected the request (HTTP ' + str(code) + ').') from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise ProviderError('Provider connection failed or timed out.') from None


def credential_loader(credential_directory):
    """Bind the app config directory from trusted worker startup, never JSON.

    Creating this callback is inert. Resolution happens only for an explicit
    provider operation and saved keys take precedence over existing fallback.
    """
    def load(config):
        return _credential(config, credential_directory=credential_directory)
    return load


def _credential(config, *, credential_directory=None):
    if config.provider == 'ollama':
        return ''
    try:
        if __package__:
            from .credentials import load_saved_key
        else:
            # Keep standalone copied-worker fixtures independent of cwd/sys.path.
            load_saved_key = _fixed_module(Path(__file__).with_name('credentials.py')).load_saved_key
        saved = load_saved_key(config.provider, credential_directory)
    except Exception:
        raise ProviderError('Cannot read private provider authentication.') from None
    if saved is not None:
        return saved
    return _fallback_credential(config)


def _fallback_credential(config):
    if config.provider == 'openrouter':
        # Reuse the existing checked private-file reader; do not copy key data
        # into workbench settings, subprocess arguments, or logs.
        environment_key = os.environ.get('OPENROUTER_API_KEY')
        if environment_key is not None:
            return environment_key
        # The source reader is resolved from this trusted module, never cwd or
        # a chat project. Copied/installed workers use environment credentials;
        # they never search arbitrary projects for a credential module/file.
        location = Path(__file__).resolve()
        runtime_root = location.parent if (location.parent / '_openrouter_config.py').is_file() else location.parent.parent
        copied_reader = runtime_root / '_openrouter_config.py'
        reader = (copied_reader if copied_reader.is_file() else
                  location.parents[2] / 'tools' / 'openrouter.py')
        if not reader.is_file():
            return ''
        try:
            if reader == copied_reader:
                paths = _fixed_module(runtime_root / '_runtime_paths.py')
                config_path = Path(paths.OPENROUTER_CONFIG_PATH)
                if not config_path.is_absolute() or config_path.name != '.env.openrouter':
                    raise ProviderError('Invalid fixed private configuration path.')
            else:
                config_path = reader.parent.parent / '.env.openrouter'
            module = _fixed_module(reader)
            return module.load_config(path=config_path).api_key
        except Exception:
            raise ProviderError('Cannot read private OpenRouter configuration.') from None
    key = os.environ.get('OPENAI_API_KEY', '')
    return key


def _fixed_module(path):
    """Load a fixed build/source module without adding project paths to sys.path."""
    import sys
    module_spec = importlib.util.spec_from_file_location('workbench_private_' + uuid.uuid4().hex, str(path))
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    try:
        # Compiling the fixed source directly avoids implicit __pycache__ writes
        # during a read-only credential operation, including installed workers.
        with Path(path).open('rb') as source:
            code = source.read(1024 * 1024 + 1)
        if len(code) > 1024 * 1024:
            raise ProviderError('Private credential helper exceeds the size limit.')
        exec(compile(code, str(path), 'exec'), module.__dict__)
        return module
    finally:
        sys.modules.pop(module_spec.name, None)


def _knowledge_policy(config, purpose):
    if purpose not in KNOWLEDGE_PURPOSES:
        return
    base_model = config.model[:-6] if config.model.endswith(':nitro') else config.model
    publisher = config.model_metadata.get('publisher', '')
    if not isinstance(publisher, str):
        raise ProviderError('Invalid reviewed model publisher.')
    if config.provider == 'openai' or re.search(r'(^|[/._:-])(openai|gpt(?:-oss)?|o[134])([/._:-]|$)', base_model.lower()) or publisher.lower() == 'openai':
        raise ProviderError('OpenAI models cannot build or evaluate scribbles and refs.')
    metadata = config.model_metadata
    if (metadata.get('model') != base_model
            or not isinstance(publisher, str) or not publisher.strip()
            or metadata.get('terms_reviewed') is not True):
        raise ProviderError('Knowledge building requires exact reviewed non-OpenAI model metadata.')
    try:
        reviewed = date.fromisoformat(metadata.get('reviewed_at', ''))
        age = (date.today() - reviewed).days
    except (TypeError, ValueError):
        raise ProviderError('Model metadata requires a valid review date.') from None
    if age < 0:
        raise ProviderError('Model policy review date cannot be in the future.')
    terms_url = metadata.get('terms_url', '')
    if not isinstance(terms_url, str) or not terms_url.startswith('https://'):
        raise ProviderError('Model metadata requires the reviewed terms URL.')
    if config.provider == 'openrouter':
        for name in ('input_usd_per_million', 'output_usd_per_million'):
            _number(metadata.get(name), 0, config.max_price_per_million,
                    'Model pricing is unknown or exceeds the configured price ceiling.')
        routes = config.resolved_routing_providers()
        if not routes or any(item.lower().startswith('openai') for item in routes):
            raise ProviderError('Knowledge building requires explicitly reviewed non-OpenAI routing providers.')


@dataclass(frozen=True)
class ImageInput:
    """Validated immutable outbound image data; never a path or remote URL."""
    mime_type: str
    data_base64: str = field(repr=False)
    byte_size: int = field(repr=False)

    def to_dict(self):
        return {'mime_type': self.mime_type, 'data_base64': self.data_base64}


def normalize_images(values):
    """Validate a small PNG/JPEG set without decoding pixels or reading files.

    Limits apply to decoded file bytes; callers count the encoded data against
    their input bounds as well. Only the format signature is inspected. A
    provider remains responsible for accepting the image and selected model.
    """
    if not isinstance(values, (list, tuple)) or len(values) > MAX_IMAGES:
        raise ProviderError('Images must be a bounded list of at most four PNG or JPEG images.')
    result, total = [], 0
    for value in values:
        if isinstance(value, ImageInput):
            value = value.to_dict()
        if (not isinstance(value, Mapping) or set(value) != {'mime_type', 'data_base64'}
                or not isinstance(value.get('mime_type'), str)
                or value['mime_type'] not in ('image/png', 'image/jpeg')):
            raise ProviderError('Image inputs require only a PNG or JPEG MIME type and base64 data.')
        encoded = value['data_base64']
        if (not isinstance(encoded, str) or not encoded
                or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3)):
            raise ProviderError('Image data is empty, invalid or exceeds the four MiB per-image limit.')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ProviderError('Image data must be canonical ASCII base64.') from None
        if (len(raw) > MAX_IMAGE_BYTES or base64.b64encode(raw).decode('ascii') != encoded):
            raise ProviderError('Image data is invalid or exceeds the four MiB per-image limit.')
        signature = b'\x89PNG\r\n\x1a\n' if value['mime_type'] == 'image/png' else b'\xff\xd8\xff'
        if not raw.startswith(signature):
            raise ProviderError('Image data does not match its PNG or JPEG MIME type.')
        total += len(raw)
        if total > MAX_TOTAL_IMAGE_BYTES:
            raise ProviderError('Images exceed the eight MiB combined byte limit.')
        result.append(ImageInput(value['mime_type'], encoded, len(raw)))
    return tuple(result)


def _messages(values, limit, key):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 4096:
        raise ProviderError('Messages must be a nonempty bounded list.')
    result = []
    size = image_count = image_size = 0
    for message in values:
        if (not isinstance(message, Mapping) or set(message) - {'role', 'content', 'images'}
                or message.get('role') not in ('system', 'developer', 'user', 'assistant')
                or not isinstance(message.get('content'), str)):
            raise ProviderError('Conversation messages require a supported role and text content.')
        if 'images' in message and message['role'] != 'user':
            raise ProviderError('Image inputs are supported only in user messages.')
        images = normalize_images(message.get('images', ()))
        image_count += len(images)
        image_size += sum(image.byte_size for image in images)
        if image_count > MAX_IMAGES or image_size > MAX_TOTAL_IMAGE_BYTES:
            raise ProviderError('Conversation images exceed the four-image or eight MiB combined limit.')
        content = message['content']
        if key and key in content:
            raise ProviderError('A credential occurs in the submitted text; remove it before sending.')
        try:
            size += len(content.encode('utf-8')) + sum(len(image.data_base64) for image in images)
        except UnicodeError:
            raise ProviderError('Messages require valid UTF-8 text.') from None
        if size > limit:
            raise ProviderError('Conversation exceeds the input byte limit.')
        item = {'role': message['role'], 'content': content}
        if images:
            item['images'] = images
        result.append(item)
    return result


def _provider_messages(conversation, provider):
    """Translate validated images while preserving the text-only wire shape."""
    result = []
    for message in conversation:
        item = {'role': message['role'], 'content': message['content']}
        images = message.get('images', ())
        if images:
            if provider == 'ollama':
                item['images'] = [image.data_base64 for image in images]
            else:
                item['content'] = [{'type': 'input_text' if provider == 'openai' else 'text',
                                    'text': message['content']}]
                for image in images:
                    data_url = 'data:' + image.mime_type + ';base64,' + image.data_base64
                    item['content'].append(
                        {'type': 'input_image', 'image_url': data_url} if provider == 'openai' else
                        {'type': 'image_url', 'image_url': {'url': data_url}})
        result.append(item)
    return result


def _usage(value, ollama=False):
    if not isinstance(value, Mapping):
        return {}
    normalized = {}
    for name, aliases in (
            ('input_tokens', ('prompt_eval_count',) if ollama else ('input_tokens', 'prompt_tokens')),
            ('output_tokens', ('eval_count',) if ollama else ('output_tokens', 'completion_tokens')),
            ('total_tokens', ('total_tokens',))):
        for alias in aliases:
            count = value.get(alias)
            if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 2**53:
                normalized[name] = count
                break
    if 'total_tokens' not in normalized and 'input_tokens' in normalized and 'output_tokens' in normalized:
        normalized['total_tokens'] = normalized['input_tokens'] + normalized['output_tokens']
    return normalized


def _response_text(response, provider):
    """Validate successful plain text identically for buffered and streamed calls."""
    if not isinstance(response, Mapping) or response.get('error'):
        raise ProviderError('Provider returned a failed or invalid response.')
    try:
        if provider == 'openai':
            if response.get('status') != 'completed':
                raise ProviderError('Provider response is incomplete; it is not a successful inference.')
            output = response.get('output', [])
            if not isinstance(output, list):
                raise ProviderError('Provider returned an invalid text response.')
            chunks = []
            for item in output:
                if not isinstance(item, Mapping):
                    raise ProviderError('Provider returned an invalid text response.')
                if item.get('type') == 'message':
                    parts = item.get('content', [])
                    if item.get('role', 'assistant') != 'assistant' or not isinstance(parts, list):
                        raise ProviderError('Provider returned an invalid text response.')
                    for part in parts:
                        if not isinstance(part, Mapping):
                            raise ProviderError('Provider returned an invalid text response.')
                        if part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                            chunks.append(part['text'])
                        elif part.get('type') == 'refusal':
                            raise ProviderError('Provider declined this request.')
                        else:
                            raise ProviderError('Unexpected provider content was refused.')
                elif item.get('type') != 'reasoning':
                    raise ProviderError('Unexpected provider tool output was refused.')
            content = '\n'.join(chunks)
            usage = _usage(response.get('usage', {}))
        elif provider == 'openrouter':
            choice = response['choices'][0]
            if choice.get('finish_reason') not in ('stop', 'end_turn'):
                raise ProviderError('Provider response is incomplete or requested unavailable tools.')
            message = choice['message']
            if message.get('tool_calls') or message.get('function_call') or message.get('refusal'):
                raise ProviderError('Provider tool request or refusal cannot be treated as a completed inference.')
            content = message['content']
            usage = _usage(response.get('usage', {}))
        else:
            if response.get('done') is not True or response.get('done_reason', 'stop') != 'stop':
                raise ProviderError('Local provider response is incomplete.')
            message = response['message']
            if message.get('tool_calls') or message.get('function_call') or message.get('refusal'):
                raise ProviderError('Local provider requested unavailable tools or declined the request.')
            content = message['content']
            usage = _usage(response, ollama=True)
    except (KeyError, IndexError, AttributeError, TypeError):
        raise ProviderError('Provider returned an invalid text response.') from None
    if not isinstance(content, str):
        raise ProviderError('Provider returned an invalid text response.')
    return content, usage


def _sources(values, key):
    if not isinstance(values, (list, tuple)) or len(values) > 10000:
        raise ProviderError('Invalid curated source list.')
    result = []
    for source in values:
        if hasattr(source, 'to_dict'):
            source = source.to_dict()
        if not isinstance(source, Mapping):
            raise ProviderError('Invalid curated source record.')
        # Freeze records through bounded JSON; never copy arbitrary objects or
        # response-provided tool/citation records into trusted source metadata.
        try:
            raw = json.dumps(dict(source), allow_nan=False)
            if len(raw) > 65536:
                raise ProviderError('Curated source record exceeds the size limit.')
            result.append(_redact(json.loads(raw), key))
        except (TypeError, ValueError, RecursionError):
            raise ProviderError('Invalid curated source record.') from None
    return result


def _redaction_marker(key):
    marker = '[REDACTED]'
    # Preserve the familiar marker only if neither it nor either boundary can
    # recreate an accepted printable-ASCII credential. Otherwise non-ASCII
    # blocks separate both adjacent sides and cannot contain any key character.
    overlaps = any(key.endswith(marker[:size]) or key.startswith(marker[-size:])
                   for size in range(1, min(len(key), len(marker))))
    if key in marker or marker in key or overlaps:
        return '\u2588' * len(marker)
    return marker


def _redact(value, key):
    if not key:
        return value
    if isinstance(value, str):
        return value.replace(key, _redaction_marker(key))
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(name, key): _redact(item, key) for name, item in value.items()}
    return value


def _catalog_entries(provider, records, maximum, key=''):
    """Keep only inert model identifiers/labels, never descriptions or links."""
    if not isinstance(records, list) or len(records) > MAX_CATALOG_RECORDS:
        raise ProviderError('Provider model catalog exceeds its supported record limit.')
    models, seen = [], set()
    truncated = False
    for record in records:
        if not isinstance(record, Mapping):
            continue
        identifier = record.get('id')
        try:
            _model_name(provider, identifier)
        except ProviderError:
            continue
        name = record.get('name', identifier)
        if (not isinstance(name, str) or not name.strip() or len(name) > MAX_MODEL_CHARS
                or any(ord(char) < 32 or 127 <= ord(char) <= 159
                       or ord(char) in (0x202a, 0x202b, 0x202c, 0x202d, 0x202e, 0x2066, 0x2067, 0x2068, 0x2069)
                       for char in name)):
            continue
        try:
            name.encode('utf-8')
        except UnicodeError:
            continue
        if key and (key in identifier or key in name):
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        if len(models) == maximum:
            truncated = True
            continue
        models.append({'id': identifier, 'name': name, 'provider': provider})
    return models, truncated


def _catalog_response_size(response, maximum):
    try:
        # JSON permits escaped unpaired surrogates. Account for their escaped
        # bytes here, then discard such names in the inert metadata filter.
        raw = json.dumps(response, ensure_ascii=False, allow_nan=False).encode('utf-8', errors='backslashreplace')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ProviderError('Provider returned an invalid model catalog.') from None
    if len(raw) > maximum:
        raise ProviderError('Provider model catalog exceeds the byte limit.')


class ModelCatalogClient:
    """Fetch one fixed-origin catalog only after an explicit caller action.

    Public OpenRouter and local Ollama catalogs do not read a credential.
    OpenAI resolves its API key through the same private loader as completions.
    A listed model is neither a capability guarantee nor an approved route.
    """
    def __init__(self, config, transport=None, credential_loader=None):
        self.config = config if isinstance(config, ModelCatalogConfig) else ModelCatalogConfig.from_dict(config)
        self.transport = transport
        self.credential_loader = credential_loader

    def list_models(self):
        config = self.config
        config.validate()
        if self.transport is None and not config.network_enabled:
            raise ProviderError('Model refresh requires an explicit network invocation.')
        key = ''
        if config.provider == 'openai':
            try:
                key = (self.credential_loader(config) if self.credential_loader is not None else
                       _credential(config) if self.transport is None else '')
            except Exception:
                raise ProviderError('Cannot read the private provider credential.') from None
            if not isinstance(key, str) or key and not re.fullmatch(r'[!-~]{1,8192}', key):
                raise ProviderError('Invalid private provider credential.')
            if self.transport is None and not key:
                raise ProviderError('Provider API key is missing from private configuration.')
            if key and key in json.dumps(config.to_dict(), allow_nan=False):
                raise ProviderError('A credential occurs in provider settings; remove it before sending.')
        base = _base_url(config.provider, config.base_url or CLOUD_BASES.get(config.provider, OLLAMA_BASE))
        headers = {'Accept': 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        endpoint = '/api/tags' if config.provider == 'ollama' else '/models'
        spec = RequestSpec(base + endpoint, 'GET', None, headers, config.timeout, config.max_response_bytes)
        try:
            response = (self.transport or request_json)(spec)
        except ProviderError:
            if self.transport is None:
                raise
            raise ProviderError('Provider model catalog transport failed.') from None
        except Exception:
            raise ProviderError('Provider model catalog transport failed.') from None
        if not isinstance(response, Mapping) or response.get('error'):
            raise ProviderError('Provider returned a failed or invalid model catalog.')
        _catalog_response_size(response, config.max_response_bytes)
        records = response.get('models' if config.provider == 'ollama' else 'data')
        if not isinstance(records, list) or len(records) > MAX_CATALOG_RECORDS:
            raise ProviderError('Provider model catalog exceeds its supported record limit.')
        if config.provider == 'ollama' and isinstance(records, list):
            # Preserve only the tag identity and display name; digest/details
            # and all other provider content have no role in model selection.
            records = [{'id': record.get('model', record.get('name')), 'name': record.get('name')}
                       if isinstance(record, Mapping) else None for record in records]
        models, truncated = _catalog_entries(config.provider, records, config.max_models, key)
        return {'models': models, 'models_truncated': truncated}


class ProviderClient:
    def __init__(self, config, transport=None, credential_loader=None):
        self.config = config if isinstance(config, ProviderConfig) else ProviderConfig.from_dict(config)
        self.transport = transport
        self.credential_loader = credential_loader
        self._verified_routes = None

    def verify_model(self):
        """Refresh only exact OpenRouter endpoint metadata within a manual call.

        Descriptions/provider messages are discarded. Router-side no-training
        and max-price filters still constrain the actual inference.
        No replacement model/provider is selected when the reviewed route fails.
        """
        config = self.config
        config.validate()
        if config.provider != 'openrouter':
            raise ProviderError('Endpoint catalog verification is available only for OpenRouter.')
        if self.transport is None and not config.network_enabled:
            raise ProviderError('Model verification requires an explicit network invocation.')
        routes = config.resolved_routing_providers()
        if not routes:
            raise ProviderError('Choose explicitly reviewed routing providers before model verification.')
        model = config.model[:-6] if config.model.endswith(':nitro') else config.model
        url = CLOUD_BASES['openrouter'] + '/models/' + model + '/endpoints'
        spec = RequestSpec(url, 'GET', None, {'Accept': 'application/json'}, config.timeout, config.max_response_bytes)
        try:
            response = (self.transport or request_json)(spec)
        except ProviderError:
            if self.transport is None:
                raise
            raise ProviderError('Provider metadata transport failed.') from None
        except Exception:
            raise ProviderError('Provider metadata transport failed.') from None
        try:
            data = response['data']
            endpoints = data['endpoints']
            if data['id'] != model or not isinstance(endpoints, list) or len(endpoints) > 1000:
                raise ProviderError('OpenRouter endpoint metadata does not match the requested model.')
            matched = []
            for endpoint in endpoints:
                if not isinstance(endpoint, Mapping):
                    raise ProviderError('Invalid OpenRouter endpoint record.')
                tag = endpoint.get('tag', '')
                if tag not in routes:
                    continue
                if endpoint.get('model_id') != model or endpoint.get('status') != 0:
                    continue
                pricing = endpoint['pricing']
                prompt, output = float(pricing['prompt']) * 1000000, float(pricing['completion']) * 1000000
                _number(prompt, 0, config.max_price_per_million, 'Reviewed route input pricing exceeds the configured ceiling.')
                _number(output, 0, config.max_price_per_million, 'Reviewed route output pricing exceeds the configured ceiling.')
                request_price = float(pricing.get('request', 0))
                if not math.isfinite(request_price) or request_price != 0:
                    raise ProviderError('Reviewed route has an unsupported per-request charge.')
                matched.append({'provider': tag, 'input_usd_per_million': prompt,
                                'output_usd_per_million': output})
            if not matched:
                raise ProviderError('The exact reviewed provider route is unavailable; no fallback was attempted.')
        except ProviderError:
            raise
        except Exception:
            raise ProviderError('Cannot verify the exact OpenRouter model endpoint metadata.') from None
        self._verified_routes = (model, tuple(routes), config.max_price_per_million)
        return {'model': model, 'routes': matched}

    def complete(self, messages, *, purpose='chat', sources=(), max_output_tokens=None, on_text=None):
        """Complete once; optional text deltas remain provisional until success.

        Native transports stream when ``on_text`` is provided. Injected mapping
        transports remain compatible; a transport's optional ``stream(spec)``
        method supplies an iterable of bytes for offline native-stream fixtures.
        """
        config = self.config
        config.validate_purpose(purpose)
        if on_text is not None and not callable(on_text):
            raise ProviderError('Provider text callback must be callable.')
        if self.transport is None and not config.network_enabled:
            raise ProviderError('Provider network access is disabled; explicitly enable it for this invocation.')
        try:
            key = ('' if config.provider == 'ollama' else
                   self.credential_loader(config) if self.credential_loader is not None else
                   _credential(config) if self.transport is None else '')
        except Exception:
            raise ProviderError('Cannot read the private provider credential.') from None
        if not isinstance(key, str) or key and not re.fullmatch(r'[!-~]{1,8192}', key):
            raise ProviderError('Invalid private provider credential.')
        if config.provider != 'ollama' and self.transport is None and not key:
            raise ProviderError('Provider API key is missing from private configuration.')
        if key and key in json.dumps(config.to_dict(), allow_nan=False):
            raise ProviderError('A credential occurs in provider settings; remove it before sending.')
        records = _sources(sources, key)
        conversation = _provider_messages(_messages(messages, config.max_input_bytes, key), config.provider)
        settings = _parameters(config.provider, config.parameters)
        tokens = settings.get('max_tokens', settings.get('num_predict'))
        if max_output_tokens is not None:
            _number(max_output_tokens, 16 if config.provider == 'openai' else 1, 65536,
                    'Remaining output token budget is invalid or below the provider minimum.', True)
            tokens = max_output_tokens if tokens is None else min(tokens, max_output_tokens)
        model = config.model
        base = _base_url(config.provider, config.base_url or CLOUD_BASES.get(config.provider, OLLAMA_BASE))
        streaming = on_text is not None
        headers = {'Accept': ('application/x-ndjson' if config.provider == 'ollama' else 'text/event-stream')
                   if streaming else 'application/json', 'Content-Type': 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        if config.provider == 'openai':
            payload = {'model': model, 'input': conversation,
                       'store': False, 'stream': streaming, 'tools': []}
            if tokens is not None:
                payload['max_output_tokens'] = tokens
            for name in ('temperature', 'top_p', 'service_tier'):
                if name in settings:
                    payload[name] = settings[name]
            if 'reasoning_effort' in settings:
                payload['reasoning'] = {'effort': settings['reasoning_effort']}
            endpoint = '/responses'
        elif config.provider == 'openrouter':
            if settings.get('nitro') and not model.endswith(':nitro'):
                model += ':nitro'
            routing = {'data_collection': 'deny', 'allow_fallbacks': False,
                       'require_parameters': True, 'max_price': {
                           'prompt': config.max_price_per_million,
                           'completion': config.max_price_per_million, 'request': 0},
                       'sort': 'throughput' if settings.get('nitro') else 'price'}
            routes = config.resolved_routing_providers()
            routing.update({'only': list(routes), 'order': list(routes)})
            payload = {'model': model, 'messages': conversation,
                       'stream': streaming, 'provider': routing}
            if tokens is not None:
                payload['max_tokens'] = tokens
            for name in ('temperature', 'top_p', 'service_tier'):
                if name in settings:
                    payload[name] = settings[name]
            if 'reasoning_effort' in settings:
                payload['reasoning'] = {'effort': settings['reasoning_effort']}
            endpoint = '/chat/completions'
        else:
            options = {name: settings[name] for name in ('num_keep', 'num_ctx', 'temperature', 'top_p') if name in settings}
            if tokens is not None:
                options['num_predict'] = tokens
            payload = {'model': model, 'messages': conversation, 'stream': streaming, 'options': options}
            for name in ('keep_alive', 'think'):
                if name in settings:
                    payload[name] = settings[name]
            endpoint = '/api/chat'
        spec = RequestSpec(base + endpoint, 'POST', payload, headers, config.timeout, config.max_response_bytes)
        if config.provider == 'openrouter' and purpose in KNOWLEDGE_PURPOSES and self.transport is None:
            identity = (config.model[:-6] if config.model.endswith(':nitro') else config.model,
                        tuple(config.resolved_routing_providers()), config.max_price_per_million)
            if self._verified_routes != identity:
                self.verify_model()
        native_stream = streaming and (self.transport is None or callable(getattr(self.transport, 'stream', None)))
        if native_stream and self.transport is None:
            response = request_stream(spec, config.provider, on_text,
                                      max_output_chars=config.max_output_chars, key=key)
        elif native_stream:
            try:
                chunks = self.transport.stream(spec)
            except Exception:
                raise ProviderError('Provider stream transport failed.') from None
            response = parse_stream(chunks, config.provider, on_text, max_response_bytes=config.max_response_bytes,
                                    max_output_chars=config.max_output_chars, key=key)
        else:
            try:
                response = (self.transport or request_json)(spec)
            except ProviderError:
                if self.transport is None:
                    raise
                raise ProviderError('Provider transport failed.') from None
            except Exception:
                raise ProviderError('Provider transport failed.') from None
        content, usage = _response_text(response, config.provider)
        if not content.strip():
            raise ProviderError('Provider returned no usable text.')
        if len(content) > config.max_output_chars:
            raise ProviderError('Provider text exceeds the output character limit.')
        try:
            content.encode('utf-8')
        except UnicodeError:
            raise ProviderError('Provider returned invalid UTF-8 text.') from None
        if key:
            content = content.replace(key, _redaction_marker(key))
        if len(content) > config.max_output_chars:
            raise ProviderError('Provider text exceeds the output character limit.')
        if streaming and not native_stream:
            try:
                on_text(content)
            except Exception:
                raise ProviderError('Provider text callback failed; no retry was made.') from None
        return Completion(content, usage, records, config.provider, model)


def complete(messages, config, *, purpose='chat', sources=(), max_output_tokens=None, on_text=None,
             transport=None, credential_loader=None):
    return ProviderClient(config, transport, credential_loader).complete(
        messages, purpose=purpose, sources=sources, max_output_tokens=max_output_tokens, on_text=on_text)
