#!/usr/bin/env python3
"""Optional local OpenRouter client; Python 3.9+, standard library only.

Credentials come from the process environment or the repository's ignored
.env.openrouter file. Configuration is literal data, never shell input.
"""

import argparse
from dataclasses import dataclass, field
import http.client
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import urllib.error
import urllib.request


CONFIG_PATH = Path(__file__).resolve().parent.parent / '.env.openrouter'
API_BASE = 'https://openrouter.ai/api/v1'
CONFIG_KEYS = ('OPENROUTER_API_KEY', 'OPENROUTER_MODEL')
CONFIG_TEMPLATE = (
    '# Local OpenRouter configuration. Keep this file out of Git.\n'
    'OPENROUTER_API_KEY=\n'
    'OPENROUTER_MODEL=\n'
)
MAX_CONFIG_BYTES = 65536
MAX_PROMPT_CHARS = 65536
MAX_RESPONSE_BYTES = 1024 * 1024


class OpenRouterError(RuntimeError):
    """A diagnostic safe to display without credential or provider data."""


@dataclass(frozen=True)
class Config:
    api_key: str = field(default='', repr=False)
    model: str = field(default='', repr=False)


def parse_config(text):
    """Parse only literal KEY=value entries, with optional matching quotes.

    Quotes are removed, but escapes, variables, and commands are never expanded.
    Comments must occupy their own line; inline '#' characters remain literal.
    """
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if not separator or name not in CONFIG_KEYS or name in values:
            raise OpenRouterError('Invalid local configuration entry.')
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise OpenRouterError('Invalid local configuration quoting.')
            value = value[1:-1]
        values[name] = value
    return values


def _read_config(path):
    """Read one bounded regular file; refuse unsafe POSIX credential storage."""
    try:
        if path.is_symlink():
            raise OpenRouterError('Local configuration must not be a symbolic link.')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        if os.name == 'posix':
            # O_NONBLOCK prevents a substituted FIFO from blocking before fstat.
            flags |= getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return {}
    except OSError:
        raise OpenRouterError('Cannot open local configuration securely.') from None
    try:
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise OpenRouterError('Local configuration must be a regular file.')
            if os.name == 'posix' and info.st_mode & 0o077:
                raise OpenRouterError('Local configuration requires owner-only permissions; use chmod 600 .env.openrouter.')
            raw = source.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            raise OpenRouterError('Local configuration is too large.')
        return parse_config(raw.decode('utf-8'))
    except (OSError, UnicodeError):
        raise OpenRouterError('Cannot read local configuration.') from None


def load_config(path=None, environ=None):
    """Load the repository-local file, then apply individual environment overrides."""
    values = _read_config(Path(path) if path is not None else CONFIG_PATH)
    environment = os.environ if environ is None else environ
    for name in CONFIG_KEYS:
        if name in environment:
            values[name] = environment[name]
    api_key = values.get('OPENROUTER_API_KEY', '')
    model = values.get('OPENROUTER_MODEL', '')
    if api_key and not re.fullmatch(r'[!-~]+', api_key):
        raise OpenRouterError('API key contains unsupported characters.')
    return Config(api_key=api_key, model=model)


def init_config(path=None):
    """Create empty owner-only placeholders exclusively; never replace a file."""
    if os.name != 'posix':
        raise OpenRouterError('Owner-only initialization requires POSIX; use OPENROUTER_API_KEY in the environment on this host.')
    destination = Path(path) if path is not None else CONFIG_PATH
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise OpenRouterError('Local configuration already exists; left unchanged.') from None
    except OSError:
        raise OpenRouterError('Cannot create local configuration.') from None
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
            output.write(CONFIG_TEMPLATE)
    except (OSError, UnicodeError):
        raise OpenRouterError('Cannot finish local configuration; inspect the local file.') from None
    return destination


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Prevent the Authorization header from following provider redirects."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _require_key(config):
    if not config.api_key:
        raise OpenRouterError('API key is missing; edit .env.openrouter or set OPENROUTER_API_KEY.')


