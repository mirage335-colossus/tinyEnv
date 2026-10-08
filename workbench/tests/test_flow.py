"""Offline contract checks for the bounded, declarative agent-flow runtime."""

import asyncio
from dataclasses import FrozenInstanceError
import json
import threading
import unittest

from workbench.services import flow


def verdict(approved=False, supported=False, doubts=()):
    return json.dumps(
        {"approved": approved, "supported": supported, "doubts": list(doubts)}
    )


class ScriptedProvider:
    """Expose the actual call order and fail if execution leaves its script."""

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return next(self.responses)


class FlowParserTests(unittest.TestCase):
    def assert_invalid(self, source, limits=None, code=None):
        result = flow.parse(source, limits=limits)
        self.assertEqual(result.source, source)
        self.assertIsNone(result.program)
        self.assertTrue(result.diagnostics)
        for diagnostic in result.diagnostics:
            self.assertGreaterEqual(diagnostic.line, 1)
            self.assertGreaterEqual(diagnostic.column, 1)
            self.assertTrue(diagnostic.code)
            self.assertTrue(diagnostic.message)
        if code is not None:
            self.assertIn(code, [item.code for item in result.diagnostics])
        return result

    def test_crlf_comments_and_literal_hash_preserve_original_source(self):
        source = "\r\n# comment\r\nagent Writer_2: Keep # this literal.  \r\nconclude: checkpoint\r\n"
        result = flow.parse(source)
        self.assertEqual(result.source, source)
        self.assertIsNotNone(result.program)
        self.assertFalse(result.diagnostics)

    def test_empty_and_comment_only_drafts_are_valid_empty_programs(self):
        for source in ("", " \t\r\n", "# First.\n\t# Second.\r\n"):
            with self.subTest(source=source):
                result = flow.parse(source)
                self.assertEqual(result.source, source)
                self.assertIsNotNone(result.program)
                self.assertEqual(result.program.nodes, ())
                self.assertFalse(result.diagnostics)

    def test_empty_conditional_arms_remain_editable(self):
        for source in (
            "if approved\nend\n",
            "if approved\nelse\nend\n",
            "if approved\nelse\nconclude: Else.\nend\n",
            "if approved\nconclude: Then.\nelse\nend\n",
        ):
            with self.subTest(source=source):
                result = flow.parse(source)
                self.assertIsNotNone(result.program)
                self.assertFalse(result.diagnostics)

    def test_ascii_spacing_matches_the_gui_editing_grammar(self):
        source = (
            "repeat  \t2 \r\nagent  \tWriter_2 \t:  Draft. \r\n"
            "critique   reviewer\t : Check.\r\nif  \tapproved  \r\n"
            "else\r\nend\r\nuntil  \tapproved \r\n"
        )
        result = flow.parse(source)
        self.assertIsNotNone(result.program)
        self.assertFalse(result.diagnostics)

    def test_required_command_space_cannot_be_replaced_by_a_tab(self):
        for source in (
            "agent\twriter: Draft.\n",
            "critique\treviewer: Check.\n",
            "repeat\t2\nagent writer: Draft.\nuntil approved\n",
            "if\tapproved\nend\n",
        ):
            with self.subTest(source=source):
                self.assert_invalid(source)

    def test_non_ascii_whitespace_is_data_rather_than_indentation(self):
        self.assert_invalid("\u00a0agent writer: Draft.\n")
        source = "agent writer: \u00a0Draft.\u00a0\n"
        result = flow.parse(source)
        self.assertIsNotNone(result.program)
        self.assertEqual(result.program.nodes[0].prompt, "\u00a0Draft.\u00a0")

    def test_embedded_carriage_return_is_forbidden(self):
        for source in ("agent writer: A\rB\n", "agent writer:\r Draft.\n"):
            with self.subTest(source=source):
                self.assert_invalid(source)
        for source in ("agent writer: Draft.\r\n", "agent writer: Draft.\r"):
            with self.subTest(source=source):
                self.assertIsNotNone(flow.parse(source).program)

    def test_nested_repeat_and_conditional_are_valid(self):
        source = """repeat 2
  agent planner: Plan.
  repeat 3
    agent writer: Write.
    critique reviewer: Review.
  until approved
  if supported
    conclude: Supported.
  else
    conclude: Rejected.
  end
until supported
"""
        result = flow.parse(source)
        self.assertIsNotNone(result.program)
        self.assertFalse(result.diagnostics)

    def test_unknown_statement_has_source_location(self):
        result = self.assert_invalid(
            "agent writer: Draft.\nunsupported statement\n", code="invalid_syntax"
        )
        self.assertEqual(result.diagnostics[0].line, 2)

    def test_invalid_grammar_is_never_a_partial_program(self):
        for source in (
            "prompt: A standalone prompt is not supported.\n",
            "until approved\n",
            "else\n",
            "end\n",
            "repeat 2\nagent writer: Draft.\n",
            "repeat 2\nuntil approved\n",
            "if approved\nconclude: Checkpoint.\n",
            "if Approved\nconclude: Checkpoint.\nend\n",
            "agent -writer: Draft.\n",
            "agent writer: \n",
            "critique reviewer: \n",
            "agent writer: A\x00B\n",
            "agent writer: A\x01B\n",
        ):
            with self.subTest(source=source):
                self.assert_invalid(source)

    def test_syntax_after_conclude_is_still_validated(self):
        self.assert_invalid("conclude: Label.\nexecute arbitrary code\n")

    def test_utf8_source_limit_is_measured_in_bytes(self):
        source = "agent writer: café\n"
        encoded_size = len(source.encode("utf-8"))
        self.assertIsNotNone(
            flow.parse(source, flow.FlowLimits(max_source_bytes=encoded_size)).program
        )
        self.assert_invalid(
            source,
            flow.FlowLimits(max_source_bytes=encoded_size - 1),
            "source_limit",
        )

    def test_node_limit_rejects_instead_of_dropping_statements(self):
        self.assert_invalid(
            "agent writer: Draft.\nconclude: Label.\n",
            flow.FlowLimits(max_nodes=1),
            "node_limit",
        )

    def test_line_limit_preserves_rejected_source(self):
        self.assert_invalid(
            "agent writer: Draft.\nconclude: Label.\n# Extra line.",
            flow.FlowLimits(max_lines=2),
            "line_limit",
        )

    def test_one_trailing_newline_does_not_consume_an_extra_line(self):
        self.assertIsNotNone(
            flow.parse("agent writer: Draft.\n", flow.FlowLimits(max_lines=1)).program
        )
        self.assert_invalid(
            "agent writer: Draft.\n\n", flow.FlowLimits(max_lines=1), "line_limit"
        )

    def test_nesting_limit_rejects_inner_block(self):
        self.assert_invalid(
            "repeat 2\nrepeat 2\nagent writer: Draft.\nuntil approved\nuntil approved\n",
            flow.FlowLimits(max_depth=1),
            "nesting_limit",
        )

    def test_repeat_limit_is_checked_at_parse_time(self):
        self.assert_invalid(
            "repeat 3\nagent writer: Draft.\nuntil approved\n",
            flow.FlowLimits(max_repeat=2),
            "repeat_limit",
        )

    def test_configuration_cannot_raise_limits_beyond_safe_hard_ceilings(self):
        for limits in (
            flow.FlowLimits(max_depth=65),
            flow.FlowLimits(max_repeat=2147483648),
        ):
            with self.subTest(limits=limits):
                with self.assertRaises(ValueError):
                    flow.parse("agent writer: Draft.\n", limits)
        self.assertIsNotNone(
            flow.parse(
                "repeat 2147483647\nagent writer: Draft.\nuntil approved\n",
                flow.FlowLimits(max_depth=64, max_repeat=2147483647),
            ).program
        )

    def test_zero_depth_and_repeat_caps_still_allow_leaf_statements(self):
        source = "agent writer: Draft.\n"
        for limits in (flow.FlowLimits(max_depth=0), flow.FlowLimits(max_repeat=0)):
            with self.subTest(limits=limits):
                self.assertIsNotNone(flow.parse(source, limits).program)
        self.assert_invalid(
            "if approved\nend\n", flow.FlowLimits(max_depth=0), "nesting_limit"
        )
        self.assert_invalid(
            "repeat 1\nagent writer: Draft.\nuntil approved\n",
            flow.FlowLimits(max_repeat=0),
            "repeat_limit",
        )

    def test_zero_node_cap_accepts_empty_and_comment_only_drafts(self):
        limits = flow.FlowLimits(max_nodes=0)
        for source in ("", "# Editable draft.\n", " \t\n"):
            with self.subTest(source=source):
                result = flow.parse(source, limits)
                self.assertIsNotNone(result.program)
                self.assertEqual(result.program.nodes, ())
        self.assert_invalid("agent writer: Draft.\n", limits, "node_limit")

    def test_zero_byte_and_line_caps_accept_only_truly_empty_source(self):
        for limits, code in (
            (flow.FlowLimits(max_source_bytes=0), "source_limit"),
            (flow.FlowLimits(max_lines=0), "line_limit"),
        ):
            with self.subTest(limits=limits):
                result = flow.parse("", limits)
                self.assertIsNotNone(result.program)
                self.assertEqual(result.program.nodes, ())
                for source in ("\n", " ", "# Comment."):
                    with self.subTest(source=source):
                        self.assert_invalid(source, limits, code)
        self.assertIsNotNone(
            flow.parse(
                "", flow.FlowLimits(max_source_bytes=0, max_lines=0, max_nodes=0,
                                    max_depth=0, max_repeat=0)
            ).program
        )

    def test_invalid_limit_configurations_are_not_silently_defaulted(self):
        for limits in (False, 0, {}, (), object()):
            with self.subTest(limits=limits):
                with self.assertRaises(ValueError):
                    flow.parse("", limits)
        for field in ("max_source_bytes", "max_lines", "max_nodes", "max_depth", "max_repeat"):
            for value in (False, -1, 1.0):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        flow.parse("", flow.FlowLimits(**{field: value}))

    def test_validate_has_the_same_public_result_as_parse(self):
        for source in ("agent writer: Draft.\n", "not a statement\n"):
            with self.subTest(source=source):
                self.assertEqual(flow.validate(source), flow.parse(source))


