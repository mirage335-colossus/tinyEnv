"""Explicit OpenRouter prompt-injection guardrail management (stdlib, Python 3.9+).

This module manages one already-existing guardrail. It never creates a guardrail,
assigns one to an API key, changes account settings, or alters completion payloads.
Only ``OPENROUTER_MANAGEMENT_KEY`` supplies the production credential; ordinary
provider keys and private provider files have no role here. Imports are inert.

The OpenRouter API replaces the entire ``content_filter_builtins`` collection.
An update therefore re-reads and fingerprints the whole collection before
preserving unrelated entries. The service has no atomic compare-and-set: another
writer can still change it between that GET and PATCH. Failed/uncertain updates
are never retried automatically; callers must reload before another decision.
"""

import hashlib
import hmac
import json
import math
import os
import re

from .providers import ProviderError, RequestSpec, request_json


BASE_URL = 'https://openrouter.ai/api/v1/guardrails/'
PROMPT_INJECTION_SLUG = 'regex-prompt-injection'
MAX_GUARDRAIL_ID_CHARS = 128
MAX_RESPONSE_BYTES = 512 * 1024
MAX_REQUEST_BYTES = 128 * 1024
MAX_BUILTIN_FILTERS = 256
MAX_FILTER_SLUG_CHARS = 128
MAX_JSON_DEPTH = 24
MAX_JSON_NODES = 65536
FILTER_ACTIONS = frozenset(('block', 'flag', 'redact'))


class GuardrailError(ProviderError):
    """A locally generated diagnostic, without credentials or provider bodies."""


def validate_guardrail_id(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= MAX_GUARDRAIL_ID_CHARS
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value)):
        raise GuardrailError('Choose an existing, bounded OpenRouter guardrail ID.')
    return value


def _json_bytes(value, maximum, message):
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
            raise GuardrailError(message)
        if isinstance(item, dict):
            if nodes + len(pending) + len(item) > MAX_JSON_NODES:
                raise GuardrailError(message)
            if not all(isinstance(key, str) for key in item):
                raise GuardrailError(message)
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if nodes + len(pending) + len(item) > MAX_JSON_NODES:
                raise GuardrailError(message)
            pending.extend((child, depth + 1) for child in item)
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise GuardrailError(message) from None
    if len(raw) > maximum:
        raise GuardrailError(message)
    return raw


def _management_credential():
    # Deliberately do not call providers._credential or read a configuration file.
    return os.environ.get('OPENROUTER_MANAGEMENT_KEY', '')


