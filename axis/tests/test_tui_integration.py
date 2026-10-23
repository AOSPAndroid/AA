"""Exercise chat/terminal boundaries with no model server or remote Windows PC."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import start
import terminal_ui


def event(delta=None, finish_reason=None):
    return ("data: " + json.dumps({"choices": [{"delta": delta or {}, "finish_reason": finish_reason}]}) + "\n").encode("utf-8")


def tool_call(identifier, name="list_dir", arguments='{"path":"."}'):
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": arguments}}


class TUIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ui = MagicMock()
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            self.agent = agent.Agent("http://127.0.0.1:8080/v1", "test-local-model", str(self.root),
                                     False, False, notes=str(self.root / "notes"),
                                     state_dir=str(self.root / "state"), ui=self.ui)

    def tearDown(self):
        self.temporary.cleanup()

    def test_model_sampling_defaults_reach_the_chat_request(self):
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            configured = agent.Agent("http://127.0.0.1:8080/v1", "test-local-model", str(self.root),
                                     False, True, notes=str(self.root / "notes"),
                                     state_dir=str(self.root / "state"), ui=self.ui,
                                     sampling={"temperature": 1.0, "top_p": 0.92})
        response = MagicMock()
        response.headers = {"Content-Type": "text/event-stream"}
        response.__iter__.return_value = iter([event({"content": "Ready"}), event(finish_reason="stop")])
        with patch.object(configured.http, "open") as open_request:
            open_request.return_value.__enter__.return_value = response
            self.assertEqual(configured.chat()["content"], "Ready")
        body = json.loads(open_request.call_args.args[0].data)
        self.assertEqual(body["temperature"], 1.0)
        self.assertEqual(body["top_p"], 0.92)
        self.assertTrue(body["chat_template_kwargs"]["enable_thinking"])

    def test_cancelling_a_tool_batch_preserves_one_result_per_call(self):
        calls = [tool_call("first"), tool_call("interrupted"), tool_call("not_started")]
        self.agent.chat = Mock(return_value={"role": "assistant", "content": "", "tool_calls": calls})
        self.agent.call_tool = Mock(side_effect=["first action finished", KeyboardInterrupt()])

        with self.assertRaises(KeyboardInterrupt):
            self.agent.run("Inspect the folder")

        replies = [m for m in self.agent.messages if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in replies], ["first", "interrupted", "not_started"])
        self.assertEqual(replies[0]["content"], "first action finished")
        self.assertIn("interrupt", replies[1]["content"].lower())
        self.assertIn("not", replies[2]["content"].lower())
        self.assertEqual(self.agent.call_tool.call_count, 2)

        # The next user request must not inherit unanswered assistant tool calls.
        self.agent.chat = Mock(return_value={"role": "assistant", "content": "Ready", "shown": False})
        self.assertEqual(self.agent.run("What next?"), "Ready")

    def test_result_is_saved_before_terminal_rendering_can_fail(self):
        self.agent.chat = Mock(return_value={"role": "assistant", "content": "", "tool_calls": [tool_call("changed")]})
        self.agent.call_tool = Mock(return_value="The requested action completed")
        self.ui.tool_result.side_effect = RuntimeError("Terminal rendering failed")

        with self.assertRaisesRegex(RuntimeError, "Terminal rendering failed"):
            self.agent.run("Perform the selected action")

        replies = [m for m in self.agent.messages if m["role"] == "tool"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["content"], "The requested action completed")
        saved = self.root / "state" / "outputs" / (self.agent.last_output_id + ".txt")
        self.assertEqual(saved.read_text(encoding="utf-8"), "The requested action completed")
        self.agent.call_tool.assert_called_once()

    def test_partial_tool_call_at_output_limit_is_never_executed(self):
        stream = [
            event({"tool_calls": [{"index": 0, "id": "partial", "type": "function", "function": {
                "name": "run_command", "arguments": '{"command":"Restart-Computer'}}]}),
            event(finish_reason="length"),
            b"data: [DONE]\n",
        ]
        self.agent.chat = Mock(side_effect=lambda: self.agent.read_stream(iter(stream)))
        self.agent.call_tool = Mock()

        with self.assertRaises(RuntimeError):
            self.agent.run("An unfinished request")

        self.agent.call_tool.assert_not_called()
        self.ui.end_response.assert_called()

    def test_raw_eof_without_completion_is_reported_as_incomplete(self):
        with self.assertRaises(RuntimeError):
            self.agent.read_stream(iter([event({"content": "Partial answer"})]))
        self.ui.end_response.assert_called()

    def test_stream_interruption_flushes_reasoning_and_closes_display(self):
        def interrupted():
            yield event({"reasoning_content": "Considering the current state"})
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.agent.read_stream(interrupted())
        self.ui.end_response.assert_called()
        self.ui.end_thinking.assert_called()
        self.ui.write_thinking.assert_called_once_with("Considering the current state")
        self.ui.write_response.assert_not_called()

    def test_reasoning_is_displayed_but_not_fed_back_into_history(self):
        class TTY(io.StringIO):
            def isatty(self):
                return True

        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                stream = TTY()
                with patch.dict(os.environ, {"TERM": "xterm"}, clear=True), \
                     patch.object(terminal_ui, "_enable_vt", return_value=True):
                    ui = terminal_ui.TerminalUI(stream=stream, verbose=verbose)
                self.agent.ui = ui
                self.agent.think = True

                def model_stream():
                    worker = ui._activity.thread
                    yield event({"reasoning_content": "Visible deliberation"})
                    self.assertFalse(worker.is_alive())
                    self.assertIn("Visible deliberation", stream.getvalue())
                    # Inline thinking from other server templates is displayed too,
                    # even with tags split across chunks.
                    for piece in ("<thi", "nk>Visible inline reasoning", "</thi", "nk>", "Ready", "."):
                        yield event({"content": piece})
                    yield event(finish_reason="stop")

                self.agent.chat = Mock(side_effect=lambda: self.agent.read_stream(model_stream()))
                self.assertEqual(self.agent.run("Check status"), "Ready.")
                self.assertIsNone(ui._activity)
                output = terminal_ui.clean_text(stream.getvalue())
                self.assertIn("Ready.", output)
                self.assertEqual(output.count("Visible deliberation"), 1)
                self.assertEqual(output.count("Visible inline reasoning"), 1)
                self.assertNotIn("<think>", output)
                self.assertNotIn("</think>", output)
                self.assertNotIn("Visible", json.dumps(self.agent.messages))

    def test_reasoning_display_clears_on_interruption_and_output_limit(self):
        class TTY(io.StringIO):
            def isatty(self):
                return True

        for failure in (KeyboardInterrupt, RuntimeError):
            with self.subTest(failure=failure):
                stream = TTY()
                with patch.dict(os.environ, {"TERM": "xterm"}, clear=True), \
                     patch.object(terminal_ui, "_enable_vt", return_value=True):
                    ui = terminal_ui.TerminalUI(stream=stream)
                self.agent.ui = ui
                self.agent.think = True
                workers = []

                def model_stream():
                    workers.append(ui._activity.thread)
                    yield event({"reasoning_content": "Visible deliberation"})
                    workers.append(ui._activity.thread)
                    if failure is KeyboardInterrupt:
                        raise KeyboardInterrupt()
                    yield event(finish_reason="length")

                self.agent.chat = Mock(side_effect=lambda: self.agent.read_stream(model_stream()))
                with self.assertRaises(failure):
                    self.agent.run("Check status")
                self.assertIsNone(ui._activity)
                self.assertTrue(all(not worker.is_alive() for worker in workers))
                self.assertIn("Visible deliberation", stream.getvalue())

    def test_non_streaming_response_displays_thinking_and_answer_once(self):
        stream = io.StringIO()
        self.agent.ui = terminal_ui.TerminalUI(stream=stream, plain=True)
        response = MagicMock()
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "reasoning_content": "Visible deliberation", "content": "Ready."}}]}).encode()
        with patch.object(self.agent.http, "open") as opened:
            opened.return_value.__enter__.return_value = response
            self.assertEqual(self.agent.run("Check status"), "Ready.")
        self.assertTrue(self.agent.answer_shown)
        self.assertEqual(stream.getvalue().count("Visible deliberation"), 1)
        self.assertEqual(stream.getvalue().count("Ready."), 1)
        self.assertNotIn("Visible deliberation", json.dumps(self.agent.messages))

    def test_fragmented_tool_arguments_are_assembled_before_dispatch(self):
        stream = [
            event({"tool_calls": [{"index": 0, "id": "complete", "type": "function", "function": {
                "name": "list_", "arguments": '{"path":'}}]}),
            event({"tool_calls": [{"index": 0, "function": {"name": "dir", "arguments": '"."}'}}]}),
            event(finish_reason="tool_calls"),
            b"data: [DONE]\n",
        ]
        result = self.agent.read_stream(iter(stream))
        self.assertEqual(result["tool_calls"], [tool_call("complete")])

    def test_normal_stop_without_done_sentinel_is_a_valid_response(self):
        result = self.agent.read_stream(iter([event({"content": "Hello"}), event(finish_reason="stop")]))
        self.assertEqual(result["content"], "Hello")
        self.ui.end_response.assert_called()

    def test_local_status_jobs_help_and_exit_do_not_invoke_the_model(self):
        self.agent.chat = Mock()
        for command in ("/help", "/status", "/jobs"):
            with self.subTest(command=command):
                self.assertTrue(agent.handle_command(self.agent, self.ui, command, []))
        self.assertFalse(agent.handle_command(self.agent, self.ui, "/exit", []))
        self.agent.chat.assert_not_called()
        self.ui.help.assert_called_once()
        self.ui.config.assert_called()
        self.ui.jobs.assert_called()

    def test_reset_keeps_saved_output_available(self):
        self.agent.save_output("Saved inspection result")
        output_id = self.agent.last_output_id
        self.agent.messages.append({"role": "user", "content": "Old request"})
        self.assertTrue(agent.handle_command(self.agent, self.ui, "/reset", []))
        self.assertEqual(len(self.agent.messages), 1)
        saved = self.root / "state" / "outputs" / (output_id + ".txt")
        self.assertEqual(saved.read_text(encoding="utf-8"), "Saved inspection result")


class LauncherIntegrationTests(unittest.TestCase):
    def test_parent_interrupt_does_not_stop_a_child_that_is_still_chatting(self):
        child = MagicMock()
        child.wait.side_effect = [KeyboardInterrupt(), 0]
        command = [sys.executable, "agent.py"]
        with patch.object(start.subprocess, "Popen", return_value=child) as popen:
            self.assertEqual(start.wait_for_agent(command), 0)
        self.assertEqual(child.wait.call_count, 2)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], command)
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_owned_model_server_is_isolated_from_chat_console_interrupts(self):
        with tempfile.TemporaryDirectory() as folder:
            process = MagicMock()
            process.poll.return_value = None
            with patch.object(start, "HERE", folder), patch.object(start, "server_ready", return_value=True), patch.object(start.subprocess, "Popen", return_value=process) as popen:
                result = start.start_server(str(Path(folder) / "llama-server.exe"),
                                            str(Path(folder) / "model.gguf"), 16384, False,
                                            alias="selected-model")
            self.assertIs(result, process)
            command = popen.call_args.args[0]
            self.assertEqual(command[command.index("--alias") + 1], "selected-model")
            self.assertNotIn("--reasoning-budget", command)
            options = popen.call_args.kwargs
            if os.name == "nt":
                flags = options.get("creationflags", 0)
                self.assertTrue(flags & start.subprocess.CREATE_NEW_PROCESS_GROUP)
                self.assertTrue(flags & start.subprocess.CREATE_NO_WINDOW)
            else:
                self.assertTrue(options.get("start_new_session"))

    def test_launcher_keeps_server_and_agent_thinking_settings_in_sync(self):
        for options, expected in (([], True), (["--think"], True), (["--no-think"], False)):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as folder:
                process = MagicMock()
                with patch.object(start, "prepare_model", return_value=("35b", "model.gguf")), \
                     patch.object(start, "server_ready", return_value=False), \
                     patch.object(start, "gpus", return_value=[]), \
                     patch.object(start, "find_server", return_value="llama-server.exe"), \
                     patch.object(start, "start_server", return_value=process) as server, \
                     patch.object(start, "wait_for_agent", return_value=0) as launch, \
                     patch.object(start, "log"):
                    self.assertEqual(start.main(["--workdir", folder] + options), 0)
                self.assertEqual(server.call_args.kwargs["think"], expected)
                command = launch.call_args.args[0]
                self.assertIn("--think" if expected else "--no-think", command)
                self.assertNotIn("--no-think" if expected else "--think", command)
                self.assertNotIn("--verbose", command)

    def test_direct_chat_defaults_to_thinking_and_allows_opt_out(self):
        for options, expected in (([], True), (["--no-think"], False)):
            with self.subTest(options=options):
                ui = MagicMock()
                ui.prompt.return_value = "/exit"
                with patch.object(agent, "Agent") as factory, \
                     patch.object(agent, "TerminalUI", return_value=ui), \
                     patch.object(agent.threading, "Thread"):
                    self.assertEqual(agent.main(options), 0)
                self.assertEqual(factory.call_args.args[4], expected)


if __name__ == "__main__":
    unittest.main()