class FlowRuntimeTests(unittest.TestCase):
    def assert_diagnostic(self, result, code):
        self.assertIn(code, [item.code for item in result.diagnostics])

    def test_agent_only_answer_and_conclude_annotation(self):
        provider = ScriptedProvider("Actual answer.")
        result = flow.run("agent writer: Draft.\nconclude: Finished.\n", provider)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "Actual answer.")
        self.assertEqual(result.calls, 1)
        self.assertFalse(result.diagnostics)
        self.assertTrue(any(event.text == "Finished." for event in result.events))

    def test_empty_draft_cannot_execute_as_a_successful_answer(self):
        for source in ("", "# Editable draft.\n", "conclude: Checkpoint.\n"):
            with self.subTest(source=source):
                provider = ScriptedProvider()
                result = flow.run(source, provider)
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.calls, 0)
                self.assertEqual(result.output, "")
                self.assert_diagnostic(result, "missing_candidate")

    def test_provider_request_is_immutable_and_carries_context(self):
        provider = ScriptedProvider("Answer.")
        result = flow.run(
            "agent Writer_2: Keep # this literal.\n",
            provider,
            context="Original user context.",
        )
        self.assertEqual(result.status, "completed")
        request = provider.requests[0]
        self.assertEqual(request.kind, "agent")
        self.assertEqual(request.role, "Writer_2")
        self.assertEqual(request.prompt, "Keep # this literal.")
        self.assertIn("Original user context.", request.context)
        self.assertGreater(request.max_output_tokens, 0)
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            request.prompt = "Mutation."

    def test_repeat_revises_until_a_fresh_approved_verdict(self):
        provider = ScriptedProvider(
            "First draft.", verdict(doubts=("Missing evidence.",)),
            "Revised answer.", verdict(True, True),
        )
        result = flow.run(
            "repeat 3\nagent writer: Revise.\ncritique reviewer: Check evidence.\n"
            "until approved\nconclude: Accepted.\n",
            provider,
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "Revised answer.")
        self.assertEqual(result.calls, 4)
        self.assertEqual(
            [(request.kind, request.role) for request in provider.requests],
            [("agent", "writer"), ("critique", "reviewer")] * 2,
        )
        self.assertIn("First draft.", provider.requests[1].context)
        self.assertIn("Missing evidence.", provider.requests[2].context)
        indices = [request.call_index for request in provider.requests]
        self.assertEqual(indices, list(range(indices[0], indices[0] + 4)))

    def test_nested_repeats_keep_distinct_iteration_counts(self):
        provider = ScriptedProvider(
            "Plan one.", "Draft one.", verdict(),
            "Draft two.", verdict(True, True), verdict(),
            "Plan two.", "Draft three.", verdict(True, True), verdict(True, True),
        )
        result = flow.run(
            "repeat 2\nagent planner: Plan.\nrepeat 2\nagent writer: Write.\n"
            "critique reviewer: Check draft.\nuntil approved\n"
            "critique architect: Check plan.\nuntil supported\nconclude: Done.\n",
            provider,
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "Draft three.")
        self.assertEqual(result.calls, 10)
        self.assertEqual(
            [request.role for request in provider.requests],
            ["planner", "writer", "reviewer", "writer", "reviewer", "architect",
             "planner", "writer", "reviewer", "architect"],
        )

    def test_exhausted_repeat_stops_before_following_statements(self):
        provider = ScriptedProvider("First.", verdict(), "Second.", verdict())
        result = flow.run(
            "repeat 2\nagent writer: Draft.\ncritique reviewer: Check.\n"
            "until approved\nagent forbidden: Must never execute.\n"
            "conclude: Must never conclude.\n",
            provider,
        )
        self.assertEqual(result.status, "exhausted")
        self.assertEqual(result.calls, 4)
        self.assert_diagnostic(result, "repeat_exhausted")
        self.assertFalse(any(event.text == "Must never conclude." for event in result.events))

    def test_invalid_verdicts_fail_closed(self):
        malformed = (
            "true",
            "{}",
            '{"approved": false, "approved": true, "supported": true, "doubts": []}',
            "```json\n" + verdict(True, True) + "\n```",
            json.dumps({"approved": "true", "supported": True, "doubts": []}),
            json.dumps({"approved": 1, "supported": True, "doubts": []}),
            json.dumps({"approved": True, "supported": 1, "doubts": []}),
            json.dumps({"approved": False, "supported": False, "doubts": "No."}),
            json.dumps({"approved": False, "supported": False, "doubts": [1]}),
            json.dumps({"approved": True, "supported": True, "doubts": [], "extra": 1}),
            verdict(True, False),
            verdict(True, True, ("Unresolved doubt.",)),
        )
        for response in malformed:
            with self.subTest(response=response):
                provider = ScriptedProvider("Candidate.", response)
                result = flow.run(
                    "agent writer: Draft.\ncritique reviewer: Check.\n"
                    "agent forbidden: Must never execute.\n",
                    provider,
                )
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.calls, 2)
                self.assert_diagnostic(result, "malformed_verdict")

    def test_if_else_uses_actual_approved_and_rejected_verdicts(self):
        source = (
            "agent writer: Draft.\ncritique reviewer: Check.\nif approved\n"
            "conclude: Accepted branch.\nelse\nconclude: Rejected branch.\nend\n"
        )
        for accepted in (True, False):
            with self.subTest(accepted=accepted):
                provider = ScriptedProvider("Candidate.", verdict(accepted, accepted))
                result = flow.run(source, provider)
                self.assertEqual(result.status, "completed" if accepted else "rejected")
                self.assertEqual(result.output, "Candidate.")
                expected = "Accepted branch." if accepted else "Rejected branch."
                other = "Rejected branch." if accepted else "Accepted branch."
                self.assertTrue(any(event.text == expected for event in result.events))
                self.assertFalse(any(event.text == other for event in result.events))

    def test_rejected_branch_can_revise_and_obtain_a_fresh_approval(self):
        provider = ScriptedProvider(
            "Unsupported answer.", verdict(), "Supported answer.", verdict(True, True)
        )
        result = flow.run(
            "agent writer: Draft.\ncritique reviewer: Check.\nif rejected\n"
            "agent writer: Fix.\ncritique reviewer: Recheck.\nend\nconclude: Done.\n",
            provider,
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "Supported answer.")
        self.assertEqual(result.calls, 4)

    def test_supported_condition_does_not_imply_approval(self):
        provider = ScriptedProvider("Candidate.", verdict(False, True))
        result = flow.run(
            "agent writer: Draft.\ncritique reviewer: Check.\nif supported\n"
            "conclude: Supported branch.\nelse\nconclude: Unsupported branch.\nend\n",
            provider,
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.output, "Candidate.")
        self.assertTrue(any(event.text == "Supported branch." for event in result.events))
        self.assertFalse(any(event.text == "Unsupported branch." for event in result.events))

    def test_new_agent_answer_cannot_inherit_an_old_approval(self):
        provider = ScriptedProvider("Accepted.", verdict(True, True), "Unreviewed.")
        result = flow.run(
            "agent writer: Draft.\ncritique reviewer: Check.\n"
            "agent writer: Replace.\nconclude: Done.\n",
            provider,
        )
        self.assertEqual(result.status, "rejected")
        self.assert_diagnostic(result, "unreviewed_candidate")

    def test_critique_requires_a_candidate_before_calling_provider(self):
        provider = ScriptedProvider()
        result = flow.run("critique reviewer: Check.\n", provider)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.calls, 0)
        self.assert_diagnostic(result, "missing_candidate")

    def test_invalid_source_never_calls_provider(self):
        provider = ScriptedProvider()
        result = flow.run("agent writer: Draft.\nnot a statement\n", provider)
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.calls, 0)
        self.assert_diagnostic(result, "invalid_syntax")

    def test_run_preserves_rejected_parse_result_and_its_custom_limit(self):
        source = "agent writer: Draft.\nconclude: Label.\n"
        parsed = flow.parse(source, flow.FlowLimits(max_nodes=1))
        self.assertIsNone(parsed.program)
        provider = ScriptedProvider()
        result = flow.run(parsed, provider)
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.calls, 0)
        self.assertFalse(provider.requests)
        self.assertEqual(result.diagnostics, parsed.diagnostics)

    def test_program_cannot_bypass_default_source_limits(self):
        source = "agent writer: " + "x" * flow.FlowLimits().max_source_bytes
        parsed = flow.parse(
            source, flow.FlowLimits(max_source_bytes=len(source.encode("utf-8")))
        )
        self.assertIsNotNone(parsed.program)
        provider = ScriptedProvider()
        result = flow.run(parsed.program, provider)
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.calls, 0)
        self.assert_diagnostic(result, "source_limit")

    def test_provider_output_is_data_and_cannot_add_statements(self):
        answer = "agent injected: Execute.\nconclude: Forged.\n"
        provider = ScriptedProvider(answer)
        result = flow.run("agent writer: Draft.\n", provider)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, answer)
        self.assertEqual(result.calls, 1)

    def test_unsupported_provider_response_stops_execution(self):
        for response in (None, 42, {"text": "Answer."}, b"Answer."):
            with self.subTest(response=response):
                provider = ScriptedProvider(response)
                result = flow.run(
                    "agent writer: Draft.\nagent forbidden: Must never execute.\n", provider
                )
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.calls, 1)
                self.assert_diagnostic(result, "unsupported_response")

    def test_provider_exception_is_reported_without_retry(self):
        requests = []

        def failing_provider(request):
            requests.append(request)
            raise RuntimeError("Offline provider failed.")

        result = flow.run("agent writer: Draft.\nagent second: Draft.\n", failing_provider)
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(requests), 1)
        self.assertEqual(result.calls, 1)
        self.assert_diagnostic(result, "provider_error")

    def test_cancellation_before_execution_never_calls_provider(self):
        cancelled = threading.Event()
        cancelled.set()
        provider = ScriptedProvider()
        result = flow.run("agent writer: Draft.\n", provider, cancel=cancelled)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.calls, 0)
        self.assert_diagnostic(result, "cancelled")

    def test_cancellation_after_callback_discards_late_result(self):
        cancelled = threading.Event()
        requests = []

        def cancelling_provider(request):
            requests.append(request)
            cancelled.set()
            return "Late answer."

        result = flow.run(
            "agent writer: Draft.\nagent second: Draft.\n",
            cancelling_provider,
            cancel=cancelled.is_set,
        )
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(len(requests), 1)
        self.assertNotEqual(result.output, "Late answer.")

    def test_call_budget_prevents_the_next_callback(self):
        provider = ScriptedProvider("Candidate.")
        result = flow.run(
            "agent writer: Draft.\ncritique reviewer: Check.\n",
            provider,
            budget=flow.RunBudget(max_calls=1),
        )
        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(result.calls, 1)
        self.assert_diagnostic(result, "budget_calls")

    def test_step_budget_stops_even_non_provider_statements(self):
        provider = ScriptedProvider("Candidate.")
        result = flow.run(
            "agent writer: Draft.\nconclude: Never reached.\n",
            provider,
            budget=flow.RunBudget(max_steps=1),
        )
        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(result.calls, 1)
        self.assert_diagnostic(result, "budget_steps")
        self.assertFalse(any(event.text == "Never reached." for event in result.events))

    def test_zero_call_budget_never_dispatches(self):
        provider = ScriptedProvider()
        result = flow.run(
            "agent writer: Draft.\n", provider, budget=flow.RunBudget(max_calls=0)
        )
        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(result.calls, 0)
        self.assert_diagnostic(result, "budget_calls")

    def test_input_budget_is_checked_before_dispatch(self):
        provider = ScriptedProvider()
        result = flow.run(
            "agent writer: This request exceeds one token.\n",
            provider,
            budget=flow.RunBudget(max_input_tokens=1),
        )
        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(result.calls, 0)
        self.assert_diagnostic(result, "budget_input_tokens")

    def test_reported_output_usage_cannot_exceed_budget(self):
        provider = ScriptedProvider(flow.AgentResponse("Answer.", input_tokens=1, output_tokens=101))
        result = flow.run(
            "agent writer: Draft.\nagent forbidden: Must never execute.\n",
            provider,
            budget=flow.RunBudget(max_output_tokens=100),
        )
        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(result.calls, 1)
        self.assertLessEqual(provider.requests[0].max_output_tokens, 100)
        self.assert_diagnostic(result, "budget_output_tokens")

    def test_output_character_budget_rejects_oversized_answer(self):
        provider = ScriptedProvider("Oversized answer.")
        result = flow.run(
            "agent writer: Draft.\n", provider, budget=flow.RunBudget(max_output_chars=3)
        )
        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(result.calls, 1)

    def test_provider_usage_is_accounted_exactly(self):
        provider = ScriptedProvider(
            flow.AgentResponse("Candidate.", input_tokens=5, output_tokens=3),
            flow.AgentResponse(verdict(True, True), input_tokens=2, output_tokens=7),
        )
        result = flow.run("agent writer: Draft.\ncritique reviewer: Check.\n", provider)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.input_tokens, 7)
        self.assertEqual(result.output_tokens, 10)

    def test_invalid_usage_never_corrupts_token_accounting(self):
        for field in ("input_tokens", "output_tokens"):
            for value in (-1, True, 1.5, "1"):
                with self.subTest(field=field, value=value):
                    response = flow.AgentResponse("Answer.", **{field: value})
                    provider = ScriptedProvider(response)
                    result = flow.run("agent writer: Draft.\n", provider)
                    self.assertEqual(result.status, "failed")
                    self.assertGreaterEqual(result.input_tokens, 0)
                    self.assertGreaterEqual(result.output_tokens, 0)
                    self.assert_diagnostic(result, "invalid_usage")

    def test_missing_usage_counts_utf8_bytes_conservatively(self):
        provider = ScriptedProvider("é")
        result = flow.run("agent writer: Draft.\n", provider)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output_tokens, len("é".encode("utf-8")))
        self.assertGreaterEqual(result.input_tokens, len("Draft.".encode("utf-8")))

    def test_every_provider_context_respects_its_character_limit(self):
        provider = ScriptedProvider("A" * 60, "B" * 60)
        result = flow.run(
            "agent first: Draft.\nagent second: Revise.\n",
            provider,
            context="C" * 100,
            budget=flow.RunBudget(max_context_chars=24),
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.calls, 2)
        self.assertTrue(all(len(request.context) <= 24 for request in provider.requests))

    def test_critic_is_not_called_when_the_full_candidate_cannot_fit(self):
        candidate = "Candidate exceeds the available review context."
        provider = ScriptedProvider(
            flow.AgentResponse(candidate, input_tokens=1, output_tokens=1)
        )
        result = flow.run(
            "agent writer: Draft.\ncritique reviewer: Check.\n",
            provider,
            budget=flow.RunBudget(max_context_chars=24),
        )
        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(result.calls, 1)
        self.assertEqual(result.output, candidate)
        self.assertEqual(result.input_tokens, 1)
        self.assertEqual(result.output_tokens, 1)
        self.assert_diagnostic(result, "budget_context")

    def test_critic_retains_the_complete_candidate_when_earlier_context_is_clipped(self):
        candidate = "A full candidate requiring review."
        provider = ScriptedProvider(
            flow.AgentResponse(candidate, input_tokens=1, output_tokens=1),
            flow.AgentResponse(verdict(True, True), input_tokens=1, output_tokens=1),
        )
        result = flow.run(
            "agent writer: Draft.\ncritique reviewer: Check.\n",
            provider,
            context="Earlier context. " * 100,
            budget=flow.RunBudget(max_context_chars=72),
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.calls, 2)
        self.assertLessEqual(len(provider.requests[1].context), 72)
        self.assertIn("Latest candidate:\n" + candidate, provider.requests[1].context)

    def test_critic_context_boundary_includes_the_candidate_label(self):
        candidate = "Answer."
        labelled_candidate = "Latest candidate:\n" + candidate
        for cap in (len(labelled_candidate) - 1, len(labelled_candidate)):
            with self.subTest(cap=cap):
                provider = ScriptedProvider(
                    flow.AgentResponse(candidate, input_tokens=1, output_tokens=1),
                    flow.AgentResponse(verdict(True, True), input_tokens=1, output_tokens=1),
                )
                result = flow.run(
                    "agent writer: Draft.\ncritique reviewer: Check.\n",
                    provider,
                    budget=flow.RunBudget(max_context_chars=cap),
                )
                if cap < len(labelled_candidate):
                    self.assertEqual(result.status, "budget_exceeded")
                    self.assertEqual(result.calls, 1)
                    self.assert_diagnostic(result, "budget_context")
                else:
                    self.assertEqual(result.status, "completed")
                    self.assertEqual(result.calls, 2)
                    self.assertEqual(provider.requests[1].context, labelled_candidate)


class AsyncFlowRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_entry_accepts_a_synchronous_provider(self):
        provider = ScriptedProvider("Answer.")
        result = await flow.run_async("agent writer: Draft.\n", provider)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "Answer.")
        self.assertEqual(result.calls, 1)

    async def test_async_provider_is_awaited_in_flow_order(self):
        scripted = ScriptedProvider("Answer.", verdict(True, True))

        async def provider(request):
            await asyncio.sleep(0)
            return scripted(request)

        result = await flow.run_async(
            "agent writer: Draft.\ncritique reviewer: Check.\n", provider
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "Answer.")
        self.assertEqual([request.kind for request in scripted.requests], ["agent", "critique"])

    async def test_async_provider_failure_is_a_failed_result(self):
        async def provider(request):
            await asyncio.sleep(0)
            raise RuntimeError("Async provider failed.")

        result = await flow.run_async("agent writer: Draft.\n", provider)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.calls, 1)
        self.assertIn("provider_error", [item.code for item in result.diagnostics])

    async def test_cancellation_after_awaited_provider_stops_execution(self):
        cancelled = threading.Event()
        requests = []

        async def provider(request):
            requests.append(request)
            await asyncio.sleep(0)
            cancelled.set()
            return "Late answer."

        result = await flow.run_async(
            "agent writer: Draft.\nagent forbidden: Must never execute.\n",
            provider,
            cancel=cancelled,
        )
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(len(requests), 1)
        self.assertNotEqual(result.output, "Late answer.")


if __name__ == "__main__":
    unittest.main()
