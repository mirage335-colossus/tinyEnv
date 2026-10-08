"""Bounded, opt-in research with explicit interactive or curated scope.

Returned source material is inert, untrusted evidence. This module never follows
document links, invokes a model, evaluates content, or enables provider tools.
Network access is disabled until both policy and the individual call opt in.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
import zlib
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class ResearchError(ValueError):
    """A source, budget, or network policy rejected an operation."""


@dataclass(frozen=True)
class ResearchPolicy:
    network_enabled: bool = False
    max_queries: int = 2
    max_results: int = 3
    max_response_bytes: int = 524288
    timeout_seconds: float = 15.0
    max_local_files: int = 256
    max_local_bytes: int = 16777216
    max_local_results: int = 50
    max_local_entries: int = 4096
    max_index_entries: int = 1000
    scope: str = "curated"

    def __post_init__(self) -> None:
        for name in ("max_queries", "max_results", "max_response_bytes", "max_local_files",
                     "max_local_bytes", "max_local_results", "max_local_entries", "max_index_entries"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ResearchError(name + " must be a positive integer")
        if not isinstance(self.network_enabled, bool):
            raise ResearchError("network_enabled must be a boolean")
        _scope(self.scope)
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(self.timeout_seconds, bool) \
                or not 0 < self.timeout_seconds <= 60:
            raise ResearchError("timeout_seconds must be between zero and 60")


@dataclass(frozen=True)
class ResearchSource:
    id: str
    title: str
    url: str
    text: str
    kind: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransportResponse:
    status: int
    url: str
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


def _scope(scope: str) -> str:
    if not isinstance(scope, str) or scope not in {"curated", "interactive"}:
        raise ResearchError("research scope must be curated or interactive")
    return scope


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    # IPv4-mapped/tunneled addresses must not conceal a private destination.
    mapped = getattr(address, "ipv4_mapped", None)
    six_to_four = getattr(address, "sixtofour", None)
    teredo = getattr(address, "teredo", None)
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and (mapped is None or mapped.is_global)
            and (six_to_four is None or six_to_four.is_global)
            and (teredo is None or all(item.is_global for item in teredo)))


def validate_source_url(url: str, *, scope: str = "curated") -> str:
    """Validate a document URL; search API endpoints are not document URLs."""
    scope = _scope(scope)
    if not isinstance(url, str) or not url or len(url) > 2048 \
            or re.search(r"[\x00-\x20\x7f\\]", url):
        raise ResearchError("invalid source URL")
    _utf8(url)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ResearchError("invalid source URL") from exc
    if scope == "interactive":
        if parts.scheme != "https" or not parts.hostname or parts.username is not None \
                or parts.password is not None or port not in (None, 443):
            raise ResearchError("only credential-free public HTTPS URLs are allowed")
        host = parts.hostname
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            if not _public_address(str(literal)):
                raise ResearchError("source destination must be public")
            host = "[" + str(literal) + "]" if literal.version == 6 else str(literal)
        else:
            try:
                host = host.encode("idna").decode("ascii").lower()
            except UnicodeError as exc:
                raise ResearchError("invalid source hostname") from exc
            if (len(host) > 253 or host.endswith(".") or "." not in host
                    or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                           for part in host.split("."))
                    or host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))
                    or re.fullmatch(r"[0-9.]+", host)):
                raise ResearchError("source hostname must name a public destination")
        for component in (parts.path, parts.query):
            if re.search(r"%(?![0-9a-fA-F]{2})", component):
                raise ResearchError("invalid percent encoding in source URL")
            try:
                decoded = unquote(component, errors="strict")
            except UnicodeError as exc:
                raise ResearchError("invalid Unicode source URL") from exc
            if re.search(r"[\x00-\x1f\x7f\\]", decoded):
                raise ResearchError("invalid source URL controls")
        if any(item in (".", "..") for item in unquote(parts.path).split("/")):
            raise ResearchError("invalid document path")
        return urlunsplit(("https", host, quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                           quote(parts.query, safe="/%?:@!$&'()*+,;=-._~"), ""))
    if parts.scheme != "https" or parts.username is not None or parts.password is not None \
            or port is not None or parts.query or parts.netloc != parts.hostname:
        raise ResearchError("only credential-free HTTPS document URLs are allowed")
    if re.search(r"%(?![0-9a-fA-F]{2})", parts.path):
        raise ResearchError("invalid percent encoding in document path")
    try:
        path = unquote(parts.path, errors="strict")
    except UnicodeError as exc:
        raise ResearchError("invalid Unicode document path") from exc
    if re.search(r"[\x00-\x20\x7f\\]", path) or any(item in (".", "..") for item in path.split("/")):
        raise ResearchError("invalid document path")
    if parts.hostname == "en.wikipedia.org":
        # Exclude namespace pages, API endpoints and external link redirects.
        title = path[len("/wiki/"):] if path.startswith("/wiki/") else ""
        if not title or ":" in title or "?" in title or "#" in title:
            raise ResearchError("only English Wikipedia article pages are allowed")
    elif parts.hostname == "stackoverflow.com":
        if not re.fullmatch(r"/questions/[1-9][0-9]*(?:/[A-Za-z0-9_-]+)?/?", path):
            raise ResearchError("only Stack Overflow question pages are allowed")
    elif parts.hostname == "man7.org":
        if not re.fullmatch(r"/linux/man-pages/man[1-9][a-z]*/[A-Za-z0-9_.+-]+\.[1-9][a-z]*\.html", path):
            raise ResearchError("only Linux manual pages are allowed")
    else:
        raise ResearchError("source host is not approved")
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%()_-.", encoding="utf-8"), "", ""))


class _TextExtractor(HTMLParser):
    """Extract displayed text without retaining executable or external links."""

    _ignored = {"script", "style", "noscript", "iframe", "object", "nav", "form", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.hidden: List[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._ignored:
            self.hidden.append(tag)
        if not self.hidden and tag in {"p", "div", "br", "li", "pre", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if not self.hidden and tag in {"p", "div", "li", "pre", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[\t \r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n(?:\s*\n)*", "\n\n", text)
        return text.strip()


def _plain_html(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        raise ResearchError("redirects are disabled")


def _http_get(url: str, *, max_bytes: int, timeout: float) -> TransportResponse:
    # No environment proxy, authentication handler, cookies, or Referer header.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    request = Request(url, headers={"Accept": "application/json,text/html,text/plain",
                                    "User-Agent": "tinyEnv-workbench/1.0 (manual bounded research)"})
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            return TransportResponse(response.status, response.geturl(), body, dict(response.headers))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ResearchError("research request failed: " + type(exc).__name__) from exc


def _public_addresses(host: str) -> List[Any]:
    """Resolve once and reject a mixed public/private response before connecting."""
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ResearchError("research destination lookup failed") from exc
    if not answers or any(family not in (socket.AF_INET, socket.AF_INET6)
                          or not _public_address(address[0])
                          for family, _, _, _, address in answers):
        raise ResearchError("research destination must resolve only to public addresses")
    return answers


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a checked address while verifying TLS against the URL hostname."""

    def __init__(self, host: str, answer: Any, timeout: float) -> None:
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self._answer = answer

    def connect(self) -> None:
        family, socktype, protocol, _, address = self._answer
        connection = socket.socket(family, socktype, protocol)
        try:
            connection.settimeout(self.timeout)
            connection.connect(address)
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except BaseException:
            connection.close()
            raise


