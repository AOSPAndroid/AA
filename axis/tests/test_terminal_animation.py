"""Animation lifecycle, buffered delivery and startup cancellation without a model."""
import io
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import start
import terminal_ui as terminal


class TTY(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flushes = 0
        self.tail_seen = threading.Event()

    def isatty(self):
        return True

    def flush(self):
        self.flushes += 1

    def write(self, value):
        result = super().write(value)
        if "pending-tail" in value:
            self.tail_seen.set()
        return result


def animated_ui(stream, **kwargs):
    with patch.dict(os.environ, {"TERM": "xterm"}, clear=True), patch.object(terminal, "_enable_vt", return_value=True):
        return terminal.TerminalUI(stream=stream, **kwargs)


class AnimationTests(unittest.TestCase):
    def test_stream_batches_console_writes_without_losing_text(self):
        stream = TTY()
        ui = animated_ui(stream)
        pieces = ["word "] * 2000
        try:
            for piece in pieces:
                ui.write_response(piece)
        finally:
            ui.end_response()
        self.assertIn("".join(pieces), terminal.clean_text(stream.getvalue()))
        self.assertLess(stream.flushes, len(pieces) // 10)
        self.assertIsNone(ui._activity)

    def test_pending_text_flushes_even_when_the_model_pauses(self):
        for thinking in (False, True):
            with self.subTest(thinking=thinking):
                stream = TTY()
                ui = animated_ui(stream)
                write = ui.write_thinking if thinking else ui.write_response
                try:
                    write("First fragment ")
                    write("pending-tail")
                    self.assertTrue(stream.tail_seen.wait(1.0), "Buffered text was stranded during a network pause")
                finally:
                    ui.end_thinking()
                    ui.end_response()
                self.assertIsNone(ui._activity)

    def test_approval_stops_stream_worker_and_flushes_tail_before_input(self):
        for thinking in (False, True):
            with self.subTest(thinking=thinking):
                stream = TTY()
                observed = []
                ui = animated_ui(stream, input_fn=lambda _: observed.append(
                    (ui._activity, "pending-tail" in stream.getvalue())) or "n")
                write = ui.write_thinking if thinking else ui.write_response
                write("First ")
                worker = ui._activity.thread
                write("pending-tail")
                self.assertFalse(ui.confirm("Restart LAB-PC-042"))
                self.assertEqual(observed, [(None, True)])
                self.assertFalse(worker.is_alive())

    def test_plain_no_color_and_dumb_terminals_have_no_motion_or_delay(self):
        for options, env in (({"plain": True}, {}), ({}, {"NO_COLOR": "1"}), ({}, {"TERM": "dumb"})):
            with self.subTest(options=options, env=env):
                stream = TTY()
                with patch.dict(os.environ, env, clear=True), patch.object(terminal, "_enable_vt", return_value=True):
                    ui = terminal.TerminalUI(stream=stream, **options)
                with patch.object(terminal.time, "sleep") as delay:
                    ui.startup("Fixture model")
                    with ui.status("Loading"):
                        self.assertIsNone(ui._activity)
                    ui.write_response("pending-tail")
                    self.assertTrue(stream.tail_seen.is_set())
                    ui.end_response()
                delay.assert_not_called()
                self.assertNotIn("\x1b", stream.getvalue())
                self.assertNotIn("\r", stream.getvalue())

    def test_spinner_frames_fit_terminal_without_an_activity_bar(self):
        for width in (20, 30, 62, 110):
            ui = animated_ui(TTY(), width=width)
            for tick in range(40):
                frame = ui._activity_frame("Loading model with a long name \u4e16\u754c", tick, 130)
                self.assertLess(terminal._width(frame), width)
                self.assertIn("02:10", frame)
                self.assertNotIn("%", frame)
                self.assertNotIn("[", frame)
                self.assertNotIn("=", frame)
            self.assertNotEqual(ui._activity_frame("Loading", 0, 1), ui._activity_frame("Loading", 1, 1))
        self.assertEqual([ui._activity_frame("Thinking", tick, 0).strip() for tick in range(4)],
                         [char + " Thinking  00:00" for char in "|/-\\"])

    def test_failed_thread_start_leaves_no_active_animation(self):
        ui = animated_ui(TTY())
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("Cannot start thread")):
            with self.assertRaises(RuntimeError):
                with ui.status("Loading"):
                    self.fail("Thread creation should have failed")
        self.assertIsNone(ui._activity)

    def test_startup_cancellation_stops_owned_model_server(self):
        stream = TTY()
        ui = animated_ui(stream)
        process = MagicMock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder, patch.object(start, "HERE", folder), \
             patch.object(start.subprocess, "Popen", return_value=process), \
             patch.object(start, "server_ready", return_value=False), \
             patch.object(start.time, "sleep", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                start.start_server(str(Path(folder) / "llama-server.exe"), "model.gguf", 16384, False, ui=ui)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(10)
        process.kill.assert_not_called()
        self.assertIsNone(ui._activity)

    def test_plain_mode_reaches_startup_and_chat(self):
        process = MagicMock()
        with tempfile.TemporaryDirectory() as folder, patch.object(start, "TerminalUI") as ui, \
             patch.object(start, "prepare_model", return_value=("35b", "model.gguf")), \
             patch.object(start, "server_ready", return_value=False), patch.object(start, "gpus", return_value=[]), \
             patch.object(start, "find_server", return_value="llama-server.exe"), \
             patch.object(start, "start_server", return_value=process) as server, \
             patch.object(start, "wait_for_agent", return_value=0) as launch, patch.object(start, "log"):
            self.assertEqual(start.main(["--workdir", folder, "--plain"]), 0)
        ui.assert_called_once_with(plain=True)
        self.assertIs(server.call_args.kwargs["ui"], ui.return_value)
        self.assertIn("--plain", launch.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
