#!/usr/bin/env python3
"""Plan-first immutable GitHub delivery; remote mutation requires explicit execution.

Callers serialize publication and retain one reviewed input snapshot throughout
an operation. A failed mutation has an unknown remote outcome: reconcile exact
IDs and bytes before a new attempt. New verified base groups retire superseded
groups in the same SDK slot; application assets are never deleted or replaced.
"""
import argparse
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from email.utils import parsedate_to_datetime
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.dont_write_bytecode = True
TOOLS = str(Path(__file__).resolve().parent)
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import dependency_archive as archive
import dependency_store as store
import rust_sdk
import release
import certify_release as certification
coverage = certification.coverage

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,180}\Z')
OID = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
BASE_CLEANUP_GROUP_LIMIT = 64
# Dynamic adapters may load this file under several module names. Share one
# process-wide gate so nested four-worker pools still run at most four CLI
# requests at once; backoff and local hashing do not hold a request slot.
REQUEST_SLOTS = sys.__dict__.setdefault('_foundation_github_request_slots', threading.BoundedSemaphore(4))

class RequestMetrics:
    """Process totals only: no endpoints, credentials or response bodies retained."""
    def __init__(self):
        self.lock = threading.Lock()
        self.values = dict(cli_calls=0, api_responses=0, quota_probes=0,
                           cli_seconds=0., capacity_wait_seconds=0., retry_wait_seconds=0.,
                           downloaded_bytes=0, uploaded_bytes=0, public_downloads=0, public_download_seconds=0.)
        self.quota = None

    def add(self, **values):
        with self.lock:
            for key, value in values.items(): self.values[key] += value

    def observe(self, headers, *, quota_probe=False):
        with self.lock:
            self.values['quota_probes' if quota_probe else 'api_responses'] += 1
            numbers = {key: rate_integer(headers.get('x-ratelimit-' + key))
                       for key in ('limit', 'remaining', 'reset')}
            if (all(value is not None for value in numbers.values()) and
                    0 <= numbers['remaining'] <= numbers['limit']):
                # Responses can arrive out of order. Keep the lowest observed
                # allowance within the newest observed reset window.
                if (self.quota is None or numbers['reset'] > self.quota['reset'] or
                        numbers['reset'] == self.quota['reset'] and
                        numbers['remaining'] < self.quota['remaining']):
                    self.quota = numbers

    def snapshot(self):
        with self.lock:
            return dict(schema_version=1, **{k: round(v, 3) if isinstance(v, float) else v
                        for k, v in self.values.items()}, observed_quota=self.quota.copy() if self.quota else None)


REQUEST_METRICS = sys.__dict__.setdefault('_foundation_github_request_metrics', RequestMetrics())


def enable_metrics():
    """Opt-in sanitized per-process CI accounting, with no additional API calls."""
    if sys.__dict__.get('_foundation_github_metrics_reporter'): return
    sys.__dict__['_foundation_github_metrics_reporter'] = True
    def report():
        value = REQUEST_METRICS.snapshot()
        if value['cli_calls'] or value['public_downloads']:
            print('GitHub transport metrics: ' + json.dumps(value, sort_keys=True), file=sys.stderr, flush=True)
    atexit.register(report)


CERT = re.compile(r'certification-([A-Za-z0-9][A-Za-z0-9_.-]*)-attempt-([1-9][0-9]*)\.(json|tar.gz)\Z')


class DeliveryError(ValueError):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def valid_name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value) or value.endswith('.') or '..' in value:
        raise DeliveryError('expected one safe nonempty asset or tag name')
    stem = value.split('.', 1)[0].upper()
    if stem in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(?:COM|LPT)[1-9]', stem):
        raise DeliveryError('asset or tag name is reserved on a supported platform')
    return value


def location(repository, tag=None):
    if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', repository):
        raise DeliveryError('repository must be OWNER/REPO')
    for part in repository.split('/'):
        valid_name(part)
    if tag is not None:
        valid_name(tag)
    return repository


def sha(value):
    return hashlib.sha256(value).hexdigest()


def parse(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    if len(raw) > 16 * 1024 * 1024:
        raise DeliveryError('remote JSON exceeds supported inventory limit')
    return json.loads(raw, object_pairs_hook=coverage.object_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(DeliveryError('nonfinite remote JSON')))


def positive(value):
    return type(value) is int and value > 0


HTTP_HEADER_LIMIT = 64 * 1024
HTTP_JSON_LIMIT = 16 * 1024 * 1024
RATE_HEADERS = {'retry-after', 'x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset', 'x-ratelimit-resource'}


def response_head(stream, *, pagination=False):
    """Read one bounded gh --include header; never normalize binary body bytes."""
    lines, size = [], 0
    while True:
        line = stream.readline(HTTP_HEADER_LIMIT + 1 - size)
        size += len(line)
        if not line or size > HTTP_HEADER_LIMIT:
            raise DeliveryError('missing or oversized GitHub response headers')
        if line in (b'\n', b'\r\n'):
            break
        lines.append(line.rstrip(b'\r\n'))
    status = re.fullmatch(rb'HTTP/\S+ ([0-9]{3})(?: [^\r\n]*)?', lines[0] if lines else b'')
    if not status:
        raise DeliveryError('invalid GitHub HTTP status')
    headers = {}
    for line in lines[1:]:
        key, separator, value = line.partition(b':')
        if not separator or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key):
            raise DeliveryError('invalid GitHub response header')
        key = key.decode('ascii').lower()
        if key in RATE_HEADERS or pagination and key == 'link':
            kind = 'pagination' if key == 'link' else 'rate-limit'
            if key in headers:
                raise DeliveryError('ambiguous GitHub ' + kind + ' headers')
            try:headers[key] = value.decode('ascii').strip()
            except UnicodeError:raise DeliveryError('invalid GitHub ' + kind + ' header') from None
    return int(status[1]), headers


def rate_integer(value):
    return int(value) if isinstance(value, str) and re.fullmatch(r'[0-9]{1,12}', value) else None


def rate_diagnostic(status, headers):
    # Only parsed status and bounded numeric quota fields may reach public logs.
    fields = ['HTTP ' + str(status)]
    for name in ('x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset'):
        number = rate_integer(headers.get(name))
        if number is not None:fields.append(name.removeprefix('x-ratelimit-') + '=' + str(number))
    return '; '.join(fields)


class HTTPFailure(DeliveryError):
    def __init__(self, status, headers, payload=b''):
        super().__init__('GitHub API request failed (' + rate_diagnostic(status, headers) + ')')
        self.status, self.headers, self.rate_message = status, headers, False
        # Some secondary 403 responses omit Retry-After. Recognize only GitHub's
        # explicit rate-limit messages, never arbitrary forbidden/error text.
        if status in (403, 429) and len(payload) <= 4096:
            try:
                value = parse(payload)
                message = value.get('message') if isinstance(value, dict) else None
                self.rate_message = isinstance(message, str) and (
                    message.startswith('API rate limit exceeded for ')
                    or message == 'API rate limit exceeded.'
                    or message.startswith('You have exceeded a secondary rate limit.')
                    or message.startswith('You have triggered an abuse detection mechanism.'))
            except (UnicodeError, ValueError):pass


class ReleaseInventoryShift(DeliveryError):
    """Only validated release IDs repeated across distinct pages are recoverable."""


class PublicReleaseRedirects(HTTPRedirectHandler):
    """Public bytes never carry credentials, including across CDN redirects."""
    max_redirections = 5
    max_repeats = 2

    def __init__(self, initial):
        self.initial = initial

    def validate(self, url):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc not in
                ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com') or
                parsed.fragment or not parsed.path.startswith('/') or
                parsed.netloc == 'github.com' and url != self.initial):
            raise DeliveryError('public asset redirect escaped the selected HTTPS release')
        return url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.validate(newurl)
        # Reconstruct instead of inheriting a caller's authentication headers.
        return Request(newurl, headers={'User-Agent': 'software-foundation-release/1'})


def workflow_context_matches(context):
    """An explicit caller snapshot must belong to this exact executing workflow."""
    if not isinstance(context, dict) or set(context) != {'repository','run_id','attempt','source_commit','workflow'}:
        return False
    return (os.environ.get('GITHUB_ACTIONS') == 'true' and
            os.environ.get('GITHUB_REPOSITORY') == context['repository'] and
            positive(context['run_id']) and positive(context['attempt']) and
            os.environ.get('GITHUB_RUN_ID') == str(context['run_id']) and
            os.environ.get('GITHUB_RUN_ATTEMPT') == str(context['attempt']) and
            os.environ.get('GITHUB_SHA') == context['source_commit'] and
            isinstance(context['source_commit'],str) and OID.fullmatch(context['source_commit']) is not None and
            isinstance(context['workflow'],str) and re.fullmatch(r'[a-zA-Z0-9_-]+\.yml',context['workflow']) is not None and
            os.environ.get('GITHUB_WORKFLOW_REF','').startswith(
                context['repository']+'/.github/workflows/'+context['workflow']+'@'))