def _public_http_get(url: str, *, max_bytes: int, timeout: float) -> TransportResponse:
    """No proxy, cookies, redirects, credentials, or second DNS lookup."""
    url = validate_source_url(url, scope="interactive")
    parts = urlsplit(url)
    answer = _public_addresses(parts.hostname)[0]
    connection = _PinnedHTTPSConnection(parts.hostname, answer, timeout)
    try:
        target = urlunsplit(("", "", parts.path, parts.query, ""))
        connection.request("GET", target, headers={
            "Accept": "application/json,text/html,text/plain", "Accept-Encoding": "identity",
            "User-Agent": "tinyEnv-workbench/1.0 (bounded user research)"})
        response = connection.getresponse()
        return TransportResponse(response.status, url, response.read(max_bytes + 1),
                                 dict(response.getheaders()))
    except (http.client.HTTPException, TimeoutError, OSError) as exc:
        raise ResearchError("research request failed: " + type(exc).__name__) from exc
    finally:
        connection.close()


class _WebResults(HTMLParser):
    """Read DuckDuckGo HTML result titles/snippets, without following links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: List[Dict[str, str]] = []
        self.current: Optional[Dict[str, str]] = None
        self.capture: Optional[str] = None
        self.capture_tag: Optional[str] = None
        self.depth = 0
        self.hidden: List[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        attributes = dict(attrs)
        if tag in {"script", "style", "noscript", "iframe", "object"}:
            self.hidden.append(tag)
        if self.hidden:
            return
        classes = set((attributes.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            if self.current is not None:
                self.entries.append(self.current)
            self.current = {"url": attributes.get("href") or "", "title": "", "text": ""}
            self.capture, self.capture_tag, self.depth = "title", tag, 1
        elif self.current is not None and "result__snippet" in classes:
            self.capture, self.capture_tag, self.depth = "text", tag, 1
        elif self.capture is not None and tag == self.capture_tag:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if self.capture is not None and tag == self.capture_tag:
            self.depth -= 1
            if not self.depth:
                self.capture = self.capture_tag = None

    def handle_data(self, data: str) -> None:
        if not self.hidden and self.current is not None and self.capture is not None:
            self.current[self.capture] += data

    def close(self) -> None:
        super().close()
        if self.current is not None:
            self.entries.append(self.current)
            self.current = None


def _web_result_url(value: str) -> str:
    if value.startswith("//"):
        value = "https:" + value
    parts = urlsplit(value)
    if parts.hostname in {"duckduckgo.com", "html.duckduckgo.com"} and parts.path == "/l/":
        destinations = parse_qs(parts.query).get("uddg", [])
        if len(destinations) != 1:
            raise ResearchError("invalid search result destination")
        value = destinations[0]
    return validate_source_url(value, scope="interactive")


def _query(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256 \
            or re.search(r"[\x00-\x1f\x7f]", value):
        raise ResearchError("query must be 1 to 256 characters without controls")
    _utf8(value)
    return value.strip()


def _utf8(value: str) -> bytes:
    try:
        return value.encode("utf-8")
    except UnicodeError as exc:
        raise ResearchError("source text must contain valid Unicode") from exc


def _source(title: str, url: str, text: str, kind: str,
            metadata: Optional[Mapping[str, Any]] = None) -> ResearchSource:
    _utf8(title)
    _utf8(url)
    provenance = {"untrusted": True, "instruction_authority": False,
                  "no_links_followed": True, "sha256": hashlib.sha256(_utf8(text)).hexdigest()}
    provenance.update(metadata or {})
    identifier = hashlib.sha256(_utf8(url + "\n" + text)).hexdigest()[:20]
    return ResearchSource(identifier, title[:512], url, text, kind, provenance)


class ResearchService:
    """One bounded research run; a new service starts a new explicit budget."""

    def __init__(self, policy: Optional[ResearchPolicy] = None,
                 transport: Optional[Callable[..., Any]] = None) -> None:
        self.policy = policy or ResearchPolicy()
        self.transport = transport or (_public_http_get if self.policy.scope == "interactive" else _http_get)
        self._queries = 0
        self._results = 0
        self._requests = 0

    def usage(self) -> Dict[str, Any]:
        return {"queries": self._queries, "results": self._results, "requests": self._requests,
                "max_queries": self.policy.max_queries, "max_results": self.policy.max_results,
                "network_enabled": self.policy.network_enabled, "scope": self.policy.scope}

    def _manual(self, manual: bool) -> None:
        if manual is not True or not self.policy.network_enabled:
            raise ResearchError("network research is disabled; enable it and explicitly request a manual call")
        if self._results >= self.policy.max_results:
            raise ResearchError("research result budget exhausted")

    def _request(self, url: str, *, api: bool = False) -> TransportResponse:
        if api:
            parts = urlsplit(url)
            endpoints = {
                    ("https", "en.wikipedia.org", "/w/api.php"),
                    ("https", "api.stackexchange.com", "/2.3/search/advanced")}
            if self.policy.scope == "interactive":
                endpoints.add(("https", "html.duckduckgo.com", "/html/"))
            if (parts.scheme, parts.netloc, parts.path) not in endpoints:
                raise ResearchError("unapproved search endpoint")
        else:
            validate_source_url(url, scope=self.policy.scope)
        if self._requests >= self.policy.max_queries + self.policy.max_results:
            raise ResearchError("research request budget exhausted")
        # Charge before dispatch; failed requests cannot bypass the query budget.
        self._requests += 1
        try:
            response = self.transport(url, max_bytes=self.policy.max_response_bytes,
                                      timeout=self.policy.timeout_seconds)
        except ResearchError:
            raise
        except Exception as exc:
            raise ResearchError("research transport failed: " + type(exc).__name__) from exc
        if isinstance(response, Mapping):
            response = TransportResponse(response.get("status", 200), response.get("url", url),
                                         response.get("body", b""), response.get("headers", {}))
        if not isinstance(response, TransportResponse) or not isinstance(response.body, bytes):
            raise ResearchError("invalid research transport response")
        if response.url != url or not isinstance(response.status, int) or not 200 <= response.status < 300:
            raise ResearchError("redirected or unsuccessful research response")
        if len(response.body) > self.policy.max_response_bytes:
            raise ResearchError("research response exceeds byte budget")
        headers = {str(key).lower(): str(value).lower() for key, value in response.headers.items()}
        encoding = headers.get("content-encoding", "identity").strip()
        if encoding == "gzip":
            response = TransportResponse(response.status, response.url,
                                         _expand_gzip(response.body, self.policy.max_response_bytes), response.headers)
        elif encoding not in {"identity", ""}:
            raise ResearchError("unsupported research response encoding")
        return response

    @staticmethod
    def _json(response: TransportResponse) -> Mapping[str, Any]:
        try:
            result = json.loads(response.body.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ResearchError("invalid research JSON response") from exc
        if not isinstance(result, Mapping):
            raise ResearchError("invalid research JSON object")
        if "error" in result or "error_id" in result:
            raise ResearchError("research search provider returned an error")
        if result.get("backoff"):
            raise ResearchError("research provider requested backoff; automatic retries are disabled")
        return result

    def search(self, query: str, source: str = "wikipedia", *, manual: bool = False) -> List[ResearchSource]:
        query = _query(query)
        self._search_source(source)
        self._manual(manual)
        if self._queries >= self.policy.max_queries:
            raise ResearchError("research query budget exhausted")
        self._queries += 1
        remaining = self.policy.max_results - self._results
        if source == "web":
            url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
            response = self._request(url, api=True)
            headers = {str(key).lower(): str(value).lower() for key, value in response.headers.items()}
            if headers.get("content-type", "text/html").split(";", 1)[0].strip() \
                    not in {"text/html", "application/xhtml+xml"}:
                raise ResearchError("unsupported web search response type")
            try:
                content = response.body.decode("utf-8")
            except UnicodeError as exc:
                raise ResearchError("web search response must be UTF-8") from exc
            if re.search(r"(?:challenge-form|anomaly-modal)", content, re.IGNORECASE):
                raise ResearchError("web search provider requested a browser challenge")
            parser = _WebResults()
            parser.feed(content)
            parser.close()
            results, seen = [], set()
            for entry in parser.entries:
                if len(results) >= remaining:
                    break
                try:
                    candidate = _web_result_url(entry["url"])
                except (ResearchError, ValueError):
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                title = " ".join(entry["title"].split())
                if not title:
                    continue
                results.append(_source(title, candidate, " ".join(entry["text"].split()), "web",
                                       {"query": query, "search_excerpt": True,
                                        "search_provider": "duckduckgo-html"}))
            self._results += len(results)
            return results
        if source == "wikipedia":
            url = "https://en.wikipedia.org/w/api.php?" + urlencode({
                "action": "query", "list": "search", "srsearch": query,
                "srnamespace": 0, "srlimit": min(remaining, 50), "format": "json",
                "formatversion": 2})
            payload = self._json(self._request(url, api=True))
            group = payload.get("query", {})
            entries = group.get("search", []) if isinstance(group, Mapping) else []
        else:
            url = "https://api.stackexchange.com/2.3/search/advanced?" + urlencode({
                "site": "stackoverflow", "q": query, "pagesize": min(remaining, 100),
                "order": "desc", "sort": "relevance", "filter": "withbody"})
            payload = self._json(self._request(url, api=True))
            entries = payload.get("items", [])
        if not isinstance(entries, list):
            raise ResearchError("invalid research search results")
        results: List[ResearchSource] = []
        for entry in entries[:remaining]:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("title"), str):
                raise ResearchError("invalid research search entry")
            title = entry["title"]
            _utf8(title)
            if source == "wikipedia":
                candidate = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="()_-.")
                body = entry.get("snippet", "")
            else:
                candidate = entry.get("link", "")
                body = entry.get("body", "")
            candidate = validate_source_url(candidate)
            if not isinstance(body, str):
                raise ResearchError("invalid research search text")
            results.append(_source(_plain_html(title), candidate, _plain_html(body), source,
                                   {"query": query, "search_excerpt": source == "wikipedia"}))
        self._results += len(results)
        return results

    def _search_source(self, source: str) -> None:
        supported = {"wikipedia", "stackoverflow"}
        if self.policy.scope == "interactive":
            supported.add("web")
        if not isinstance(source, str) or source not in supported:
            raise ResearchError("research source is outside the selected scope")

    def fetch(self, url: str, *, manual: bool = False) -> ResearchSource:
        url = validate_source_url(url, scope=self.policy.scope)
        self._manual(manual)
        response = self._request(url)
        try:
            content = response.body.decode("utf-8")
        except UnicodeError as exc:
            raise ResearchError("research document must be UTF-8") from exc
        headers = {str(k).lower(): str(v).lower() for k, v in response.headers.items()}
        content_type = headers.get("content-type", "text/html").split(";", 1)[0]
        if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
            raise ResearchError("unsupported research document type")
        text = content if content_type == "text/plain" else _plain_html(content)
        if not text:
            raise ResearchError("research document is empty")
        kind = {"en.wikipedia.org": "wikipedia", "stackoverflow.com": "stackoverflow",
                "man7.org": "linux-man"}.get(urlsplit(url).hostname, "web")
        self._results += 1
        return _source(unquote(urlsplit(url).path.rsplit("/", 1)[-1]).replace("_", " "), url, text, kind)

    def research(self, queries: Sequence[str], source: str = "wikipedia", *,
                 manual: bool = False) -> Dict[str, Any]:
        """Execute only the supplied queries; no content can schedule more work."""
        if isinstance(queries, (str, bytes)) or not isinstance(queries, Sequence):
            raise ResearchError("queries must be an explicit list")
        if len(queries) > self.policy.max_queries - self._queries:
            raise ResearchError("query list exceeds research budget")
        queries = [_query(query) for query in queries]
        self._search_source(source)
        if queries:
            self._manual(manual)
        results: List[ResearchSource] = []
        start_queries = self._queries
        for query in queries:
            if self._results >= self.policy.max_results:
                break
            results.extend(self.search(query, source=source, manual=manual))
        return {"sources": [item.to_dict() for item in results], "usage": self.usage(),
                "all_queries_run": self._queries - start_queries == len(queries)}

    def search_local(self, query: str, paths: Iterable[Any] = (), *,
                     kiwix_index: Optional[Any] = None, limit: int = 3) -> List[ResearchSource]:
        """Search explicitly selected text/man files or a local JSON Kiwix export.

        The Kiwix index is schema 1: ``{"schema_version":1,"entries":[
        {"title":"...","article":"...","text":"..."}]}``. Remote URLs,
        link crawling and automatic archive retrieval are deliberately absent.
        """
        query = _query(query)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.policy.max_local_results:
            raise ResearchError("local result limit exceeds policy")
        if isinstance(paths, (str, bytes, Path)) or not isinstance(paths, Iterable):
            raise ResearchError("paths must be an explicit list")
        sources: List[ResearchSource] = []
        total = 0
        files: List[Path] = []
        entries_seen = [0]
        for selection_number, selected in enumerate(paths):
            if selection_number >= self.policy.max_local_files:
                raise ResearchError("local selection exceeds file budget")
            try:
                path = Path(selected).expanduser().absolute()
            except (TypeError, ValueError) as exc:
                raise ResearchError("invalid local source path") from exc
            if path.is_symlink() or not path.exists():
                raise ResearchError("local source must exist and cannot be a symlink")
            if path.is_dir():
                files.extend(_discover_local(path, self.policy, entries_seen))
            elif path.is_file():
                files.append(path)
            else:
                raise ResearchError("local source must be a regular file or directory")
        if len(files) > self.policy.max_local_files:
            raise ResearchError("local file scan exceeds budget")
        seen = set()
        for path in files:
            if str(path) in seen:
                continue
            seen.add(str(path))
            data = _read_local(path, min(self.policy.max_response_bytes,
                                         self.policy.max_local_bytes - total))
            total += len(data)
            try:
                text = data.decode("utf-8")
            except UnicodeError:
                continue  # Binary local files are not text evidence.
            if "\x00" in text:
                continue
            sources.append(_source(path.name, path.as_uri(), text, "local-man" if _is_man(path) else "local",
                                   {"local_path": str(path)}))
        if kiwix_index is not None:
            try:
                path = Path(kiwix_index).expanduser().absolute()
            except (TypeError, ValueError) as exc:
                raise ResearchError("invalid offline Kiwix path") from exc
            data = _read_local(path, min(self.policy.max_local_bytes - total, 4194304))
            try:
                index = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise ResearchError("invalid offline Kiwix index") from exc
            if not isinstance(index, Mapping) or index.get("schema_version") != 1 \
                    or not isinstance(index.get("entries"), list):
                raise ResearchError("offline Kiwix index requires schema_version 1 and entries")
            if len(index["entries"]) > self.policy.max_index_entries:
                raise ResearchError("offline Kiwix index exceeds entry budget")
            for number, entry in enumerate(index["entries"]):
                if not isinstance(entry, Mapping) or any(not isinstance(entry.get(key), str)
                                                         for key in ("title", "text")):
                    raise ResearchError("invalid offline Kiwix entry")
                article = entry.get("article", str(number))
                if not isinstance(article, str) or re.search(r"[\x00-\x1f\x7f]", article):
                    raise ResearchError("invalid offline Kiwix article identity")
                _utf8(article)
                if "url" in entry or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", article):
                    raise ResearchError("Kiwix index must contain local article identities only")
                sources.append(_source(entry["title"], "kiwix-local:" + quote(str(path), safe="/") + "#" + quote(article, safe=""),
                                       entry["text"], "kiwix-local", {"index_path": str(path), "article": article}))
        terms = set(re.findall(r"[\w.+-]+", query.casefold()))
        ranked = []
        for source in sources:
            words = set(re.findall(r"[\w.+-]+", (source.title + " " + source.text).casefold()))
            score = len(terms & words)
            if score:
                ranked.append((score, source))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].url))
        return [item for _, item in ranked[:limit]]


def _is_man(path: Path) -> bool:
    return bool(re.search(r"\.[1-9][a-z]*(?:\.gz)?$", path.name))


def _expand_gzip(data: bytes, limit: int) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as archive:
            result = archive.read(limit + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise ResearchError("invalid compressed source") from exc
    if len(result) > limit:
        raise ResearchError("expanded source exceeds byte budget")
    return result


def _open_local(path: Path, *, directory: bool = False) -> int:
    """Use component-wise no-follow opens where POSIX supplies that guarantee.

    Other hosts reject visible symlinks and bind file identity, but do not claim
    resistance to adversarial ancestor replacement during their native open.
    """
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"):
        directory_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
        parent = os.open(path.anchor or "/", directory_flags)
        components = path.parts[1:]
        try:
            if not components:
                if not directory:
                    raise ResearchError("local source must be a regular file")
                result, parent = parent, -1
                return result
            for component in components[:-1]:
                child = os.open(component, directory_flags, dir_fd=parent)
                os.close(parent)
                parent = child
            return os.open(components[-1], flags, dir_fd=parent)
        finally:
            if parent >= 0:
                os.close(parent)
    for component in (path,) + tuple(path.parents):
        if component.is_symlink():
            raise ResearchError("local source path cannot traverse a symlink")
    before = os.stat(path, follow_symlinks=False)
    fd = os.open(str(path), flags)
    actual = os.fstat(fd)
    if (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino):
        os.close(fd)
        raise ResearchError("local source changed while opening")
    return fd


def _discover_local(root: Path, policy: ResearchPolicy, entries_seen: List[int]) -> List[Path]:
    pending = [root]
    files: List[Path] = []
    while pending:
        directory = pending.pop()
        fd = -1
        try:
            fd = _open_local(directory, directory=True)
            # scandir(fd) gives POSIX discovery the same no-follow directory identity.
            target = fd if os.scandir in os.supports_fd else str(directory)
            entries = []
            with os.scandir(target) as iterator:
                for entry in iterator:
                    entries_seen[0] += 1
                    if entries_seen[0] > policy.max_local_entries:
                        raise ResearchError("local directory scan exceeds entry budget; select a smaller directory")
                    entries.append(entry)
            for entry in sorted(entries, key=lambda item: item.name):
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                candidate = directory / entry.name
                if entry.is_dir(follow_symlinks=False):
                    pending.append(candidate)
                elif entry.is_file(follow_symlinks=False):
                    files.append(candidate)
                    if len(files) > policy.max_local_files:
                        raise ResearchError("local file scan exceeds budget; select a smaller directory")
        except OSError as exc:
            raise ResearchError("local directory could not be read without following symlinks") from exc
        finally:
            if fd >= 0:
                os.close(fd)
    return files


def _read_local(path: Path, limit: int) -> bytes:
    if limit < 1:
        raise ResearchError("local byte budget exhausted")
    if path.is_symlink():
        raise ResearchError("local source cannot be a symlink")
    try:
        fd = _open_local(path)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ResearchError("local source must be a regular file")
            if before.st_size > limit:
                raise ResearchError("local source exceeds byte budget")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != \
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ResearchError("local source changed while reading")
        if len(data) > limit:
            raise ResearchError("local source exceeds byte budget")
        if path.name.endswith(".gz"):
            data = _expand_gzip(data, limit)
        return data
    except (OSError, EOFError) as exc:
        raise ResearchError("local source could not be read") from exc
