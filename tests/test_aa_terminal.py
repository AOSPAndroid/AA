"""Inside AA the terminal is a client of the Admin backend's Axis: same chat, approvals and audit trail.

A real local HTTP server runs the chat API with a stand-in agent; no model, PC or source database is used.
"""
import json
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import uvicorn
from fastapi import FastAPI, HTTPException

from backend import axis_api as api
from axis import aa_client, agent as axis_agent, start as axis_start


class StandIn:
    """Stands in for Axis's Agent: streams thinking, a tool call and an answer; asks approval when told."""
    def __init__(self, *args, **kwargs):
        self.ui = kwargs["ui"]
        self.messages = []
        self.answer_shown = True
        self.approved = None
        StandIn.last = self

    def run(self, message, prefetched=()):
        self.messages.append(message)
        if message == "restart PC1":
            self.approved = self.ui.confirm("restart PC1; unsaved work may be lost")
            self.interface = self.ui.interface
            self.ui.write_response("Approved." if self.approved else "Declined.")
            return ""
        self.ui.write_thinking("Looking it up.")
        self.ui.tool_start("search_atlas", {"query": message})
        self.ui.tool_result("search_atlas", '{"items": []}', 0.1, "a" * 32)
        self.ui.write_response("Nothing found for " + message)
        return ""


class TerminalClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / "test.db").touch()
        backend = SimpleNamespace(ROOT=root, MASTER_DB=root / "test.db", REPO=root / "packages", validate_pc=str.upper,
                                  jobs={}, lock=threading.RLock(), recent_deployments=lambda: {"deployments": []},
                                  reboot_monitor=SimpleNamespace(snapshot=lambda: {"reboots": []}),
                                  job_service=SimpleNamespace(unresolved=set()))
        app = FastAPI()

        def check_token(request):
            if request.headers.get("X-Atlas-Token") != "test-token":
                raise HTTPException(403, "Token required")

        @app.get("/api/session")
        def session():
            return {"token": "test-token"}

        api.register(app, backend, check_token)
        app.state.axis_sessions.factory = StandIn
        cls.model = patch.object(api, "model_status", return_value={"ready": True, "model": "test-model", "message": ""})
        cls.settings = patch.object(api, "model_settings", return_value={"think": True, "ctx": 8192, "sampling": {}})
        cls.model.start(); cls.settings.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 10
        while not cls.server.started and time.monotonic() < deadline:
            time.sleep(0.02)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.model.stop(); cls.settings.stop()
        cls.temp.cleanup()

    def chat(self, approve=True):
        ui = MagicMock()
        ui.confirm.return_value = approve
        return aa_client.AAChat("http://127.0.0.1:%d" % self.port, ui), ui

    def test_messages_stream_into_the_terminal_and_continue_one_chat(self):
        chat, ui = self.chat()
        self.assertEqual(chat.status()["model"], "test-model")
        chat.send("PC1")
        ui.write_thinking.assert_called_with("Looking it up.")
        ui.tool_start.assert_called_with("search_atlas", {"query": "PC1"})
        self.assertEqual(ui.tool_result.call_args[0][:2], ("search_atlas", '{"items": []}'))
        ui.write_response.assert_called_with("Nothing found for PC1")
        first = chat.session_id
        agent = StandIn.last
        chat.send("PC2")
        self.assertEqual((chat.session_id, StandIn.last), (first, agent), "One conversation, one agent")
        self.assertEqual(agent.messages, ["PC1", "PC2"])

    def test_approvals_are_answered_in_the_terminal_and_audited_as_terminal(self):
        for answer in (True, False):
            with self.subTest(answer=answer):
                chat, ui = self.chat(approve=answer)
                chat.send("restart PC1")
                ui.confirm.assert_called_once_with("restart PC1; unsaved work may be lost")
                self.assertIs(StandIn.last.approved, answer)
                self.assertEqual(StandIn.last.interface, "terminal")

    def test_the_latest_chat_continues_in_the_terminal(self):
        browser, _ = self.chat()
        browser.send("from the map")
        terminal, ui = self.chat()
        transcript = terminal.resume()
        self.assertEqual(terminal.session_id, browser.session_id)
        terminal.replay(transcript)
        ui.user.assert_any_call("from the map")
        terminal.send("and from here")
        self.assertEqual(StandIn.last.messages[-2:], ["from the map", "and from here"])

    def test_without_a_running_aa_the_terminal_says_how_to_start_it(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaisesRegex(aa_client.Unavailable, "Start AA.bat"):
                aa_client.admin_base(empty)
        ui = MagicMock()
        with patch.object(aa_client, "admin_base", side_effect=aa_client.Unavailable(aa_client.NOT_RUNNING)):
            self.assertEqual(aa_client.main([], ui=ui), 1)
        self.assertIn("Start AA.bat", ui.error.call_args[0][0])
        down = aa_client.AAChat("http://127.0.0.1:9", MagicMock())
        with self.assertRaisesRegex(aa_client.Unavailable, "Cannot reach AA"):
            down.status()

    def test_every_way_of_starting_axis_in_aa_uses_the_client(self):
        with patch.object(aa_client, "main", return_value=0) as client, patch.object(axis_agent, "IN_AA", True):
            self.assertEqual(axis_agent.main(["--plain", "hello"]), 0)
            client.assert_called_with(["--plain", "hello"])
        with patch.object(aa_client, "main", return_value=0) as client, patch.object(axis_start, "in_aa", return_value=True), \
                patch.dict(sys.modules, {"aa_client": aa_client}):
            self.assertEqual(axis_start.main(["--resume"]), 0)
            client.assert_called_with(["--resume"])

    def test_a_refused_or_dropped_message_does_not_end_the_terminal(self):
        ui = MagicMock()
        ui.prompt.side_effect = ["first", "second", "/exit"]
        chat = MagicMock(base="http://127.0.0.1:1")
        chat.status.return_value = {"model": "test-model"}
        chat.send.side_effect = [aa_client.Unavailable("AA refused the request (409): This chat is already working."), None]
        with patch.object(aa_client, "earlier_terminal_jobs", return_value=[]):
            self.assertEqual(aa_client.main([], ui=ui, chat=chat), 0)
        self.assertEqual([c.args[0] for c in chat.send.call_args_list], ["first", "second"])
        self.assertIn("already working", ui.error.call_args[0][0])

        class Dropped:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def __iter__(self):
                yield b'data: {"type": "session", "session_id": "s"}\n'
                raise ConnectionResetError("reset by peer")
        broken, _ = self.chat()
        with patch.object(broken, "request", return_value=Dropped()):
            with self.assertRaisesRegex(aa_client.Unavailable, "ended during the answer"):
                broken.send("hello")

    def test_atlas_job_lists_fill_the_terminal_table(self):
        import io
        from axis.terminal_ui import TerminalUI
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, plain=True, verbose=True, width=100)
        ui.tool_result("it_job_status", json.dumps({"jobs": [
            {"job_id": "f" * 32, "kind": "deployment", "state": "launched", "target": "PC7"},
            {"job_id": "e" * 32, "computer": "PC8", "state": "queued"}]}), 0.1)
        text = stream.getvalue()
        for value in ("ffffffffffff", "PC7", "eeeeeeeeeeee", "PC8", "deployment"):
            self.assertIn(value, text)

    def test_one_message_from_the_command_line(self):
        chat, ui = self.chat()
        with patch.object(aa_client, "earlier_terminal_jobs", return_value=[]):
            self.assertEqual(aa_client.main(["--plain", "PC9"], ui=ui, chat=chat), 0)
        ui.write_response.assert_called_with("Nothing found for PC9")


if __name__ == "__main__":
    unittest.main()