class GitHub:
    """Bounded read retries; writes are never replayed after an ambiguous result."""
    WAIT_BUDGET = 180 * 60
    REQUEST_DEADLINE = 180 * 60
    COMMAND_TIMEOUT = 10 * 60
    MAX_ATTEMPTS = 8
    RELEASE_INVENTORY_RETRIES = 2
    RELEASE_PAGE_LIMIT = 256
    RELEASE_REQUEST_LIMIT = 768
    WRITE_HEADROOM = 128
    QUOTA_MAX_AGE = 30
    TRANSIENT_STATUS = frozenset((500, 502, 503, 504))

    def __init__(self, repository, *, metrics=None):
        self.metrics = metrics if metrics is not None else REQUEST_METRICS
        self.repository = location(repository)
        self.wait_remaining = float(self.WAIT_BUDGET)
        self._budget_lock = threading.Lock()
        self._quota_lock = threading.Lock()
        self._quota_probe_lock = threading.Lock()
        self._quota = None

    def _run(self, arguments, *, body=None, output=None, timeout=None):
        budget = self.COMMAND_TIMEOUT if timeout is None else timeout
        started = time.monotonic()
        if not REQUEST_SLOTS.acquire(timeout=budget):
            raise DeliveryError('GitHub request capacity wait exceeded its bounded deadline')
        call_started = None
        try:
            acquired = time.monotonic()
            self.metrics.add(capacity_wait_seconds=acquired - started)
            remaining = budget - (acquired - started)
            if remaining <= 0: raise DeliveryError('GitHub CLI request exceeded its bounded deadline')
            call_started = time.monotonic()
            self.metrics.add(cli_calls=1)
            return subprocess.run(['gh', *arguments], input=body,
                stdout=output if output is not None else subprocess.PIPE,
                stderr=subprocess.PIPE, check=False, timeout=remaining)
        except subprocess.TimeoutExpired:
            raise DeliveryError('GitHub CLI request exceeded its bounded deadline') from None
        except OSError:
            raise DeliveryError('GitHub CLI request could not complete') from None
        finally:
            if call_started is not None:
                self.metrics.add(cli_seconds=time.monotonic() - call_started)
            REQUEST_SLOTS.release()

    def _timeout(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:raise DeliveryError('GitHub request deadline exhausted')
        return min(self.COMMAND_TIMEOUT, remaining)

    def _wait(self, delay, diagnostic, deadline):
        delay += random.uniform(1, 5)
        if delay >= deadline - time.monotonic():
            raise DeliveryError('GitHub request deadline exhausted (' + diagnostic + ')')
        with self._budget_lock:
            if delay > self.wait_remaining:
                raise DeliveryError('GitHub read-retry wait budget exhausted (' + diagnostic + ')')
            self.wait_remaining -= delay
            remaining_budget = self.wait_remaining
        print(f'GitHub read retry ({diagnostic}); waiting {delay:.1f}s; '
              f'wait budget remaining {remaining_budget:.1f}s', file=sys.stderr, flush=True)
        remaining = delay; started = time.monotonic()
        try:
            while remaining > 0:
                self._timeout(deadline)
                step = min(60, remaining)
                time.sleep(step)  # Interrupts/cancellation propagate; no detached sleeper.
                remaining -= step
        finally:
            self.metrics.add(retry_wait_seconds=time.monotonic() - started)

    def _retry_delay(self, failure, attempt):
        if failure.status not in (403, 429) and failure.status not in self.TRANSIENT_STATUS:return None
        headers = failure.headers
        delays = []
        retry = headers.get('retry-after')
        seconds = rate_integer(retry)
        if seconds is not None:
            delays.append(seconds)
        elif isinstance(retry, str) and len(retry) <= 100:
            try:
                date = parsedate_to_datetime(retry)
                if date.tzinfo is not None:delays.append(max(0, date.timestamp() - time.time()))
            except (ValueError, TypeError, OverflowError):pass
        reset = rate_integer(headers.get('x-ratelimit-reset'))
        if rate_integer(headers.get('x-ratelimit-remaining')) == 0 and reset is not None:
            delays.append(max(1, reset - time.time()))
        if delays:return max(delays)
        if failure.status == 429 or failure.rate_message:
            return min(60 * 2 ** (attempt - 1), 15 * 60)
        if failure.status in self.TRANSIENT_STATUS:
            return min(2 * 2 ** (attempt - 1), 60)
        return None

    def _wait_after_failure(self, error, attempt, deadline):
        delay = self._retry_delay(error, attempt)
        if delay is None:raise error
        if attempt == self.MAX_ATTEMPTS:
            raise DeliveryError('GitHub read-retry attempt limit exhausted (' +
                                rate_diagnostic(error.status, error.headers) + ')') from None
        self._wait(delay, rate_diagnostic(error.status, error.headers), deadline)

    def _read(self, operation, *, deadline=None, inventory_retries=0, check_retry_budget=None):
        deadline = deadline if deadline is not None else time.monotonic() + self.REQUEST_DEADLINE
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            self._timeout(deadline)
            try:return operation(deadline)
            except HTTPFailure as error:
                # Permission and unrelated failures retain their original error,
                # even when this read has also used its inventory request budget.
                if self._retry_delay(error, attempt) is None:raise
                if check_retry_budget is not None:check_retry_budget()
                self._wait_after_failure(error, attempt, deadline)
            except ReleaseInventoryShift as error:
                if inventory_retries <= 0:
                    raise DeliveryError('GitHub release inventory retry limit exhausted; '
                                        'repeated release ID across response pages') from None
                if attempt == self.MAX_ATTEMPTS:
                    raise DeliveryError('GitHub read-retry attempt limit exhausted; '
                                        'repeated release ID across response pages') from None
                if check_retry_budget is not None:check_retry_budget()
                inventory_retries -= 1
                self._wait(min(2 * 2 ** (attempt - 1), 60), str(error), deadline)

    def _json_once(self, endpoint, method, body, missing, deadline, *, response_metadata=None):
        arguments = ['api', '--hostname', 'github.com', '--include', '--method', method, endpoint]
        if body is not None:arguments += ['--input', '-']
        result = self._run(arguments, body=body, timeout=self._timeout(deadline))
        if len(result.stdout) > HTTP_JSON_LIMIT:
            raise DeliveryError('remote JSON exceeds supported inventory limit')
        stream = io.BytesIO(result.stdout)
        status, headers = response_head(stream, pagination=response_metadata is not None);payload = stream.read()
        if response_metadata is not None:response_metadata.update(headers=headers, size=len(result.stdout))
        self._observe(headers, quota_probe=endpoint == 'rate_limit')
        if missing and status == 404 and result.returncode:return None
        if not 200 <= status < 300:raise HTTPFailure(status, headers, payload)
        if result.returncode:raise DeliveryError('GitHub API response was incomplete')
        if status == 204:
            if payload: raise DeliveryError('HTTP 204 response must have an empty body')
            return None
        try:return parse(payload)
        except (UnicodeError, ValueError):raise DeliveryError('invalid complete GitHub JSON response') from None

    def _remember_core(self, numbers):
        # Per-client observations only, never a reservation against other jobs.
        # Out-of-order responses cannot replenish locally admitted writes.
        with self._quota_lock:
            before = self._quota
            if before is not None and numbers['reset'] < before['reset']:
                return
            remaining = numbers['remaining']
            if before is not None and numbers['reset'] == before['reset']:
                remaining = min(remaining, before['remaining'])
            self._quota = dict(numbers, remaining=remaining, observed=time.monotonic())

    def _observe(self, headers, *, quota_probe=False):
        self.metrics.observe(headers, quota_probe=quota_probe)
        if headers.get('x-ratelimit-resource') != 'core':
            return
        numbers = {key: rate_integer(headers.get('x-ratelimit-' + key))
                   for key in ('limit', 'remaining', 'reset')}
        if (positive(numbers['limit']) and positive(numbers['reset']) and
                numbers['remaining'] is not None and 0 <= numbers['remaining'] <= numbers['limit']):
            self._remember_core(numbers)

    def _reserve_headroom(self):
        with self._quota_lock:
            quota = self._quota
            if (quota is None or not 0 <= time.monotonic() - quota['observed'] < self.QUOTA_MAX_AGE or
                    quota['reset'] <= time.time() or
                    quota['remaining'] < min(self.WRITE_HEADROOM, quota['limit'])):
                return False
            quota['remaining'] -= 1
            return True

    def _headroom(self):
        if self.WRITE_HEADROOM <= 0 or self._reserve_headroom():
            return
        # One fallback probe can serve waiting upload workers as well. Network
        # and backoff never hold the observation lock used by response handlers.
        deadline = time.monotonic() + self.REQUEST_DEADLINE
        if not self._quota_probe_lock.acquire(timeout=self.REQUEST_DEADLINE):
            raise DeliveryError('GitHub quota observation wait exceeded request deadline')
        try:
            self._timeout(deadline)
            if self._reserve_headroom():
                return
            self._probe_headroom(deadline)
        finally:
            self._quota_probe_lock.release()

    def _probe_headroom(self, deadline):
        """Fallback only when fresh response headers cannot admit this write."""
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:value = self._json_once('rate_limit', 'GET', None, False, deadline)
            except HTTPFailure as error:
                self._wait_after_failure(error, attempt, deadline)
                continue
            resources = value.get('resources', {}) if isinstance(value, dict) else {}
            core = resources.get('core', {}) if isinstance(resources, dict) else {}
            if (not isinstance(core, dict) or not positive(core.get('limit'))
                    or type(core.get('remaining')) is not int or not 0 <= core['remaining'] <= core['limit']
                    or not positive(core.get('reset'))):
                raise DeliveryError('GitHub primary quota preflight returned invalid core limits')
            self._remember_core({key: core[key] for key in ('limit', 'remaining', 'reset')})
            if self._reserve_headroom():return
            if core['remaining'] >= min(self.WRITE_HEADROOM, core['limit']) and core['reset'] > time.time():
                # Local reservations are deliberately conservative. A fresh
                # successful probe still admits this write just as before;
                # do not wait an hour only because cached estimates were lower.
                # Keep the cache conservative for other concurrent admissions.
                with self._quota_lock:
                    self._quota['remaining'] = max(0, self._quota['remaining'] - 1)
                return
            diagnostic = rate_diagnostic(200, {'x-ratelimit-' + k:str(core[k]) for k in ('limit','remaining','reset')})
            if attempt == self.MAX_ATTEMPTS:
                raise DeliveryError('GitHub quota preflight attempt limit exhausted (' + diagnostic + ')')
            self._wait(max(1, core['reset'] - time.time()), diagnostic, deadline)

    def json(self, endpoint, *, method='GET', body=None, missing=False):
        encoded = archive.encoded(body) if body is not None else None
        if method == 'GET':
            return self._read(lambda end: self._json_once(endpoint, method, encoded, missing, end))
        if self.WRITE_HEADROOM > 0: self._headroom()
        try:return self._json_once(endpoint, method, encoded, missing, time.monotonic() + self.REQUEST_DEADLINE)
        except DeliveryError as error:
            raise DeliveryError(str(error) + '; remote outcome requires reconciliation', True) from None

    def pages(self, endpoint):
        # gh2.23 (bookworm) supports --include/--paginate, but not --slurp.
        # Each attempt restarts the complete inventory; no prefix survives a retry.
        def attempt(deadline):
            result = self._run(['api', '--hostname', 'github.com', '--include', '--paginate',
                                '--method', 'GET', endpoint], timeout=self._timeout(deadline))
            raw = result.stdout
            if len(raw) > HTTP_JSON_LIMIT:
                raise DeliveryError('remote pagination exceeds supported inventory limit')
            stream = io.BytesIO(raw)
            decoder = json.JSONDecoder(object_pairs_hook=coverage.object_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(DeliveryError('nonfinite remote JSON')))
            pages = []
            try:
                while stream.tell() < len(raw):
                    # gh inserts a newline between included page responses.
                    while stream.tell() < len(raw) and raw[stream.tell()] in b' \r\n\t':stream.seek(1, 1)
                    if stream.tell() == len(raw):break
                    status, headers = response_head(stream)
                    self._observe(headers)
                    if not 200 <= status < 300:raise HTTPFailure(status, headers, stream.read(4097))
                    # A later error body is opaque, even if it is not UTF-8.
                    # Strictly re-encode only this successful JSON page below.
                    offset = stream.tell();tail = raw[offset:].decode('utf-8', errors='surrogateescape')
                    leading = len(tail) - len(tail.lstrip())
                    page, end = decoder.raw_decode(tail, leading)
                    if not isinstance(page, list):raise DeliveryError('expected every page of a remote array')
                    pages.append(page);stream.seek(offset + len(tail[:end].encode('utf-8')))
                if result.returncode or not pages:raise DeliveryError('incomplete remote page inventory')
            except HTTPFailure:raise
            except (UnicodeError, ValueError):
                raise DeliveryError('complete remote pagination failed; invalid or incomplete response stream') from None
            return [item for page in pages for item in page]
        return self._read(attempt)

    def release_inventory(self, tag):
        """Initial discovery only, with bounded complete-inventory recovery.

        Explicit Link-driven requests admit each page against one shared API
        budget. No trailing empty-page probe is needed on a successful read.
        Transport failures and validated pagination shifts share _read's attempt,
        deadline and cumulative wait budgets; neither starts a nested retry loop.
        """
        endpoint = f'repos/{self.repository}/releases?per_page=100'
        requests = 0
        def check_budget():
            if requests >= self.RELEASE_REQUEST_LIMIT:
                raise DeliveryError('GitHub release discovery API-request budget exhausted')
        def attempt(deadline):
            nonlocal requests
            rows, seen, matches = [], set(), set()
            shifted, size, page_number = False, 0, 1
            while True:
                self._timeout(deadline);check_budget()
                if page_number > self.RELEASE_PAGE_LIMIT:
                    raise DeliveryError('GitHub release inventory page limit exhausted')
                metadata = {};requests += 1
                page = self._json_once(endpoint if page_number == 1 else endpoint + '&page=' + str(page_number),
                                       'GET', None, False, deadline, response_metadata=metadata)
                size += metadata['size']
                if size > HTTP_JSON_LIMIT:
                    raise DeliveryError('remote pagination exceeds supported inventory limit')
                if not isinstance(page, list):raise DeliveryError('expected every page of a remote array')
                page_ids = set()
                for row in page:
                    if not isinstance(row, dict) or not positive(row.get('id')):
                        raise DeliveryError('invalid or duplicate release inventory entry')
                    if not isinstance(row.get('tag_name'), str):
                        raise DeliveryError('incomplete release inventory')
                    Remote.info(row, row['tag_name'])
                    identity = row['id']
                    if identity in page_ids:
                        raise DeliveryError('invalid or duplicate release inventory entry')
                    page_ids.add(identity)
                    if identity in seen:shifted = True
                    seen.add(identity)
                    if row['tag_name'] == tag:matches.add(identity)
                    if len(matches) > 1:raise DeliveryError('duplicate release tags require inspection')
                rows.extend(page)
                if not self._next_release_page(metadata['headers'], page_number):break
                page_number += 1
            # Validate the entire inventory before granting recovery. Later
            # malformed rows or ambiguous tags cannot be concealed by a shift.
            if shifted:raise ReleaseInventoryShift('repeated release ID across response pages')
            return rows
        return self._read(attempt, inventory_retries=self.RELEASE_INVENTORY_RETRIES,
                          check_retry_budget=check_budget)

    def _next_release_page(self, headers, page_number):
        value = headers.get('link')
        if value is None:return False
        relations = {}
        for entry in value.split(','):
            link = re.fullmatch(r'\s*<([^<>]+)>;\s*rel="(next|prev|first|last)"\s*', entry)
            if link is None or link[2] in relations:
                raise DeliveryError('invalid or ambiguous GitHub release pagination link')
            try:
                url = urlsplit(link[1])
                query = parse_qsl(url.query, strict_parsing=True)
            except ValueError:
                raise DeliveryError('invalid GitHub release pagination destination') from None
            fields = dict(query)
            if (url.scheme != 'https' or url.netloc != 'api.github.com' or url.fragment or
                    url.path.casefold() != ('/repos/' + self.repository + '/releases').casefold() and
                    re.fullmatch(r'/repositories/[1-9][0-9]*/releases', url.path) is None or
                    len(query) != 2 or set(fields) != {'per_page', 'page'} or fields['per_page'] != '100' or
                    not re.fullmatch(r'[1-9][0-9]{0,8}', fields['page'])):
                raise DeliveryError('invalid GitHub release pagination destination')
            relations[link[2]] = int(fields['page'])
        if 'next' in relations and relations['next'] != page_number + 1:
            raise DeliveryError('GitHub release pagination did not advance exactly one page')
        if ('first' in relations and relations['first'] != 1 or
                'prev' in relations and relations['prev'] != page_number - 1 or
                'last' in relations and relations['last'] < relations.get('next', page_number) or
                'last' in relations and relations['last'] > page_number and 'next' not in relations):
            raise DeliveryError('inconsistent or incomplete GitHub release pagination links')
        return 'next' in relations

    def upload(self, tag, path):
        self._headroom()
        try:
            result = self._run(['release', 'upload', tag, '--repo', 'github.com/' + self.repository, str(path)])
        except DeliveryError as error:
            raise DeliveryError(str(error) + '; remote outcome requires reconciliation', True) from None
        if result.returncode:
            raise DeliveryError('asset upload failed; remote outcome requires reconciliation', True)

    def upload_to(self, release_id, path):
        """Upload once to a known immutable release ID, with no tag lookup."""
        from urllib.parse import quote
        if not positive(release_id): raise DeliveryError('positive upload release ID required')
        path = Path(path).absolute(); name = valid_name(path.name)
        if path.is_symlink() or not path.is_file(): raise DeliveryError('upload requires an ordinary payload file')
        before = path.stat(); expected = archive.digest(path)
        self._headroom()
        endpoint = f'https://uploads.github.com/repos/{self.repository}/releases/{release_id}/assets?name=' + quote(name, safe='')
        try:
            result = self._run(['api', '--hostname', 'github.com', '--include', '--method', 'POST', endpoint,
                '--input', str(path), '-H', 'Content-Type: application/octet-stream',
                '-H', 'Content-Length: ' + str(before.st_size), '-H', 'Accept: application/vnd.github+json'])
            response = io.BytesIO(result.stdout); status, headers = response_head(response)
            self._observe(headers)
            if result.returncode or status != 201:
                raise DeliveryError('asset upload failed; remote outcome requires reconciliation', True)
            body = response.read(HTTP_JSON_LIMIT + 1)
            if len(body) > HTTP_JSON_LIMIT: raise DeliveryError('upload response exceeds inventory limit', True)
            row = parse(body); after = path.stat()
            if (not isinstance(row, dict) or not positive(row.get('id')) or row.get('name') != name or
                    row.get('state') != 'uploaded' or row.get('size') != before.st_size or
                    row.get('digest') != 'sha256:' + expected or archive.digest(path) != expected or
                    (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
                raise DeliveryError('uploaded asset or local payload identity differs', True)
            self.metrics.add(uploaded_bytes=before.st_size)
        except (DeliveryError, OSError, ValueError) as error:
            raise DeliveryError('asset upload could not be confirmed; remote outcome requires reconciliation', True) from error

    def download(self, asset_id, path):
        path = Path(path)
        if path.exists() or path.is_symlink():raise DeliveryError('asset download destination must be new')
        def attempt(deadline):
            # Each failed attempt closes and removes its complete private response
            # before any wait. Header bytes and partial payloads never reach path.
            with tempfile.TemporaryDirectory(prefix='.github-download-', dir=path.parent) as temporary:
                raw = Path(temporary) / 'response'
                with raw.open('xb') as stream:
                    result = self._run(['api', '--hostname', 'github.com', '--include', '--method', 'GET',
                        f'repos/{self.repository}/releases/assets/{asset_id}',
                        '-H', 'Accept:application/octet-stream'], output=stream, timeout=self._timeout(deadline))
                with raw.open('rb') as stream:
                    status, headers = response_head(stream)
                    self._observe(headers)
                    if not 200 <= status < 300:raise HTTPFailure(status, headers, stream.read(4097))
                    if result.returncode or status != 200:
                        raise DeliveryError('asset download failed; incomplete response must not be reused')
                    with path.open('xb') as destination:shutil.copyfileobj(stream, destination)
                    self.metrics.add(downloaded_bytes=path.stat().st_size)
        return self._read(attempt)

    def download_public(self, url, path, size, digest):
        """Fetch hash-pinned public bytes without an authenticated REST request."""
        parsed = urlsplit(url)
        prefix = '/' + self.repository + '/releases/download/'
        if (parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment or
                not parsed.path.startswith(prefix) or len(parsed.path[len(prefix):].split('/')) != 2 or
                type(size) is not int or not 0 <= size < 2*1024**3 or not isinstance(digest,str) or not SHA.fullmatch(digest)):
            raise DeliveryError('public download requires an exact release URL, size and digest')
        path = Path(path)
        if path.exists() or path.is_symlink(): raise DeliveryError('asset download destination must be new')
        deadline = time.monotonic() + 10*60
        def attempt(end):
            started = time.monotonic()
            if not REQUEST_SLOTS.acquire(timeout=self._timeout(end)):
                raise DeliveryError('public download capacity deadline exhausted')
            acquired = time.monotonic(); self.metrics.add(capacity_wait_seconds=acquired-started, public_downloads=1)
            try:
                redirects = PublicReleaseRedirects(url)
                request = Request(redirects.validate(url), headers={'User-Agent':'software-foundation-release/1'})
                with tempfile.TemporaryDirectory(prefix='.github-public-',dir=path.parent) as temporary:
                    staged = Path(temporary)/'payload'; total=0; hashed=hashlib.sha256()
                    try:
                        with build_opener(redirects).open(request,timeout=min(60,self._timeout(end))) as response, staged.open('xb') as output:
                            redirects.validate(response.url)
                            if response.status != 200: raise DeliveryError('public asset response was incomplete')
                            while True:
                                self._timeout(end)
                                data=response.read1(min(1024*1024,size-total+1))
                                self._timeout(end)
                                if not data: break
                                total+=len(data)
                                if total>size: raise DeliveryError('public asset exceeds declared size')
                                hashed.update(data);output.write(data)
                    except HTTPError as error:
                        with error:
                            headers={key:error.headers.get(key) for key in RATE_HEADERS if error.headers.get(key) is not None}
                            raise HTTPFailure(error.code,headers,b'') from None
                    except (OSError,URLError):
                        raise DeliveryError('public asset transfer failed; incomplete bytes discarded') from None
                    if total!=size or hashed.hexdigest()!=digest:
                        raise DeliveryError('public asset bytes differ from complete inventory')
                    with staged.open('rb') as incoming,path.open('xb') as output: shutil.copyfileobj(incoming,output)
                    self.metrics.add(downloaded_bytes=total)
            finally:
                self.metrics.add(public_download_seconds=time.monotonic()-acquired)
                REQUEST_SLOTS.release()
        return self._read(attempt,deadline=deadline)


class Remote:
    def __init__(self, repository, transport=None):
        self.repository = location(repository)
        self.transport = transport or GitHub(repository)
        self.base = f'repos/{repository}'
        self.mutated = False
        self.private = None
        self._public_assets = {}

    def visible(self):
        value = self.transport.json(self.base)
        if (not isinstance(value, dict) or not isinstance(value.get('full_name'), str)
                or value['full_name'].casefold() != self.repository.casefold() or type(value.get('private')) is not bool):
            raise DeliveryError('repository visibility or identity is unconfirmed')
        self.private = value['private']
        return self.private

    def published(self, tag, required=True):
        """Use GitHub's exact published-tag endpoint, independent of release history."""
        valid_name(tag)
        value = self.transport.json(self.base + '/releases/tags/' + quote(tag,safe=''), missing=True)
        if value is None:
            if required: raise DeliveryError('required published release is absent; no implicit fallback')
            return None
        self.info(value,tag)
        if value['draft']: raise DeliveryError('published release endpoint returned a draft')
        return value

    def by_id(self, identity, tag):
        if not positive(identity): raise DeliveryError('positive release identity required')
        value = self.info(self.transport.json(self.base + '/releases/' + str(identity)),tag)
        if value['id'] != identity: raise DeliveryError('release identity changed during operation')
        return value

    def pin_published(self, info, assets, private):
        """Bind local immutable download inputs from an authenticated snapshot."""
        self.info(info,info.get('tag_name'))
        if info['draft'] or type(private) is not bool: raise DeliveryError('published repository visibility is required')
        self.private = private
        if not private:
            for name,row in assets.items():
                valid_name(name)
                if not positive(row.get('id')) or row.get('name') != name:
                    raise DeliveryError('public asset identity differs')
                url='https://github.com/'+self.repository+'/releases/download/'+quote(info['tag_name'],safe='')+'/'+quote(name,safe='')
                self._public_assets[row['id']] = url

    def find(self, tag, required=True):
        if hasattr(self.transport, 'release_inventory'):
            rows = self.transport.release_inventory(tag)
        else:
            rows = self.transport.pages(self.base + '/releases?per_page=100')
        seen = set()
        matches = []
        for row in rows:
            if not isinstance(row, dict) or not positive(row.get('id')) or row['id'] in seen:
                raise DeliveryError('invalid or duplicate release inventory entry')
            seen.add(row['id'])
            if not isinstance(row.get('tag_name'), str):
                raise DeliveryError('incomplete release inventory')
            if row['tag_name'] == tag:
                self.info(row, tag)
                matches.append(row)
        if len(matches) > 1:
            raise DeliveryError('duplicate release tags require inspection')
        if not matches:
            if required:
                raise DeliveryError('required release is absent; no implicit build or publication')
            return None
        return matches[0]

    def wait_find(self, tag, *, release_id=None):
        """Bounded observation after initialization; never repeat a mutation."""
        if release_id is not None and not positive(release_id):
            raise DeliveryError('positive release identity required')
        for delay in (0, .25, .5, 1, 2, 4, 8):
            if delay: time.sleep(delay)
            if release_id is None:
                found = self.find(tag, required=False)
            else:
                # A confirmed creation response already identifies the resource.
                # Unrelated draft inserts must not shift its observation pages.
                found = self.transport.json(self.base + '/releases/' + str(release_id), missing=True)
                if found is not None:
                    self.info(found, tag)
                    if found['id'] != release_id:
                        raise DeliveryError('observed release ID differs from creation response')
            if found is not None:
                return found
        raise DeliveryError('release is not visible; preserve initialization state and reconcile')

    @staticmethod
    def info(value, tag):
        if (not isinstance(value, dict) or not positive(value.get('id')) or value.get('tag_name') != tag
                or type(value.get('draft')) is not bool or type(value.get('prerelease')) is not bool
                or not isinstance(value.get('name'), str)):
            raise DeliveryError('invalid release identity or lifecycle fields')
        return value

    def assets(self, info):
        rows = self.transport.pages(self.base + f'/releases/{info["id"]}/assets?per_page=100')
        assets, ids, folded = {}, set(), set()
        for row in rows:
            if not isinstance(row, dict):
                raise DeliveryError('invalid asset entry')
            name = valid_name(row.get('name'))
            if (name.casefold() in folded or not positive(row.get('id')) or row['id'] in ids
                    or row.get('state') != 'uploaded' or type(row.get('size')) is not int or row['size'] < 0
                    or not isinstance(row.get('digest'), str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', row['digest'])):
                raise DeliveryError('duplicate, incomplete or unbound asset inventory')
            assets[name] = {key: row[key] for key in ('id', 'name', 'state', 'size', 'digest')}
            ids.add(row['id']); folded.add(name.casefold())
        if self.private is not None and info['draft'] is False: self.pin_published(info,assets,self.private)
        return assets

    def reference(self, tag, missing=False):
        value = self.transport.json(self.base + '/git/ref/tags/' + tag, missing=missing)
        if value is None:
            return None
        obj = value.get('object', {}) if isinstance(value, dict) else {}
        if (not isinstance(obj, dict) or obj.get('type') != 'commit'
                or not isinstance(obj.get('sha'), str) or not OID.fullmatch(obj['sha'])):
            raise DeliveryError('tag must directly identify the frozen commit')
        return obj['sha']

    def change(self, endpoint, *, method='POST', body=None):
        self.mutated = True
        return self.transport.json(self.base + endpoint, method=method, body=body)

    def upload(self, tag, path):
        self.mutated = True
        self.transport.upload(tag, path)

    def upload_to(self, info, path):
        # Callers retain this validated release snapshot through their final
        # complete asset reconciliation; no response-loss mutation is replayed.
        self.info(info, info.get('tag_name'))
        self.mutated = True
        if hasattr(self.transport, 'upload_to'):
            return self.transport.upload_to(info['id'], path)
        return self.transport.upload(info['tag_name'], path)

    def download(self, row, path, expected=None):
        expected = expected or row['digest'][7:]
        if row['digest'] != 'sha256:' + expected:
            raise DeliveryError('remote asset differs from expected bytes')
        public_url = self._public_assets.get(row['id'])
        if self.private is False and public_url is not None and hasattr(self.transport,'download_public'):
            self.transport.download_public(public_url,path,row['size'],expected)
        else:
            self.transport.download(row['id'], path)
        if Path(path).stat().st_size != row['size'] or archive.digest(path) != expected:
            raise DeliveryError('downloaded asset bytes differ from complete inventory')

    def unchanged(self, tag, before, assets, expected_ref=None):
        after = self.by_id(before['id'],tag) if before['draft'] is False else self.find(tag)
        for key in ('id', 'tag_name', 'name', 'draft', 'prerelease'):
            if after[key] != before[key]:
                raise DeliveryError('release identity or lifecycle changed during operation')
        if self.assets(after) != assets:
            raise DeliveryError('remote asset identities changed during operation')
        if expected_ref is not None and self.reference(tag) != expected_ref:
            raise DeliveryError('tag identity changed during operation')
        return after

    def not_latest(self, info):
        value = self.transport.json(self.base + '/releases/latest', missing=True)
        if value is not None:
            self.info(value, value.get('tag_name'))
            if value['id'] == info['id']:
                raise DeliveryError('candidate or base was unexpectedly selected as Latest')


def plan(operation, repository, **details):
    value = dict(operation=operation, repository=location(repository), execute=False, **details)
    value['plan_sha256'] = coverage.digest(value)
    return value


def run_mutation(remote, action):
    try:
        return action()
    except BaseException as error:
        if remote.mutated:
            raise DeliveryError('remote outcome uncertain; reconcile tag, release ID, inventory and bytes before retry: '
                                + str(error), True) from error
        raise


def candidate_identity(directory, repository, tag, source_commit, packager_commit, publication_id, experiment=False):
    location(repository, tag)
    if tag == 'base' or not OID.fullmatch(source_commit) or not OID.fullmatch(packager_commit):
        raise DeliveryError('candidate needs a distinct tag and complete source/packager commits')
    valid_name(publication_id)
    if type(experiment) is not bool or (not experiment and source_commit != packager_commit):
        raise DeliveryError('different packaging revision requires an experiment')
    directory = Path(directory)
    manifest = release.verify_release(directory)
    mapping, seen = {}, {'delivery.json'}
    for name in sorted([*manifest['files'], 'release.json']):
        path = archive.checked_file(directory, name)
        asset = valid_name(path.name)
        if asset.casefold() in seen or CERT.fullmatch(asset):
            raise DeliveryError('flattened asset names collide with another asset or evidence namespace')
        seen.add(asset.casefold())
        mapping[name] = {'asset': asset, 'sha256': archive.digest(path), 'size': path.stat().st_size}
        if name != 'release.json' and mapping[name]['sha256'] != manifest['files'][name]:
            raise DeliveryError('local release changed while freezing delivery identity')
    archive.verify_inventory(directory, manifest['files'], exclude=('release.json',))
    if (coverage.load(directory / 'release.json') != manifest or
            archive.digest(directory / 'release.json') != mapping['release.json']['sha256']):
        raise DeliveryError('local release changed while freezing delivery identity')
    return {'schema_version': 1, 'repository': repository, 'tag': tag, 'source_commit': source_commit,
            'packager_commit': packager_commit, 'tag_commit': packager_commit,
            'publication_id': publication_id, 'experiment': experiment,
            'source_sha256': manifest['source']['sha256'], 'inventory_sha256': archive.digest(directory / 'release.json'),
            'files': mapping}


def validate_delivery(delivery, directory, *, metadata_only=False):
    if not isinstance(delivery, dict):
        raise DeliveryError('delivery identity must be an object')
    if metadata_only:
        metadata = release.verify_metadata(directory)
        coverage.fields(delivery, {'schema_version', 'repository', 'tag', 'source_commit', 'packager_commit', 'tag_commit',
            'publication_id', 'experiment', 'source_sha256', 'inventory_sha256', 'files'})
        location(delivery['repository'], delivery['tag']); valid_name(delivery['publication_id'])
        if (delivery['schema_version'] != 1 or type(delivery['experiment']) is not bool or
                not OID.fullmatch(delivery['source_commit']) or not OID.fullmatch(delivery['packager_commit']) or
                delivery['tag_commit'] != delivery['packager_commit'] or
                not delivery['experiment'] and delivery['source_commit'] != delivery['packager_commit'] or
                delivery['source_sha256'] != metadata['source']['sha256'] or
                delivery['inventory_sha256'] != archive.digest(Path(directory) / 'release.json')):
            raise DeliveryError('delivery identity differs from complete release metadata')
        expected = dict(metadata['files'], **{'release.json': delivery['inventory_sha256']})
        if set(delivery['files']) != set(expected): raise DeliveryError('delivery file inventory differs')
        seen = {'delivery.json'}
        for name, digest in expected.items():
            item = delivery['files'][name]; coverage.fields(item, {'asset', 'sha256', 'size'})
            asset = valid_name(Path(name).name)
            if (item['asset'] != asset or item['sha256'] != digest or asset.casefold() in seen or
                    CERT.fullmatch(asset) or type(item['size']) is not int or item['size'] < 0):
                raise DeliveryError('delivery asset identity differs from complete metadata')
            seen.add(asset.casefold())
        return sha(archive.encoded(delivery))
    expected = candidate_identity(directory, **{key: delivery[key] for key in
        ('repository', 'tag', 'source_commit', 'packager_commit', 'publication_id', 'experiment')})
    if expected != delivery:
        raise DeliveryError('delivery identity differs from complete local release')
    return sha(archive.encoded(delivery))


def evidence_pairs(names):
    groups = {}
    for name in names:
        match = CERT.fullmatch(name)
        if not match:
            raise DeliveryError('unexpected asset outside immutable delivery and certificate attempts')
        groups.setdefault((match[1], match[2]), set()).add(match[3])
    if any(parts != {'json', 'tar.gz'} for parts in groups.values()):
        raise DeliveryError('partial certificate attempt requires reconciliation')


def validate_remote_inventory(delivery, info, assets, *, draft=False, prerelease=None):
    """Reconcile a complete observed inventory without fetching it repeatedly."""
    if prerelease is not None and type(prerelease) is not bool:
        raise DeliveryError('prerelease pin must be a boolean or None')
    tag = delivery['tag']; Remote.info(info,tag)
    title = 'experiment' if delivery['experiment'] else tag
    # Ordinary candidates are prereleases until certification permits promotion.
    # Experiment identity remains immutable and can never become an ordinary release.
    if (info['draft'] != draft or info['name'] != title
            or (delivery['experiment'] and not info['prerelease'])
            or (prerelease is not None and info['prerelease'] != prerelease)):
        raise DeliveryError('release lifecycle does not match frozen delivery')
    expected = {item['asset'] for item in delivery['files'].values()} | {'delivery.json'}
    if not expected <= assets.keys():
        raise DeliveryError('published delivery is missing required assets')
    extras = set(assets) - expected
    if draft and extras:
        raise DeliveryError('unexpected draft assets')
    evidence_pairs(extras)
    for item in delivery['files'].values():
        row = assets[item['asset']]
        if row['digest'] != 'sha256:' + item['sha256'] or row['size'] != item['size']:
            raise DeliveryError('remote asset differs from complete frozen inventory')
    descriptor = archive.encoded(delivery)
    if assets['delivery.json']['digest'] != 'sha256:' + sha(descriptor) or assets['delivery.json']['size'] != len(descriptor):
        raise DeliveryError('remote frozen delivery differs')


def verified_remote(remote, delivery, directory, *, draft=False, prerelease=None, readback=True, metadata_only=False):
    validate_delivery(delivery, directory, metadata_only=metadata_only)
    tag = delivery['tag']; info = remote.find(tag) if draft else remote.published(tag)
    assets = remote.assets(info)
    validate_remote_inventory(delivery,info,assets,draft=draft,prerelease=prerelease)
    if remote.reference(tag) != delivery['tag_commit']:
        raise DeliveryError('tag commit differs from frozen delivery')
    with tempfile.TemporaryDirectory(prefix='delivery-verify-') as temporary:
        staged = Path(temporary)
        descriptor = staged / 'delivery.json'
        remote.download(assets['delivery.json'], descriptor, sha(archive.encoded(delivery)))
        if coverage.load(descriptor) != delivery:
            raise DeliveryError('remote frozen delivery differs')
        restored = staged / 'release'; restored.mkdir()
        selections = []
        for name, item in (delivery['files'].items() if readback else ()):
            path = restored.joinpath(*archive.relative(name).parts); path.parent.mkdir(parents=True, exist_ok=True)
            selections.append((item['asset'], path, item['sha256']))
        download_files(remote, assets, selections)
        if readback: release.verify_release(restored)
    remote.unchanged(tag, info, assets, delivery['tag_commit'])
    return info, assets


def upload_files(remote, tag, paths, *, release_info=None):
    """Bound independent payload uploads and join a failed batch before stopping.

    Control descriptors and lifecycle transitions belong to the caller, after
    every payload finishes. A response loss retains the outer mutation's sticky
    uncertainty; queued later batches never launch after the first failure.
    """
    paths = [Path(path) for path in paths]
    if len({path.name.casefold() for path in paths}) != len(paths):
        raise DeliveryError('upload payload names must be distinct')
    with ThreadPoolExecutor(max_workers=4) as pool:
        for start in range(0, len(paths), 4):
            futures = [pool.submit(remote.upload_to, release_info, path) if release_info is not None else
                       pool.submit(remote.upload, tag, path) for path in paths[start:start + 4]]
            for future in futures: future.result()


def download_files(remote, assets, selections, *, _completed=None):
    """Bounded independent immutable transfers; all workers join before return."""
    selections = list(selections)
    destinations = [str(Path(path).absolute()) for _, path, _ in selections]
    if len(destinations) != len(set(destinations)):
        raise DeliveryError('download destinations must be distinct')
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(remote.download, assets[name], path, digest): name
                   for name, path, digest in selections}
        for future in as_completed(futures) if _completed is not None else futures:
            future.result()
            if _completed is not None:
                _completed(futures[future])  # Coordinator only; never a transfer worker.


def _fetch_base_groups(repository, recipes, output, *, transport, binary_only, single,
                       group_store=store):
    if type(binary_only) is not bool: raise DeliveryError('binary-only selection must be boolean')
    if (not isinstance(recipes, (list, tuple)) or not recipes or
            any(not isinstance(recipe, str) for recipe in recipes) or len(set(recipes)) != len(recipes)):
        raise DeliveryError('expected distinct nonempty SDK recipe identities')
    expected = {recipe: group_store.names(recipe) for recipe in recipes}
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise DeliveryError('fetch destination must be new')
    remote = Remote(repository, transport); remote.visible()
    info = remote.published('base')
    if info['draft'] or not info['prerelease'] or info['name'] != 'base':
        raise DeliveryError('base must be a published prerelease')
    assets = remote.assets(info)
    reference = remote.reference('base')
    if any(not set(names) <= assets.keys() for names in expected.values()):
        raise DeliveryError('exact complete dependency group is absent; no cold build fallback')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.base-fetch-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'group'; stage.mkdir()
        groups, selections, remaining, owners = {}, [], {}, {}
        for recipe, names in expected.items():
            group = stage if single else stage / recipe
            if not single: group.mkdir()
            groups[recipe] = group
            binary, source, checksum = names
            selected = (binary, checksum) if binary_only else names
            selections.extend((name, group / name, None) for name in selected)
            remaining[recipe] = len(selected)
            owners.update((name, recipe) for name in selected)
        def verify(recipe):
            group = groups[recipe]
            files = (group_store.verify_binary_group(group, recipe) if binary_only else
                     group_store.verify_group(group, recipe))
            if any(assets[name]['digest'] != 'sha256:' + files[name] for name in expected[recipe]):
                raise DeliveryError('base assets differ from complete checksum inventory')
            return dict(fetched=True, recipe=recipe, files=files,
                        payload='binary' if binary_only else 'complete')
        # A recipe can verify while other recipes still download. Separate
        # bounded pools avoid verification occupying transfer slots or waiting
        # on unfinished files. Both pools join before failed staging is removed.
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = {}
            def downloaded(name):
                recipe = owners[name]
                remaining[recipe] -= 1
                if remaining[recipe] == 0:
                    pending[recipe] = pool.submit(verify, recipe)
            download_files(remote, assets, selections, _completed=downloaded)
            results = {recipe: pending[recipe].result() for recipe in groups}
        # All consumers retain full byte checks; one fresh reconciliation covers
        # the whole immutable snapshot before any output becomes available.
        remote.unchanged('base', info, assets, reference)
        stage.rename(output)
    return results


def fetch_base(repository, recipe, output, *, transport=None, binary_only=False):
    return _fetch_base_groups(repository, [recipe], output, transport=transport,
                              binary_only=binary_only, single=True)[recipe]


def fetch_bases(repository, recipes, output, *, transport=None, binary_only=False):
    """Fetch recipe subdirectories together using one in-memory base inventory."""
    return _fetch_base_groups(repository, recipes, output, transport=transport,
                              binary_only=binary_only, single=False)


def fetch_rust_base(repository, recipe, output, *, transport=None):
    """Fetch and verify the exact complete retained Rust extension group."""
    return _fetch_base_groups(repository, [recipe], output, transport=transport,
                              binary_only=False, single=True, group_store=rust_sdk)[recipe]


def fetch_rust_bases(repository, recipes, output, *, transport=None):
    """Fetch complete Rust recipe subdirectories using one base inventory."""
    return _fetch_base_groups(repository, recipes, output, transport=transport,
                              binary_only=False, single=False, group_store=rust_sdk)


def _base_sdk_slot(binary, group_store):
    """Conservative consumer slot from already verified archive metadata."""
    rust = group_store is rust_sdk
    data, _ = archive.inspect_manifest_archive(binary, 'rust-sdk.json' if rust else 'sdk.json', sdk_archive=not rust)
    kind = data.get('kind')
    if kind not in (('rust-extension',) if rust else ('source-build', 'windows-dependencies', 'retained-upstream')):
        return None
    target = data.get('target', {})
    if not isinstance(target, dict) or any(not isinstance(target.get(key), str) or not target[key] for key in ('system', 'processor', 'triple')):
        return None
    slot = dict(kind=kind, target={key: target[key] for key in ('system', 'processor', 'triple')})
    if kind == 'windows-dependencies':
        toolchain = data.get('external_toolchain', {})
        toolset = toolchain.get('toolset') if isinstance(toolchain, dict) else None
        if target['system'] != 'Windows' or not isinstance(toolset, str) or not toolset: return None
        slot['toolset'] = toolset
        provenance = data.get('provenance', {})
        policy = ('triplet', 'configurations', 'crt_linkage', 'library_linkage', 'lto', 'ports')
        if not isinstance(provenance, dict) or any(key not in provenance for key in policy): return None
        slot['policy'] = {key: provenance[key] for key in policy}
    else:
        host = data.get('host', {})
        if not isinstance(host, dict) or any(not isinstance(host.get(key), str) or not host[key] for key in ('system', 'processor')): return None
        slot['host'] = host
    if kind in ('source-build', 'windows-dependencies'):
        capabilities = data.get('capabilities')
        if (not isinstance(capabilities, list) or not capabilities or
                any(not isinstance(item, str) or not item for item in capabilities)): return None
        slot.update(capabilities=sorted(capabilities), baseline=data.get('baseline'),
                    runtime_host_services=data.get('runtime_host_services', []))
    elif kind == 'retained-upstream':
        if target['system'] != 'Emscripten' or not isinstance(data.get('cache_options'), list): return None
        slot['cache_options'] = data['cache_options']
    else:
        compiler = data.get('compiler', {})
        slot['compiler_host'] = compiler.get('host') if isinstance(compiler, dict) else None
        if not isinstance(slot['compiler_host'], str) or not slot['compiler_host']: return None
    return archive.encoded(slot)


def _retire_base_groups(remote, info, assets, reference, recipe, group, group_store):
    """Verify every removal before deleting exact IDs under the publisher lock."""
    slot = _base_sdk_slot(Path(group) / group_store.names(recipe)[0], group_store)
    binary = group_store.names(recipe)[0]
    if archive.digest(Path(group) / binary) != assets[binary]['digest'][7:]:
        raise DeliveryError('local published SDK changed before base cleanup')
    if slot is None: return {}
    prefix = 'rust-sdk-' if group_store is rust_sdk else 'sdk-'
    pattern = re.compile(re.escape(prefix) + r'([0-9a-f]{64})-(?:binary\.tar\.gz|sources\.tar\.gz|SHA256SUMS)\Z')
    recipes = sorted({match[1] for name in assets if (match := pattern.fullmatch(name)) and match[1] != recipe})
    if len(recipes) > BASE_CLEANUP_GROUP_LIMIT:
        raise DeliveryError('base cleanup exceeds its bounded group inventory; preserve old groups for inspection')
    removed = {}
    for identity in recipes:
        binary, source, checksum = names = group_store.names(identity)
        if not set(names) <= assets.keys(): continue  # Partial groups are never cleanup authority.
        with tempfile.TemporaryDirectory(prefix='base-retire-') as temporary:
            destination = Path(temporary)
            remote.download(assets[binary], destination / binary)
            try:
                if _base_sdk_slot(destination / binary, group_store) != slot: continue
            except (ValueError, tarfile.TarError):
                continue  # Unknown or malformed archived metadata is preserved.
            download_files(remote, assets, [(name, destination / name, None) for name in (source, checksum)])
            try:
                files = group_store.verify_group(destination, identity)
                if any(assets[name]['digest'] != 'sha256:' + files[name] for name in names): continue
            except (ValueError, tarfile.TarError):
                continue
        # Retire the complete-group marker first. Interrupted cleanup cannot
        # leave a checksum advertising archives that no longer exist.
        removed.update((name, assets[name]) for name in (checksum, binary, source))
    return retire_base_assets(remote, info, assets, reference, removed)


def retire_base_assets(remote, info, assets, reference, removed):
    """Delete verified base IDs once, with prompt failure and exact reconciliation."""
    if not removed: return {}
    if any(assets.get(name) != row for name, row in removed.items()):
        raise DeliveryError('base cleanup selection differs from frozen asset inventory')
    transport = remote.transport
    limits = dict(WRITE_HEADROOM=0, MAX_ATTEMPTS=3, REQUEST_DEADLINE=60, COMMAND_TIMEOUT=60)
    previous = {key: getattr(transport, key) for key in limits} if isinstance(transport, GitHub) else {}
    try:
        for key in previous: setattr(transport, key, limits[key])
        remote.unchanged('base', info, assets, reference); remote.not_latest(info)
        expected = dict(assets)
        for name, row in removed.items():
            if remote.change('/releases/assets/' + str(row['id']), method='DELETE') is not None:
                raise DeliveryError('base asset deletion returned an unexpected response')
            del expected[name]
            remote.unchanged('base', info, expected, reference)
        remote.not_latest(info)
        return removed
    finally:
        for key, value in previous.items(): setattr(transport, key, value)


def _publish_base_group(repository, recipe, group, source_commit, *, execute, transport,
                        group_store, operation):
    files = group_store.verify_group(group, recipe)
    if not OID.fullmatch(source_commit):
        raise DeliveryError('complete source commit required')
    result = plan(operation, repository, recipe=recipe, source_commit=source_commit, files=files,
                  lifecycle='prerelease; never Latest; immutable complete group; retire superseded matching SDK slots')
    if not execute:return result
    remote = Remote(repository, transport)
    def act():
        remote.visible(); info = remote.find('base', False)
        before = remote.assets(info) if info else {}
        reference = remote.reference('base') if info else source_commit
        present = set(files) & before.keys()
        if present and present != set(files):
            raise DeliveryError('partial existing dependency group requires reconciliation')
        if info and (info['draft'] or not info['prerelease'] or info['name'] != 'base'):
            raise DeliveryError('existing base has incompatible lifecycle')
        if present:
            # The local complete group was verified above. Existing published
            # immutable assets must match every exact size and SHA-256; their
            # first publication already required complete byte readback.
            if any(before[name]['digest'] != 'sha256:' + digest or
                   before[name]['size'] != (Path(group) / name).stat().st_size
                   for name, digest in files.items()):
                raise DeliveryError('immutable group conflicts: remote asset differs')
            remote.unchanged('base', info, before, reference); remote.not_latest(info)
            return dict(result, execute=True, reused=True)
        if info is None:
            if remote.reference('base', True) is not None:raise DeliveryError('base tag already exists without its release')
            remote.change('/git/refs', body={'ref':'refs/tags/base','sha':source_commit})
            info = remote.info(remote.change('/releases', body={'tag_name':'base','target_commitish':source_commit,
                'name':'base','body':'Complete reusable dependency groups indexed by recipe identity.',
                'draft':True,'prerelease':True,'make_latest':'false'}), 'base')
            if not info['draft'] or not info['prerelease'] or info['name']!='base':
                raise DeliveryError('created base does not match requested draft lifecycle')
            remote.wait_find('base', release_id=info['id'])
        binary, source, checksum = group_store.names(recipe)
        upload_files(remote, 'base', [Path(group) / name for name in (binary, source)], release_info=info)
        remote.upload_to(info, Path(group) / checksum)  # Complete group marker follows joined payloads.
        current = remote.find('base'); assets = remote.assets(current)
        if any(current[key]!=info[key] for key in ('id','name','draft','prerelease')):
            raise DeliveryError('base release identity changed during upload')
        if set(assets) != set(before) | set(files) or any(assets[n] != v for n,v in before.items()):
            raise DeliveryError('base inventory changed unexpectedly')
        with tempfile.TemporaryDirectory(prefix='base-confirm-') as temporary:
            download_files(remote, assets, [(name, Path(temporary) / name, files[name]) for name in files])
            if group_store.verify_group(temporary, recipe) != files:raise DeliveryError('uploaded group differs')
        if group_store.verify_group(group, recipe) != files:raise DeliveryError('local dependency group changed')
        remote.unchanged('base', current, assets, reference)
        if current['draft']:
            remote.change(f'/releases/{current["id"]}', method='PATCH', body={'draft':False,'prerelease':True,'make_latest':'false'})
        final = remote.find('base')
        if (final['id'] != current['id'] or final['name']!='base' or final['draft']
                or not final['prerelease'] or remote.assets(final) != assets):
            raise DeliveryError('base finalization could not be verified')
        remote.not_latest(final)
        if remote.reference('base') != reference:raise DeliveryError('base tag identity changed')
        removed = _retire_base_groups(remote, final, assets, reference, recipe, group, group_store)
        return dict(result, execute=True, reused=False, release_id=final['id'], removed_assets=removed)
    return run_mutation(remote, act)


def publish_base(repository, recipe, group, source_commit, *, execute=False, transport=None):
    return _publish_base_group(repository, recipe, group, source_commit, execute=execute,
                               transport=transport, group_store=store, operation='publish-base')


def publish_rust_base(repository, recipe, group, source_commit, *, execute=False, transport=None):
    """Plan or append an immutable complete retained Rust extension group."""
    return _publish_base_group(repository, recipe, group, source_commit, execute=execute,
                               transport=transport, group_store=rust_sdk, operation='publish-rust-base')


def publish_candidate(repository, tag, directory, source_commit, packager_commit, publication_id,
                      experiment=False, *, execute=False, transport=None):
    delivery = candidate_identity(directory, repository, tag, source_commit, packager_commit, publication_id, experiment)
    result = plan('publish-candidate', repository, delivery=delivery, lifecycle='draft upload, verify every byte, publish prerelease until certified promotion; never Latest')
    if not execute:return result
    body = 'Certification pending. Immutable application assets.'
    if release.verify_metadata(directory).get('packages') is not None:
        body += ('\n\nSigned package repositories are included in this release. '
                 '[Installation instructions](https://github.com/' + repository +
                 '/releases/download/' + tag + '/INSTALL.md). '
                 'The stable repository URL becomes active when this release is promoted to Latest.')
    remote = Remote(repository, transport)
    def act():
        remote.visible()
        if remote.find(tag, False) is not None or remote.reference(tag, True) is not None:
            raise DeliveryError('release or tag already exists; no overwrite or implicit resume')
        remote.change('/git/refs', body={'ref':'refs/tags/'+tag,'sha':delivery['tag_commit']})
        info = remote.info(remote.change('/releases', body={'tag_name':tag,'target_commitish':delivery['tag_commit'],
            'name':'experiment' if experiment else tag,'body':body,
            'draft':True,'prerelease':True,'make_latest':'false'}), tag)
        remote.wait_find(tag, release_id=info['id'])
        upload_files(remote, tag, [Path(directory) / name for name in delivery['files']], release_info=info)
        with tempfile.TemporaryDirectory(prefix='delivery-metadata-') as temporary:
            path=Path(temporary)/'delivery.json';path.write_bytes(archive.encoded(delivery));remote.upload_to(info,path)
        current, assets = verified_remote(remote, delivery, directory, draft=True, prerelease=True, metadata_only=True)
        if current['id'] != info['id']:raise DeliveryError('draft release identity changed')
        remote.change(f'/releases/{info["id"]}', method='PATCH', body={'draft':False,'prerelease':True,'make_latest':'false'})
        final, final_assets = verified_remote(remote, delivery, directory, prerelease=True, readback=False, metadata_only=True)
        if final['id'] != info['id'] or final_assets != assets:raise DeliveryError('publication identity changed')
        remote.not_latest(final)
        return dict(result, execute=True, release_id=final['id'])
    return run_mutation(remote, act)


def retain_reports(reports, retain):
    """Keep every logical report beside one copy of shared physical evidence."""
    report_paths, parents = {}, {}
    for path in reports:
        path = Path(path); report = coverage.load(path); check = valid_name(report['check'])
        if check in report_paths: raise DeliveryError('duplicate evidence check')
        parent = path.parent.resolve(strict=True)
        prefix = parents.setdefault(parent, 'reports/' + check)
        relative = prefix + '/' + valid_name(path.name)
        report_paths[check] = relative; retain(path, relative)
        for name in report['evidence']:
            retain(coverage.local(path.parent, name), prefix + '/' + name)
    return report_paths


def bundle_certificate(directory, delivery, certificate, check_plan, policy, profile, reports, attempt, destination, *, metadata_only=False):
    validate_delivery(delivery, directory, metadata_only=metadata_only)
    manifest = release.verify_metadata(directory) if metadata_only else release.verify_release(directory)
    if not positive(attempt):raise DeliveryError('certificate attempt must be positive')
    certificate = Path(certificate); reports = [Path(p) for p in reports]
    document = coverage.load(certificate)
    frozen = coverage.load(check_plan); rules = coverage.load(policy)
    adoption = document.get('adoption')
    if adoption is not None and (not isinstance(adoption, dict) or adoption.get('attempt') != attempt or
                                 adoption.get('run_id') != document.get('run_id')):
        raise DeliveryError('certificate adoption belongs to another run or attempt')
    expected = certification.certify(Path(directory), manifest, frozen, reports,
                                     rules, profile, delivery['experiment'], adoption=adoption)
    if document != expected:raise DeliveryError('certificate does not match current complete policy and evidence')
    run_id = document['run_id']
    if not isinstance(run_id, str) or not coverage.NAME.fullmatch(run_id):raise DeliveryError('invalid certification run')
    stem = valid_name(f'certification-{run_id}-attempt-{attempt}')
    tree = Path(destination) / 'contents'; tree.mkdir()
    retained = {}
    def retain(source, name):
        source = Path(source)
        if source.is_symlink() or not source.is_file():raise DeliveryError('evidence must be an ordinary file')
        current = source.stat(); identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        digest = archive.digest(source)
        target = tree.joinpath(*archive.relative(name).parts)
        if name in retained:
            if retained[name] != (source.resolve(), identity, digest) or archive.digest(target) != digest:
                raise DeliveryError('shared evidence changed during retention')
            return
        target.parent.mkdir(parents=True,exist_ok=True)
        with source.open('rb') as incoming, target.open('xb') as outgoing:shutil.copyfileobj(incoming,outgoing)
        after = source.stat()
        if (identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or
                archive.digest(source) != digest or archive.digest(target) != digest):
            raise DeliveryError('local evidence changed during retention')
        retained[name] = (source.resolve(), identity, digest)
    for source,name in ((certificate,'certificate.json'),(check_plan,'plan.json'),(policy,'policy.json')):retain(source,name)
    report_paths = retain_reports(reports, retain)
    copied_reports = [tree / name for name in report_paths.values()]
    copied_certificate = coverage.load(tree / 'certificate.json')
    if (copied_certificate != document or coverage.load(tree / 'plan.json') != frozen
            or coverage.load(tree / 'policy.json') != rules
            or certification.certify(Path(directory), manifest, frozen,
                                     copied_reports, rules, profile, delivery['experiment'],
                                     adoption=copied_certificate.get('adoption')) != document):
        raise DeliveryError('certificate evidence changed while creating the complete bundle')
    metadata={'schema_version':1,'delivery_sha256':sha(archive.encoded(delivery)), 'run_id':run_id,
              'attempt':attempt,'profile':profile,'reports':report_paths,
              'report_order':list(report_paths),'files':archive.file_inventory(tree)}
    (tree/'bundle.json').write_bytes(archive.encoded(metadata))
    bundled=Path(destination)/(stem+'.tar.gz');archive.archive_tree(tree,bundled)
    envelope={'schema_version':1,'delivery_sha256':metadata['delivery_sha256'],'run_id':run_id,'attempt':attempt,
              'bundle':bundled.name,'bundle_sha256':archive.digest(bundled),
              'certificate_sha256':archive.digest(tree/'certificate.json'),'subject':document['subject'],
              'status':document['status'],'eligible_for_promotion':document['eligible_for_promotion'],
              'experiment':document['experiment']}
    path=Path(destination)/(stem+'.json');path.write_bytes(archive.encoded(envelope))
    return envelope,path,bundled


def attach_certificate(repository, tag, directory, delivery, certificate, check_plan, policy, profile,
                       reports, attempt, *, execute=False, transport=None, metadata_only=False):
    location(repository,tag)
    if (repository,tag)!=(delivery.get('repository'),delivery.get('tag')):raise DeliveryError('delivery belongs to another location')
    with tempfile.TemporaryDirectory(prefix='certificate-package-') as temporary:
        envelope,report,bundle=bundle_certificate(directory,delivery,certificate,check_plan,policy,profile,reports,attempt,temporary,metadata_only=metadata_only)
        files={p.name:archive.digest(p) for p in (report,bundle)}
        result=plan('attach-certificate',repository,tag=tag,files=files,certificate=envelope,
                    lifecycle='append one immutable attempt; preserve every previous asset; no promotion')
        if not execute:return result
        remote=Remote(repository,transport)
        def act():
            remote.visible();info,before=verified_remote(remote,delivery,directory,readback=not metadata_only,metadata_only=metadata_only)
            if set(files)&before.keys():raise DeliveryError('certificate attempt already exists; inspect it, never overwrite')
            remote.upload_to(info,bundle);remote.upload_to(info,report)
            current=remote.by_id(info['id'],tag);after=remote.assets(current)
            if (any(current[key]!=info[key] for key in ('id','tag_name','name','draft','prerelease')) or
                    remote.reference(tag)!=delivery['tag_commit'] or set(after)!=set(before)|set(files) or any(after[n]!=v for n,v in before.items())):
                raise DeliveryError('certificate attachment changed lifecycle or an existing asset')
            with tempfile.TemporaryDirectory(prefix='certificate-confirm-') as check:
                for name,digest in files.items():remote.download(after[name],Path(check)/name,digest)
            remote.unchanged(tag,current,after,delivery['tag_commit'])
            return dict(result,execute=True,release_id=info['id'])
        return run_mutation(remote,act)


def verify_certificate(remote, assets, delivery, directory, policy, profile, run_id, attempt, certificate_sha256, *, metadata_only=False):
    if not positive(attempt) or not coverage.NAME.fullmatch(run_id) or not SHA.fullmatch(certificate_sha256):
        raise DeliveryError('exact certificate run, attempt and digest are required')
    stem=valid_name(f'certification-{run_id}-attempt-{attempt}')
    names={stem+'.json',stem+'.tar.gz'}
    if not names<=assets.keys():raise DeliveryError('complete certificate attempt is missing')
    with tempfile.TemporaryDirectory(prefix='certificate-review-') as temporary:
        temporary=Path(temporary);path=temporary/(stem+'.json');remote.download(assets[path.name],path)
        envelope=coverage.load(path)
        expected_fields={'schema_version','delivery_sha256','run_id','attempt','bundle','bundle_sha256',
                         'certificate_sha256','subject','status','eligible_for_promotion','experiment'}
        coverage.fields(envelope,expected_fields)
        if (envelope['schema_version']!=1 or envelope['delivery_sha256']!=sha(archive.encoded(delivery))
                or envelope['run_id']!=run_id or envelope['attempt']!=attempt
                or envelope['certificate_sha256']!=certificate_sha256 or envelope['bundle']!=stem+'.tar.gz'
                or not isinstance(envelope['bundle_sha256'],str) or not SHA.fullmatch(envelope['bundle_sha256'])):
            raise DeliveryError('certificate attempt is stale or belongs to another delivery')
        bundled=temporary/envelope['bundle'];remote.download(assets[bundled.name],bundled,envelope['bundle_sha256'])
        tree=archive.extract(bundled,temporary/'contents',max_bytes=4*1024**3)
        metadata=coverage.load(tree/'bundle.json')
        coverage.fields(metadata,{'schema_version','delivery_sha256','run_id','attempt','profile','reports','report_order','files'})
        if (metadata['schema_version']!=1 or metadata['delivery_sha256']!=envelope['delivery_sha256']
                or metadata['run_id']!=run_id or metadata['attempt']!=attempt or metadata['profile']!=profile):
            raise DeliveryError('bundled evidence identity differs')
        archive.verify_inventory(tree,metadata['files'],exclude=('bundle.json',))
        if archive.digest(tree/'certificate.json')!=certificate_sha256:raise DeliveryError('certificate bytes changed')
        rules=coverage.load(policy)
        if coverage.load(tree/'policy.json')!=rules:raise DeliveryError('current promotion policy differs from tested policy')
        reports=[]
        if not isinstance(metadata['reports'],dict) or not metadata['reports']:raise DeliveryError('complete reports required')
        if (not isinstance(metadata['report_order'],list) or len(set(metadata['report_order']))!=len(metadata['report_order'])
                or set(metadata['report_order'])!=set(metadata['reports'])):
            raise DeliveryError('complete original report order required')
        for check in metadata['report_order']:
            name=metadata['reports'][check]
            valid_name(check);path=archive.checked_file(tree,name)
            if coverage.load(path)['check']!=check:raise DeliveryError('report identity mismatch')
            reports.append(path)
        # Preserve original caller order when comparing the certifier's report list.
        frozen=coverage.load(tree/'plan.json')
        saved=coverage.load(tree/'certificate.json')
        adoption=saved.get('adoption')
        if adoption is not None and (not isinstance(adoption,dict) or adoption.get('attempt')!=attempt or
                                     adoption.get('run_id')!=run_id):
            raise DeliveryError('certificate adoption belongs to another run or attempt')
        result=certification.certify(Path(directory),release.verify_metadata(directory) if metadata_only else release.verify_release(directory),frozen,reports,rules,profile,False,adoption=adoption)
        if result!=saved or result['subject']!=envelope['subject']:
            raise DeliveryError('saved certificate does not reproduce from complete retained evidence')
        if (result['status'] not in ('passed','passed_with_warnings') or result['eligible_for_promotion'] is not True
                or result['experiment'] is not False or envelope['eligible_for_promotion'] is not True
                or envelope['experiment'] is not False or envelope['status']!=result['status']):
            raise DeliveryError('certificate does not qualify this ordinary release')
        return {'certificate_sha256':certificate_sha256,'run_id':run_id,'attempt':attempt,'status':result['status']}


def promote(repository,tag,directory,delivery,policy,profile,run_id,attempt,certificate_sha256,*,execute=False,transport=None,metadata_only=False):
    location(repository,tag);validate_delivery(delivery,directory,metadata_only=metadata_only)
    if (repository,tag)!=(delivery['repository'],delivery['tag']) or delivery['experiment'] or tag=='base':
        raise DeliveryError('only this ordinary application release can be promoted')
    if not positive(attempt) or not coverage.NAME.fullmatch(run_id) or not SHA.fullmatch(certificate_sha256):
        raise DeliveryError('exact certificate run, attempt and digest are required')
    certification.requirements(coverage.load(policy),profile)
    result=plan('promote',repository,tag=tag,delivery_sha256=sha(archive.encoded(delivery)),
                policy_sha256=archive.digest(policy),profile=profile,run_id=run_id,attempt=attempt,
                certificate_sha256=certificate_sha256,lifecycle='verify exact certificate and every remote asset, change Latest, verify pointer')
    if not execute:return result
    remote=Remote(repository,transport)
    def act():
        remote.visible();info,assets=verified_remote(remote,delivery,directory,readback=not metadata_only,metadata_only=metadata_only)
        evidence=verify_certificate(remote,assets,delivery,directory,policy,profile,run_id,attempt,certificate_sha256,metadata_only=metadata_only)
        # Reconcile IDs, sizes, hashes and tag after certificate reproduction;
        # this operation already downloaded and verified the immutable bytes.
        info=remote.unchanged(tag,info,assets,delivery['tag_commit'])
        if archive.digest(policy)!=result['policy_sha256']:raise DeliveryError('promotion policy changed')
        body=info.get('body')
        if body and body.startswith('Certification pending.'):
            body=body.replace('Certification pending.','Certification complete.',1)
        remote.change(f'/releases/{info["id"]}',method='PATCH',body={'draft':False,'prerelease':False,'make_latest':'true','body':body})
        final=remote.by_id(info['id'],tag);after=remote.assets(final)
        if (final['draft'] or final['prerelease'] or final['name']!=info['name'] or final.get('body')!=body or after!=assets or
                remote.reference(tag)!=delivery['tag_commit']):raise DeliveryError('promoted lifecycle or assets changed')
        latest=remote.transport.json(remote.base+'/releases/latest')
        remote.info(latest,tag)
        if latest['id']!=info['id'] or latest['draft'] or latest['prerelease']:
            raise DeliveryError('Latest pointer does not identify the exact certified release')
        return dict(result,execute=True,release_id=info['id'],latest=True,evidence=evidence)
    return run_mutation(remote,act)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('fetch-base','fetch-rust-base','publish-base',
        'publish-rust-base','publish-candidate','attach-certificate','promote'))
    parser.add_argument('--input',default='-',help='strict JSON request file or stdin')
    parser.add_argument('--execute',action='store_true',help='explicitly execute planned remote mutations')
    args=parser.parse_args(argv)
    request=parse(sys.stdin.buffer.read() if args.input=='-' else Path(args.input).read_bytes())
    if not isinstance(request,dict) or 'execute' in request or 'transport' in request:
        raise DeliveryError('request must be an object; execution is a separate explicit CLI option')
    operation=globals()[args.operation.replace('-','_')]
    fetching=args.operation in ('fetch-base','fetch-rust-base')
    result=operation(**request,**({} if fetching else {'execute':args.execute}))
    try:
        print(json.dumps(result,sort_keys=True,indent=2),flush=True)
    except (OSError,ValueError) as error:
        if args.execute and not fetching:
            raise DeliveryError('execution completed but its receipt could not be delivered; reconcile remote before retry',True) from error
        raise
    return 0


if __name__=='__main__':
    enable_metrics()
    try:sys.exit(main())
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as error:
        print(json.dumps({'ok':False,'uncertain':getattr(error,'uncertain',False),
                          'error':str(error),'action':'reconcile remote before retry' if getattr(error,'uncertain',False)
                          else 'correct the request or inspect read-only state'}),file=sys.stderr)
        sys.exit(1)