def request_json(config, method, path, payload=None, timeout=30):
    """Call only the fixed HTTPS API; provider/error bodies never become diagnostics."""
    _require_key(config)
    if (method, path) not in (('GET', '/key'), ('POST', '/chat/completions')):
        raise OpenRouterError('Unsupported OpenRouter operation.')
    if not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 1 <= timeout <= 120:
        raise OpenRouterError('Timeout must be between 1 and 120 seconds.')
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    headers = {'Authorization': 'Bearer ' + config.api_key, 'Accept': 'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(API_BASE + path, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code in (401, 403):
            raise OpenRouterError('OpenRouter authentication failed; check the local API key.') from None
        if code == 402:
            raise OpenRouterError('OpenRouter rejected the request because credit is unavailable.') from None
        if code == 429:
            raise OpenRouterError('OpenRouter rate limit reached; try again later.') from None
        if 300 <= code < 400:
            raise OpenRouterError('OpenRouter redirect refused.') from None
        raise OpenRouterError('OpenRouter rejected the request.') from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise OpenRouterError('OpenRouter connection failed or timed out.') from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise OpenRouterError('OpenRouter response is too large.')
    try:
        result = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError, RecursionError):
        raise OpenRouterError('OpenRouter returned an invalid response.') from None
    if not isinstance(result, dict):
        raise OpenRouterError('OpenRouter returned an invalid response.')
    if 'error' in result:
        raise OpenRouterError('OpenRouter reported a request failure.')
    return result


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default diagnostic repeats supplied values, which could
        # contain a credential accidentally pasted as a command-line argument.
        self.print_usage(sys.stderr)
        self.exit(2, 'openrouter.py: invalid command arguments; use --help.\n')


def _timeout(value):
    try:
        number = float(value)
        if math.isfinite(number) and 1 <= number <= 120:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('Invalid timeout.')


def _max_tokens(value):
    try:
        number = int(value)
        if 1 <= number <= 65536:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('Invalid token limit.')


def _parser():
    parser = _ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='create empty, owner-only local configuration')
    commands.add_parser('status', help='check configuration offline without showing values')
    check = commands.add_parser('check', help='check authentication online without generating text')
    chat = commands.add_parser('chat', help='send a prompt from stdin; incurs model usage')
    for command in (check, chat):
        command.add_argument('--timeout', type=_timeout, default=30, help='request timeout in seconds (1–120; default 30)')
    chat.add_argument('--model', help='canonical provider/model slug; overrides OPENROUTER_MODEL')
    chat.add_argument('--max-tokens', type=_max_tokens, default=256, help='maximum output tokens (1–65536; default 256)')
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == 'init':
            init_config()
            print('Created .env.openrouter with empty placeholders (owner access only).')
            return 0
        config = load_config()
        if args.command == 'status':
            print('API key: ' + ('configured' if config.api_key else 'missing'))
            print('Model: ' + ('configured' if config.model else 'missing'))
            return 0 if config.api_key else 1
        _require_key(config)
        if args.command == 'check':
            result = request_json(config, 'GET', '/key', timeout=args.timeout)
            if not isinstance(result.get('data'), dict):
                raise OpenRouterError('OpenRouter returned an invalid authentication response.')
            print('OpenRouter authentication succeeded.')
            return 0
        model = args.model if args.model is not None else config.model
        if not model:
            raise OpenRouterError('Model is missing; set OPENROUTER_MODEL or use --model.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:/-]*', model):
            raise OpenRouterError('Model must be a canonical provider/model slug.')
        prompt = sys.stdin.read(MAX_PROMPT_CHARS + 1)
        if not prompt.strip():
            raise OpenRouterError('Prompt is empty; provide text on stdin.')
        if len(prompt) > MAX_PROMPT_CHARS:
            raise OpenRouterError('Prompt is too large.')
        result = request_json(config, 'POST', '/chat/completions', {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': args.max_tokens,
        }, timeout=args.timeout)
        try:
            content = result['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            raise OpenRouterError('OpenRouter returned an invalid chat response.') from None
        if not isinstance(content, str):
            raise OpenRouterError('OpenRouter returned an invalid chat response.')
        print(content.replace(config.api_key, '[REDACTED]'))
        return 0
    except OpenRouterError as error:
        print('openrouter.py: ' + str(error), file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print('openrouter.py: local input or output failed.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('openrouter.py: interrupted.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
