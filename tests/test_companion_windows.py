"""atlas_companion.py's Windows shell, driven through stand-in pywin32 modules (no Windows here):
clipboard reading order and privacy, the debounce timer, the tray menu and quitting."""
import struct
import sys
import types
import unittest
from unittest.mock import patch


class Fake(types.ModuleType):
    def __getattr__(self, name):
        if name.isupper():
            return hash(name) & 0xFFFF  # Any constant: unique per name.
        raise AttributeError(name)


def modules(clipboard):
    calls = []
    clip = Fake('win32clipboard')
    clip.CF_UNICODETEXT, clip.CF_DIB = 13, 8
    registered = {'CanIncludeInClipboardHistory': 0xC101, 'ExcludeClipboardContentFromMonitorProcessing': 0xC102, 'HTML Format': 0xC103}
    names = {v: k for k, v in registered.items()}
    clip.OpenClipboard = lambda hwnd: calls.append('open')
    clip.CloseClipboard = lambda: calls.append('close')
    order = list(clipboard)
    clip.EnumClipboardFormats = lambda previous: (order[order.index(previous) + 1] if previous in order and order.index(previous) + 1 < len(order) else 0) if previous else (order[0] if order else 0)
    clip.GetClipboardFormatName = lambda value: names[value]
    clip.RegisterClipboardFormat = lambda name: registered[name]
    clip.GetClipboardData = lambda value: clipboard[value]
    con = Fake('win32con'); con.CF_HDROP = 15
    gui = Fake('win32gui')
    for name in ('PostMessage', 'Shell_NotifyIcon', 'AppendMenu', 'SetForegroundWindow', 'TrackPopupMenu', 'DestroyWindow', 'PostQuitMessage'):
        setattr(gui, name, lambda *args, n=name: calls.append(n))
    gui.CreatePopupMenu = lambda: 'menu'
    gui.GetCursorPos = lambda: (10, 10)
    gui.LoadImage = lambda *args: 'icon'
    gui.DefWindowProc = lambda *args: 'default'
    pywintypes = Fake('pywintypes'); pywintypes.error = type('error', (Exception,), {})
    return {'win32api': Fake('win32api'), 'win32clipboard': clip, 'win32con': con, 'win32gui': gui, 'pywintypes': pywintypes}, calls


class WindowsShell(unittest.TestCase):
    def companion(self, clipboard):
        fakes, calls = modules(clipboard)
        patcher = patch.dict(sys.modules, fakes); patcher.start(); self.addCleanup(patcher.stop)
        from backend.companion import atlas_companion
        user32 = types.SimpleNamespace(SetTimer=lambda *a: calls.append('SetTimer'), KillTimer=lambda *a: calls.append('KillTimer'),
                                       RemoveClipboardFormatListener=lambda *a: calls.append('RemoveListener'))
        ctypes = patch.object(atlas_companion.ctypes, 'windll', types.SimpleNamespace(user32=user32), create=True)
        ctypes.start(); self.addCleanup(ctypes.stop)
        companion = atlas_companion.Companion()
        companion.hwnd, companion.taskbar_created = 1, 0xC200
        return atlas_companion, companion, calls

    def test_clipboard_content_in_priority_order(self):
        dib = struct.pack('<IiiHHIIiiII', 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0) + b'\0' * 4
        _, companion, calls = self.companion({0xC103: b'<b>html</b>', 13: 'GBRPWMF20847950', 8: dib})
        self.assertEqual(companion.read_clipboard(), {'text': 'GBRPWMF20847950'}, 'Excel puts text and a picture: text wins')
        self.assertEqual(calls[-1], 'close', 'The clipboard is always closed again')
        _, companion, _ = self.companion({8: dib})
        self.assertEqual(companion.read_clipboard()['image'][:2], b'BM')
        _, companion, _ = self.companion({15: (r'C:\a.txt', r'C:\b.txt')})
        self.assertEqual(companion.read_clipboard(), {'files': [r'C:\a.txt', r'C:\b.txt']})

    def test_password_manager_copies_are_private(self):
        _, companion, _ = self.companion({0xC102: b'', 13: 'hunter2'})
        self.assertEqual(companion.read_clipboard(), {'private': True})
        _, companion, _ = self.companion({0xC101: struct.pack('<I', 0), 13: 'hunter2'})
        self.assertEqual(companion.read_clipboard(), {'private': True})
        _, companion, _ = self.companion({0xC101: struct.pack('<I', 1), 13: 'fine to keep'})
        self.assertEqual(companion.read_clipboard(), {'text': 'fine to keep'})

    def test_window_messages(self):
        module, companion, calls = self.companion({13: 'LAPTOP-0001'})
        self.assertEqual(companion.wndproc(1, module.WM_CLIPBOARDUPDATE, 0, 0), 0)
        self.assertEqual(calls[-1], 'SetTimer', 'Copies are read once the clipboard settles')
        companion.wndproc(1, module.WM_TIMER, module.CLIP_TIMER, 0)
        self.assertEqual(companion.outbox.get_nowait(), {'text': 'LAPTOP-0001'})
        companion.forwarder.paused = True
        companion.wndproc(1, module.WM_TIMER, module.CLIP_TIMER, 0)
        self.assertTrue(companion.outbox.empty(), 'Paused: nothing is read')
        companion.wndproc(1, module.WM_COMMAND, module.MENU_PAUSE, 0)
        self.assertFalse(companion.forwarder.paused)
        con = sys.modules['win32con']
        companion.wndproc(1, module.TRAY, 0, con.WM_RBUTTONUP)
        self.assertIn('TrackPopupMenu', calls)
        self.assertIn('Atlas Companion · waiting for Atlas · clipboard 0 copies sent', companion.tooltip())
        self.assertEqual(companion.wndproc(1, 0x1234, 0, 0), 'default')
        companion.icon_added = True
        companion.wndproc(1, con.WM_DESTROY, 0, 0)
        self.assertTrue(companion.stop.is_set())
        self.assertIn('RemoveListener', calls)
        self.assertIn('PostQuitMessage', calls)


if __name__ == '__main__':
    unittest.main()