def _update_size(payload):
    # Match providers.request_json exactly: default ASCII escaping and spaces
    # can make the wire body much larger than canonical compact UTF-8 JSON.
    try:
        raw = json.dumps(payload, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise GuardrailError('OpenRouter guardrail update is invalid.') from None
    if len(raw) > MAX_REQUEST_BYTES:
        raise GuardrailError('OpenRouter guardrail update exceeds its byte limit.')


def _filter_records(filters):
    # The response may order independent built-ins differently. Compare full
    # records with multiplicity, so no unknown field or duplicate is lost.
    return sorted(_json_bytes(entry, MAX_RESPONSE_BYTES,
                              'OpenRouter guardrail update response is invalid.')
                  for entry in filters or ())


def _document(response, guardrail_id, key):
    if not isinstance(response, dict) or response.get('error'):
        raise GuardrailError('OpenRouter returned an invalid guardrail response.')
    raw = _json_bytes(response, MAX_RESPONSE_BYTES,
                      'OpenRouter guardrail response is invalid or exceeds its byte limit.')
    if json.dumps(key, ensure_ascii=False)[1:-1].encode('utf-8') in raw:
        raise GuardrailError('OpenRouter guardrail response contains a private credential.')
    # Detach the validated JSON before making any update or returning its digest.
    try:
        data = json.loads(raw.decode('utf-8')).get('data')
    except (ValueError, RecursionError):
        raise GuardrailError('OpenRouter returned an invalid guardrail response.') from None
    if not isinstance(data, dict) or data.get('id') != guardrail_id:
        raise GuardrailError('OpenRouter guardrail response does not match the requested ID.')
    if 'content_filter_builtins' not in data:
        raise GuardrailError('OpenRouter guardrail response omits the built-in filter collection.')
    filters = data['content_filter_builtins']
    if filters is None:
        return None
    if not isinstance(filters, list) or len(filters) > MAX_BUILTIN_FILTERS:
        raise GuardrailError('OpenRouter built-in filter collection is invalid or exceeds its count limit.')
    injection_count = 0
    for entry in filters:
        if not isinstance(entry, dict):
            raise GuardrailError('OpenRouter returned an invalid built-in filter entry.')
        slug = entry.get('slug')
        action = entry.get('action')
        if (not isinstance(slug, str) or not 1 <= len(slug) <= MAX_FILTER_SLUG_CHARS
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', slug)
                or not isinstance(action, str) or action not in FILTER_ACTIONS):
            raise GuardrailError('OpenRouter returned an invalid built-in filter entry.')
        if slug == PROMPT_INJECTION_SLUG:
            injection_count += 1
    if injection_count > 1:
        raise GuardrailError('OpenRouter returned ambiguous prompt-injection filters.')
    return filters


def _status(guardrail_id, filters):
    action = next((entry['action'] for entry in filters or ()
                   if entry['slug'] == PROMPT_INJECTION_SLUG), '')
    canonical = _json_bytes({'id': guardrail_id, 'content_filter_builtins': filters},
                            MAX_RESPONSE_BYTES,
                            'OpenRouter guardrail state cannot be fingerprinted.')
    return {'id': guardrail_id, 'enabled': bool(action), 'action': action,
            'fingerprint': hashlib.sha256(canonical).hexdigest()}


class GuardrailClient:
    """Read/update one fixed-origin resource after an explicit caller operation.

    A fake ``transport(spec)`` and ``credential_loader()`` allow offline tests.
    Returned status is inert and contains only ID, filter presence/action and a
    fingerprint. Enabling always selects ``block``; disabling removes only the
    prompt-injection filter. Existing ``flag``/``redact`` actions are reported
    honestly by ``get`` rather than being silently presented as blocking.
    """

    def __init__(self, network_enabled=False, timeout=30, transport=None, credential_loader=None):
        if not isinstance(network_enabled, bool):
            raise GuardrailError('Guardrail network permission must be explicit.')
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 1 <= timeout <= 120):
            raise GuardrailError('Guardrail timeout must be between 1 and 120 seconds.')
        if transport is not None and not callable(transport):
            raise GuardrailError('Invalid guardrail transport.')
        if credential_loader is not None and not callable(credential_loader):
            raise GuardrailError('Invalid private guardrail credential loader.')
        self.network_enabled = network_enabled
        self.timeout = timeout
        self.transport = transport
        self.credential_loader = credential_loader

    def _begin(self, guardrail_id):
        guardrail_id = validate_guardrail_id(guardrail_id)
        if self.transport is None and not self.network_enabled:
            raise GuardrailError('Guardrail management requires an explicit network invocation.')
        try:
            key = (self.credential_loader() if self.credential_loader is not None
                   else _management_credential())
        except Exception:
            raise GuardrailError('Cannot read the private OpenRouter management credential.') from None
        if not isinstance(key, str) or not re.fullmatch(r'[!-~]{1,8192}', key):
            raise GuardrailError('A valid OPENROUTER_MANAGEMENT_KEY is required for guardrail management.')
        if key in guardrail_id:
            raise GuardrailError('A private credential occurs in the guardrail ID.')
        return guardrail_id, key

    def _request(self, guardrail_id, key, method, payload=None):
        # These are the only methods and URL this client can construct.
        if method not in ('GET', 'PATCH'):
            raise GuardrailError('Unsupported guardrail management operation.')
        headers = {'Accept': 'application/json', 'Authorization': 'Bearer ' + key}
        if payload is not None:
            _update_size(payload)
            headers['Content-Type'] = 'application/json'
        spec = RequestSpec(BASE_URL + guardrail_id, method, payload, headers,
                           self.timeout, MAX_RESPONSE_BYTES)
        try:
            response = (self.transport if self.transport is not None else request_json)(spec)
        except Exception:
            if method == 'PATCH':
                raise GuardrailError('OpenRouter guardrail update failed; reload its remote state before retrying.') from None
            raise GuardrailError('OpenRouter guardrail read failed.') from None
        return _document(response, guardrail_id, key)

    def get(self, guardrail_id):
        guardrail_id, key = self._begin(guardrail_id)
        return _status(guardrail_id, self._request(guardrail_id, key, 'GET'))

    def set(self, guardrail_id, enabled, expected_fingerprint):
        """Re-read and reject stale state, then replace only the built-in list.

        The fingerprint is an optimistic local check, not an atomic server lock.
        No PATCH is sent for invalid/stale input or an already-satisfied request.
        """
        validate_guardrail_id(guardrail_id)
        if not isinstance(enabled, bool):
            raise GuardrailError('Prompt-injection filter selection must be a boolean.')
        if (not isinstance(expected_fingerprint, str)
                or not re.fullmatch(r'[0-9a-f]{64}', expected_fingerprint)):
            raise GuardrailError('Reload the guardrail before updating; its fingerprint is missing or invalid.')
        guardrail_id, key = self._begin(guardrail_id)
        current = self._request(guardrail_id, key, 'GET')
        status = _status(guardrail_id, current)
        if not hmac.compare_digest(status['fingerprint'], expected_fingerprint):
            raise GuardrailError('OpenRouter guardrail changed; reload before updating.')
        desired_action = 'block' if enabled else ''
        if status['action'] == desired_action:
            return status
        replacement = []
        for entry in current or ():
            if entry['slug'] == PROMPT_INJECTION_SLUG:
                if enabled:
                    # Preserve all unknown fields even on the modified entry.
                    replacement.append(dict(entry, action='block'))
            else:
                replacement.append(entry)
        if enabled and not status['enabled']:
            if len(replacement) == MAX_BUILTIN_FILTERS:
                raise GuardrailError('OpenRouter built-in filter count limit prevents adding prompt-injection blocking.')
            replacement.append({'slug': PROMPT_INJECTION_SLUG, 'action': 'block'})
        filters = self._request(guardrail_id, key, 'PATCH', {'content_filter_builtins': replacement})
        result = _status(guardrail_id, filters)
        if result['action'] != desired_action:
            raise GuardrailError('OpenRouter did not confirm the requested prompt-injection filter; reload its remote state.')
        if _filter_records(filters) != _filter_records(replacement):
            raise GuardrailError('OpenRouter guardrail update response differs from the requested filters; reload its remote state.')
        return result
