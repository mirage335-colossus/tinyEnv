"""Bounded, data-only pseudocode parsing and provider-driven execution.

Commands never evaluate Python, invoke a shell, or invent an agent answer. Each
``agent`` and ``critique`` calls the supplied provider. ``conclude`` is a labelled
completion checkpoint: its text is an event annotation, while the result contains
the latest actual agent answer. Agent-only completion carries no review verdict.
Once a critic executes, completion requires a fresh approved, supported verdict
with no doubts for the latest candidate. A new candidate invalidates that verdict.

Cancellation is cooperative at statement and callback boundaries. Callers own
provider timeouts and interruption of a blocking provider. Missing token usage is
accounted conservatively as UTF-8 bytes; providers can supply actual token usage.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Union


@dataclass(frozen=True)
class FlowLimits:
    max_source_bytes: int = 262144
    max_lines: int = 8192
    max_nodes: int = 2048
    max_depth: int = 16
    max_repeat: int = 1000


@dataclass(frozen=True)
class RunBudget:
    max_calls: int = 32
    max_steps: int = 512
    max_input_tokens: int = 65536
    max_output_tokens: int = 16384
    max_context_chars: int = 32768
    max_output_chars: int = 65536


@dataclass(frozen=True)
class Diagnostic:
    line: int
    column: int
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"line": self.line, "column": self.column,
                "code": self.code, "message": self.message}


@dataclass(frozen=True)
class Agent:
    line: int
    column: int
    role: str
    prompt: str


@dataclass(frozen=True)
class Critique:
    line: int
    column: int
    role: str
    prompt: str


@dataclass(frozen=True)
class Repeat:
    line: int
    column: int
    count: int
    body: tuple
    condition: str


@dataclass(frozen=True)
class Conditional:
    line: int
    column: int
    condition: str
    then_body: tuple
    else_body: tuple


@dataclass(frozen=True)
class Conclude:
    line: int
    column: int
    text: str


Node = Union[Agent, Critique, Repeat, Conditional, Conclude]


@dataclass(frozen=True)
class Program:
    source: str
    nodes: Tuple[Node, ...]


@dataclass(frozen=True)
class ParseResult:
    source: str
    program: Optional[Program]
    diagnostics: Tuple[Diagnostic, ...] = ()

    @property
    def valid(self) -> bool:
        return self.program is not None and not self.diagnostics

    def to_dict(self) -> dict:
        return {"valid": self.valid, "source": self.source,
                "diagnostics": [item.to_dict() for item in self.diagnostics]}


class _ParseError(Exception):
    def __init__(self, diagnostic: Diagnostic):
        self.diagnostic = diagnostic


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _check_limits(limits: FlowLimits) -> None:
    if not isinstance(limits, FlowLimits) or any(
            not _integer(getattr(limits, name)) for name in
            ("max_source_bytes", "max_lines", "max_nodes", "max_depth", "max_repeat")):
        raise ValueError("FlowLimits values must be nonnegative integers")
    if limits.max_depth > 64 or limits.max_repeat > 2147483647:
        raise ValueError("FlowLimits depth must not exceed 64 and repeat cap must not exceed 2147483647")


class _Parser:
    _call = re.compile(r"(agent|critique) [ \t]*([A-Za-z][A-Za-z0-9_-]{0,63})[ \t]*:[ \t]*(.+)")
    _repeat = re.compile(r"repeat [ \t]*([0-9]+)")
    _if = re.compile(r"if [ \t]*(approved|supported|rejected)")
    _until = re.compile(r"until [ \t]*(approved|supported)")

    def __init__(self, source: str, limits: FlowLimits):
        self.source = source
        self.limits = limits
        self.lines = source.split("\n")
        self.position = 0
        self.count = 0

    def error(self, code: str, message: str, line: Optional[int] = None,
              column: int = 1) -> None:
        raise _ParseError(Diagnostic(line or self.position + 1, column, code, message))

    def block(self, depth: int, terminators: tuple = ()) -> tuple:
        nodes = []
        while self.position < len(self.lines):
            raw = self.lines[self.position]
            value = raw.strip(" \t\r")
            line = self.position + 1
            column = len(raw) - len(raw.lstrip(" \t\r")) + 1
            if not value or value.startswith("#"):
                self.position += 1
                continue
            until = self._until.fullmatch(value)
            terminator = "until " + until.group(1) if until else value
            if terminator in terminators:
                return tuple(nodes)
            if value == "else" or value == "end" or value.startswith("until "):
                self.error("unexpected_terminator", "Unexpected block terminator", line, column)
            self.count += 1
            if self.count > self.limits.max_nodes:
                self.error("node_limit", "Program exceeds the statement limit", line, column)
            call = self._call.fullmatch(value)
            repeat = self._repeat.fullmatch(value)
            branch = self._if.fullmatch(value)
            self.position += 1
            if call:
                prompt = call.group(3).strip(" \t\r")
                if not prompt:
                    self.error("invalid_syntax", "An agent prompt must not be empty", line, column)
                kind = Agent if call.group(1) == "agent" else Critique
                nodes.append(kind(line, column, call.group(2), prompt))
            elif repeat:
                # Bound the decimal string before conversion, even on Python
                # versions that do not limit integer-string conversions.
                digits = repeat.group(1).lstrip("0") or "0"
                if len(digits) > len(str(self.limits.max_repeat)):
                    self.error("repeat_limit", "Repeat count exceeds its limit", line, column)
                count = int(digits)
                if count < 1 or count > self.limits.max_repeat:
                    self.error("repeat_limit", "Repeat count must be within its positive limit", line, column)
                if depth >= self.limits.max_depth:
                    self.error("nesting_limit", "Program exceeds the nesting limit", line, column)
                body = self.block(depth + 1, ("until approved", "until supported"))
                if self.position >= len(self.lines):
                    self.error("missing_terminator", "Repeat requires until approved or until supported", line, column)
                condition = self._until.fullmatch(self.lines[self.position].strip(" \t\r")).group(1)
                self.position += 1
                if not body:
                    self.error("empty_block", "Repeat body must contain a statement", line, column)
                nodes.append(Repeat(line, column, count, body, condition))
            elif branch:
                if depth >= self.limits.max_depth:
                    self.error("nesting_limit", "Program exceeds the nesting limit", line, column)
                then_body = self.block(depth + 1, ("else", "end"))
                if self.position >= len(self.lines):
                    self.error("missing_terminator", "Conditional requires end", line, column)
                else_body = ()
                if self.lines[self.position].strip(" \t\r") == "else":
                    self.position += 1
                    else_body = self.block(depth + 1, ("end",))
                if self.position >= len(self.lines):
                    self.error("missing_terminator", "Conditional requires end", line, column)
                self.position += 1
                nodes.append(Conditional(line, column, branch.group(1), then_body, else_body))
            elif value.startswith("conclude:") and value[len("conclude:"):].strip(" \t\r"):
                nodes.append(Conclude(line, column, value[len("conclude:"):].strip(" \t\r")))
            else:
                self.error("invalid_syntax", "Expected agent, critique, repeat, if, or conclude", line, column)
        return tuple(nodes)


def parse(source: str, limits: Optional[FlowLimits] = None) -> ParseResult:
    """Parse the complete source, preserving rejected source verbatim."""
    limits = FlowLimits() if limits is None else limits
    _check_limits(limits)
    if not isinstance(source, str):
        return ParseResult(source, None, (Diagnostic(1, 1, "invalid_source", "Source must be text"),))
    # Each Unicode scalar needs at least one UTF-8 byte. Reject an obviously
    # oversized input before allocating its encoded copy.
    if len(source) > limits.max_source_bytes:
        return ParseResult(source, None, (Diagnostic(1, 1, "source_limit", "Source exceeds its byte limit"),))
    try:
        size = len(source.encode("utf-8"))
    except UnicodeEncodeError as error:
        prefix = source[:error.start]
        line = prefix.count("\n") + 1
        column = len(prefix.rsplit("\n", 1)[-1]) + 1
        return ParseResult(source, None, (Diagnostic(line, column, "invalid_source", "Source contains invalid Unicode"),))
    if size > limits.max_source_bytes:
        return ParseResult(source, None, (Diagnostic(1, 1, "source_limit", "Source exceeds its byte limit"),))
    line_count = source.count("\n") + (0 if not source or source.endswith("\n") else 1)
    if line_count > limits.max_lines:
        return ParseResult(source, None, (Diagnostic(limits.max_lines + 1, 1, "line_limit", "Source exceeds its line limit"),))
    line, column = 1, 1
    for index, char in enumerate(source):
        if unicodedata.category(char) == "Cc" and char not in "\t\r\n":
            return ParseResult(source, None, (Diagnostic(line, column, "invalid_control", "Source contains a forbidden control character"),))
        if char == "\r" and index + 1 < len(source) and source[index + 1] != "\n":
            return ParseResult(source, None, (Diagnostic(line, column, "invalid_control", "Carriage return must occur at a physical line ending"),))
        if char == "\n":
            line, column = line + 1, 1
        else:
            column += 1
    parser = _Parser(source, limits)
    try:
        nodes = parser.block(0)
        return ParseResult(source, Program(source, nodes))
    except _ParseError as error:
        return ParseResult(source, None, (error.diagnostic,))


validate = parse


@dataclass(frozen=True)
class Verdict:
    approved: bool
    supported: bool
    doubts: Tuple[str, ...]

    def to_dict(self) -> dict:
        return {"approved": self.approved, "supported": self.supported,
                "doubts": list(self.doubts)}


@dataclass(frozen=True)
class AgentRequest:
    kind: str
    role: str
    prompt: str
    context: str
    call_index: int
    max_output_tokens: int


@dataclass(frozen=True)
class AgentResponse:
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@dataclass(frozen=True)
class FlowEvent:
    kind: str
    line: int
    column: int = 1
    role: str = ""
    text: str = ""
    verdict: Optional[Verdict] = None
    iteration: Optional[int] = None

    def to_dict(self) -> dict:
        result = {"kind": self.kind, "line": self.line, "column": self.column}
        if self.role:
            result["role"] = self.role
        if self.text:
            result["text"] = self.text
        if self.verdict is not None:
            result["verdict"] = self.verdict.to_dict()
        if self.iteration is not None:
            result["iteration"] = self.iteration
        return result


@dataclass(frozen=True)
class RunResult:
    status: str
    output: str
    events: Tuple[FlowEvent, ...]
    calls: int
    steps: int
    input_tokens: int
    output_tokens: int
    diagnostics: Tuple[Diagnostic, ...] = ()
    verdict: Optional[Verdict] = None

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict:
        return {"status": self.status, "output": self.output,
                "events": [item.to_dict() for item in self.events],
                "calls": self.calls, "steps": self.steps,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "diagnostics": [item.to_dict() for item in self.diagnostics],
                "verdict": self.verdict.to_dict() if self.verdict is not None else None}


class _RunStop(Exception):
    def __init__(self, status: str, diagnostic: Diagnostic):
        self.status = status
        self.diagnostic = diagnostic


_CRITIC_CONTRACT = (
    "\nReview the latest candidate using the supplied criteria and evidence. "
    "Return only a JSON object with exactly these keys: approved (boolean), "
    "supported (boolean), doubts (array of strings). Approve only when supported "
    "and doubts is empty. Do not assume an unsupported claim is true."
)


def _strict_verdict(text: str) -> Verdict:
    def object_pairs(pairs: list) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate verdict key")
            result[key] = value
        return result

    try:
        data = json.loads(text, object_pairs_hook=object_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid JSON constant")))
    except (ValueError, RecursionError) as error:
        raise ValueError("Critic must return one strict JSON verdict object") from error
    if (not isinstance(data, dict) or set(data) != {"approved", "supported", "doubts"}
            or type(data["approved"]) is not bool or type(data["supported"]) is not bool
            or not isinstance(data["doubts"], list)
            or any(not isinstance(item, str) for item in data["doubts"])):
        raise ValueError("Critic verdict requires boolean approved/supported and string-array doubts")
    if data["approved"] and (not data["supported"] or data["doubts"]):
        raise ValueError("An approved verdict must be supported and contain no doubts")
    return Verdict(data["approved"], data["supported"], tuple(data["doubts"]))


def _check_budget(budget: RunBudget) -> None:
    if not isinstance(budget, RunBudget) or any(
            not _integer(getattr(budget, name)) for name in
            ("max_calls", "max_steps", "max_input_tokens", "max_output_tokens")) or any(
            not _integer(getattr(budget, name), 1) for name in
            ("max_context_chars", "max_output_chars")):
        raise ValueError("RunBudget caps must be integers; text caps must be positive")


class _Runner:
    def __init__(self, provider: Callable, budget: RunBudget, cancel: Any, context: str):
        self.provider = provider
        self.budget = budget
        self.cancel = cancel
        marker = "[Earlier context truncated]\n"
        cap = budget.max_context_chars
        self.context = context if len(context) <= cap else (
            marker[:cap] if cap <= len(marker) else marker + context[-(cap - len(marker)):])
        self.events = []
        self.calls = self.steps = self.input_tokens = self.output_tokens = 0
        self.output = ""
        self.verdict = None
        self.verdict_serial = 0
        self.critic_executed = False
        self.history = ""
        self.current_node = None

    def stop(self, status: str, code: str, message: str, node: Optional[Node] = None) -> None:
        node = node or self.current_node
        raise _RunStop(status, Diagnostic(node.line if node else 1,
                                         node.column if node else 1, code, message))

    def check_cancel(self) -> None:
        if self.cancel is None:
            return
        try:
            cancelled = self.cancel() if callable(self.cancel) else self.cancel.is_set()
        except Exception:
            self.stop("failed", "invalid_cancel", "Cancellation checker failed")
        if cancelled:
            self.stop("cancelled", "cancelled", "Execution was cancelled")

    def step(self, node: Node) -> None:
        self.current_node = node
        self.check_cancel()
        if self.steps >= self.budget.max_steps:
            self.stop("budget_exceeded", "budget_steps", "Execution reached its step budget", node)
        self.steps += 1

    def bounded_context(self, require_complete_candidate: bool = False) -> str:
        chunks = [self.context] if self.context else []
        if self.history:
            chunks.append("Agent history:\n" + self.history)
        prior = "\n\n".join(chunks)
        candidate = "Latest candidate:\n" + self.output if self.output else ""
        cap = self.budget.max_context_chars
        if require_complete_candidate and len(candidate) > cap:
            self.stop("budget_exceeded", "budget_context", "Complete candidate does not fit the critic context budget")
        if require_complete_candidate:
            # A verdict covers the complete candidate. Never present only a
            # candidate tail and attach the resulting approval to unseen bytes.
            allowance = cap - len(candidate) - (2 if prior else 0)
            marker = "[Earlier context truncated]\n"
            if len(prior) > max(0, allowance):
                prior = (marker + prior[-(allowance - len(marker)):]
                         if allowance > len(marker) else marker[:max(0, allowance)])
            return prior + ("\n\n" if prior else "") + candidate
        value = prior + ("\n\n" if prior and candidate else "") + candidate
        if len(value) <= self.budget.max_context_chars:
            return value
        marker = "[Earlier context truncated]\n"
        if cap <= len(marker):
            return marker[:cap]
        return marker + value[-(cap - len(marker)):]

    def remember(self, kind: str, role: str, text: str) -> None:
        # Only bounded history is retained; event/output storage is separately
        # bounded by source, call and output-character caps.
        value = self.history + "\n" + kind + " " + role + ": " + text
        self.history = value[-self.budget.max_context_chars:]

    async def call(self, node: Union[Agent, Critique]) -> str:
        self.check_cancel()
        if self.calls >= self.budget.max_calls:
            self.stop("budget_exceeded", "budget_calls", "Execution reached its provider-call budget", node)
        remaining = self.budget.max_output_tokens - self.output_tokens
        if remaining <= 0:
            self.stop("budget_exceeded", "budget_output_tokens", "No output-token budget remains", node)
        kind = "critique" if isinstance(node, Critique) else "agent"
        prompt = node.prompt + (_CRITIC_CONTRACT if kind == "critique" else "")
        context = self.bounded_context(require_complete_candidate=kind == "critique")
        request = AgentRequest(kind, node.role, prompt, context, self.calls + 1, remaining)
        estimated_input = len((kind + node.role + prompt + context).encode("utf-8"))
        if estimated_input > self.budget.max_input_tokens - self.input_tokens:
            self.stop("budget_exceeded", "budget_input_tokens", "Provider request exceeds the remaining input-token budget", node)
        self.calls += 1
        # A failed/cancelled call still consumed a request. Actual usage replaces
        # this reservation only once a valid response is available.
        self.input_tokens += estimated_input
        self.events.append(FlowEvent("call", node.line, node.column, node.role, kind))
        try:
            response = self.provider(request)
            if inspect.isawaitable(response):
                response = await response
        except asyncio.CancelledError:
            self.stop("cancelled", "cancelled", "Provider execution was cancelled", node)
        except Exception:
            self.check_cancel()
            self.stop("failed", "provider_error", "Provider callback failed", node)
        if isinstance(response, str):
            response = AgentResponse(response)
        if not isinstance(response, AgentResponse) or not isinstance(response.text, str):
            self.check_cancel()
            self.stop("failed", "unsupported_response", "Provider must return text or AgentResponse", node)
        if any(value is not None and not _integer(value)
               for value in (response.input_tokens, response.output_tokens)):
            self.stop("failed", "invalid_usage", "Provider token usage must be nonnegative integers", node)
        try:
            estimated_output = len(response.text.encode("utf-8"))
        except UnicodeEncodeError:
            self.stop("failed", "unsupported_response", "Provider returned invalid Unicode", node)
        if response.input_tokens is not None:
            self.input_tokens += response.input_tokens - estimated_input
        self.output_tokens += response.output_tokens if response.output_tokens is not None else estimated_output
        self.check_cancel()
        if self.input_tokens > self.budget.max_input_tokens:
            self.stop("budget_exceeded", "budget_input_tokens", "Provider reported input usage beyond the budget", node)
        if self.output_tokens > self.budget.max_output_tokens:
            self.stop("budget_exceeded", "budget_output_tokens", "Provider output exceeded its token budget", node)
        if sum(len(event.text) for event in self.events if event.kind in ("agent", "critique")) + len(response.text) > self.budget.max_output_chars:
            self.stop("budget_exceeded", "budget_output_chars", "Provider output exceeded its text budget", node)
        if not response.text.strip():
            self.stop("failed", "empty_response", "Provider returned no answer", node)
        return response.text

    def condition(self, condition: str, node: Node) -> bool:
        if self.verdict is None:
            self.stop("failed", "missing_verdict", "Condition requires a fresh critic verdict", node)
        accepted = self.verdict.approved and self.verdict.supported and not self.verdict.doubts
        return accepted if condition == "approved" else self.verdict.supported if condition == "supported" else not accepted

    async def block(self, nodes: tuple) -> None:
        for node in nodes:
            self.step(node)
            if isinstance(node, Agent):
                self.verdict = None
                text = await self.call(node)
                self.output = text
                self.events.append(FlowEvent("agent", node.line, node.column, node.role, text))
                self.remember("agent", node.role, text)
            elif isinstance(node, Critique):
                if not self.output:
                    self.stop("failed", "missing_candidate", "Critique requires an actual agent candidate", node)
                text = await self.call(node)
                self.critic_executed = True
                try:
                    verdict = _strict_verdict(text)
                except ValueError as error:
                    self.stop("failed", "malformed_verdict", str(error), node)
                self.verdict = verdict
                self.verdict_serial += 1
                self.events.append(FlowEvent("critique", node.line, node.column, node.role, text, verdict))
                self.remember("critique", node.role, text)
            elif isinstance(node, Repeat):
                for iteration in range(1, node.count + 1):
                    self.step(node)
                    serial = self.verdict_serial
                    self.events.append(FlowEvent("iteration", node.line, node.column, iteration=iteration))
                    await self.block(node.body)
                    self.current_node = node
                    if self.verdict is not None and self.verdict_serial > serial and self.condition(node.condition, node):
                        self.events.append(FlowEvent("repeat_complete", node.line, node.column, iteration=iteration))
                        break
                else:
                    self.stop("exhausted", "repeat_exhausted", "Repeat exhausted its limit without a fresh satisfying verdict", node)
            elif isinstance(node, Conditional):
                matched = self.condition(node.condition, node)
                self.events.append(FlowEvent("branch", node.line, node.column, text="then" if matched else "else"))
                await self.block(node.then_body if matched else node.else_body)
            elif isinstance(node, Conclude):
                self.events.append(FlowEvent("conclude", node.line, node.column, text=node.text))
                self.completion(node)
            else:
                self.stop("invalid", "invalid_program", "Program contains an unsupported statement", node)

    def completion(self, node: Optional[Node] = None) -> None:
        self.check_cancel()
        if not self.output:
            self.stop("failed", "missing_candidate", "Completion requires an actual agent answer", node)
        if self.critic_executed and self.verdict is None:
            self.stop("rejected", "unreviewed_candidate", "Latest candidate has no fresh critic verdict", node)
        if self.verdict is not None and not (self.verdict.approved and self.verdict.supported and not self.verdict.doubts):
            self.stop("rejected", "rejected_verdict", "Latest critic did not approve the supported candidate", node)

    def result(self, status: str, diagnostics: tuple = ()) -> RunResult:
        return RunResult(status, self.output, tuple(self.events), self.calls, self.steps,
                         self.input_tokens, self.output_tokens, diagnostics, self.verdict)


async def run_async(program_or_source: Union[str, Program, ParseResult], provider: Callable,
                    *, budget: Optional[RunBudget] = None, cancel: Any = None,
                    context: str = "") -> RunResult:
    """Execute using a sync or async callable; every failure has a typed result."""
    budget = RunBudget() if budget is None else budget
    _check_budget(budget)
    if isinstance(program_or_source, str):
        parsed = parse(program_or_source)
    elif isinstance(program_or_source, ParseResult):
        if not program_or_source.valid:
            return RunResult("invalid", "", (), 0, 0, 0, 0,
                             program_or_source.diagnostics or
                             (Diagnostic(1, 1, "invalid_program", "Parsed program was rejected"),))
        # Reparse the retained source: public dataclass construction cannot bypass
        # the same grammar, depth and size limits applied to ordinary source.
        parsed = parse(program_or_source.source)
    elif isinstance(program_or_source, Program):
        parsed = parse(program_or_source.source)
    else:
        parsed = ParseResult("", None, (Diagnostic(1, 1, "invalid_program", "Expected source or parsed program"),))
    if not parsed.valid:
        return RunResult("invalid", "", (), 0, 0, 0, 0, parsed.diagnostics)
    if not callable(provider) or not isinstance(context, str):
        return RunResult("failed", "", (), 0, 0, 0, 0,
                         (Diagnostic(1, 1, "invalid_configuration", "Provider must be callable and context must be text"),))
    try:
        context.encode("utf-8")
    except UnicodeEncodeError:
        return RunResult("failed", "", (), 0, 0, 0, 0,
                         (Diagnostic(1, 1, "invalid_configuration", "Context contains invalid Unicode"),))
    runner = _Runner(provider, budget, cancel, context)
    try:
        await runner.block(parsed.program.nodes)
        runner.completion()
        return runner.result("completed")
    except _RunStop as error:
        runner.events.append(FlowEvent(error.status, error.diagnostic.line,
                                      error.diagnostic.column, text=error.diagnostic.message))
        return runner.result(error.status, (error.diagnostic,))


def run(program_or_source: Union[str, Program, ParseResult], provider: Callable,
        *, budget: Optional[RunBudget] = None, cancel: Any = None,
        context: str = "") -> RunResult:
    """Synchronous entry point; use run_async inside an existing event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_async(program_or_source, provider, budget=budget,
                                     cancel=cancel, context=context))
    return RunResult("failed", "", (), 0, 0, 0, 0,
                     (Diagnostic(1, 1, "async_required", "Use run_async inside an active event loop"),))
