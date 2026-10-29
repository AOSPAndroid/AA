"""Atlas Companion: runs in your normal Windows account, next to Outlook and your clipboard.

Atlas Admin runs elevated under another account and cannot see either. The Companion:
- listens to the Windows clipboard and sends every copy (text, a copied screenshot, copied file
  names) to Atlas's clipboard history, skipping copies password managers mark as private;
- when Outlook is switched on in Atlas (Live Inbox > Email watcher), reads new classic Outlook mail
  in this session and sends it to Live Inbox;
- shows a tray icon: Open Atlas, Pause clipboard, Quit.

Start it with windows\\Start-Atlas-Companion.bat as yourself (not "Run as administrator"). It reads the
address and key Atlas writes to %ProgramData%\\Atlas\\Companion\\connection.json, keeps its own state
in %LOCALAPPDATA%\\Atlas\\Companion and logs there without any clipboard or mail content.
"""
import ctypes
import logging
import logging.handlers
import os
import queue
import socket
import struct
import sys
import threading
import time
import webbrowser
from datetime import timedelta
from pathlib import Path

from backend.companion import companion_core as core

HOME = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Atlas' / 'Companion'
WM_CLIPBOARDUPDATE, WM_TIMER, WM_COMMAND, WM_USER, WM_APP = 0x031D, 0x0113, 0x0111, 0x0400, 0x8000
TRAY, REFRESH = WM_USER + 20, WM_APP + 1
DEBOUNCE_MS, CLIP_TIMER = 300, 1
MENU_OPEN, MENU_PAUSE, MENU_QUIT = 1001, 1002, 1003
log = logging.getLogger('atlas.companion')


def user_name():
    return '\\'.join(filter(None, (os.environ.get('USERDOMAIN'), os.environ.get('USERNAME'))))


class Companion:
    def __init__(self):
        import win32api, win32clipboard, win32con, win32gui, pywintypes
        self.api, self.clip, self.con, self.gui, self.pywintypes = win32api, win32clipboard, win32con, win32gui, pywintypes
        self.stop = threading.Event()
        self.settings = {'clipboard': True, 'mail': False}
        self.client = None
        self.atlas = {'state': 'connecting', 'detail': ''}
        self.mail = {'state': 'off', 'detail': '', 'captured': 0, 'last_success_at': None}
        self.outbox = queue.Queue(maxsize=200)
        self.forwarder = core.ClipboardForwarder(None)
        self.hwnd = None
        self.icon_added = False

    # Connection and check-in -------------------------------------------------------------
    def connect(self):
        url, token = core.read_connection()
        if not self.client or self.client.token != token or self.client.url != url:
            self.client = core.Client(url, token)
            self.forwarder.client = self.client
        return self.client

    def heartbeat(self):
        failures = 0
        while not self.stop.is_set():
            try:
                client = self.connect()
                self.settings = core.hello(client, user_name(), socket.gethostname(), self.forwarder.report(), self.mail)
                self.atlas = {'state': 'connected', 'detail': client.url}
                failures = 0
            except core.Offline as error:
                failures += 1
                self.atlas = {'state': 'waiting', 'detail': str(error)}
                log.info('Atlas unavailable: %s', error)
            self.refresh()
            core.sleep_until(self.stop, 15 if not failures else core.backoff(failures))

    # Clipboard ----------------------------------------------------------------------------
    def read_clipboard(self):
        """What the clipboard holds now, read on the window's thread; nothing is logged."""
        clip = self.clip
        for _ in range(10):
            try:
                clip.OpenClipboard(self.hwnd)
                break
            except self.pywintypes.error:
                time.sleep(0.05)  # Another app is still writing it.
        else:
            return {}
        try:
            formats, value = [], 0
            while True:
                value = clip.EnumClipboardFormats(value)
                if not value:
                    break
                formats.append(value)
            names = set()
            for value in formats:
                if value >= 0xC000:
                    try:
                        names.add(clip.GetClipboardFormatName(value))
                    except self.pywintypes.error:
                        pass
            no_history = None
            history = clip.RegisterClipboardFormat(core.NO_HISTORY)
            if history in formats:
                data = clip.GetClipboardData(history)
                no_history = struct.unpack_from('<I', data)[0] if isinstance(data, bytes) and len(data) >= 4 else None
            if core.private(names, no_history):
                return {'private': True}
            if clip.CF_UNICODETEXT in formats:
                return {'text': clip.GetClipboardData(clip.CF_UNICODETEXT)}
            if clip.CF_DIB in formats:
                return {'image': core.dib_to_bmp(clip.GetClipboardData(clip.CF_DIB))}
            if self.con.CF_HDROP in formats:
                return {'files': list(clip.GetClipboardData(self.con.CF_HDROP))}
            return {}
        except (self.pywintypes.error, ValueError, TypeError) as error:
            log.info('Clipboard read skipped: %s', type(error).__name__)
            return {}
        finally:
            clip.CloseClipboard()

    def sender(self):
        while not self.stop.is_set():
            try:
                content = self.outbox.get(timeout=0.5)
            except queue.Empty:
                continue
            if not self.settings.get('clipboard', True) or not self.client:
                continue
            try:
                self.forwarder.handle(content)
            except core.Offline as error:
                log.info('Clipboard copy not delivered: %s', error)
            self.refresh()

    # Outlook ------------------------------------------------------------------------------
    def mail_loop(self):
        from backend.inbox import outlook_watcher as outlook
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        mailbox = None
        try:
            while not self.stop.is_set():
                if not self.settings.get('mail') or not self.client:
                    self.mail.update(state='off', detail='Switch on Email watcher in Atlas Live Inbox.')
                    core.sleep_until(self.stop, 5)
                    continue
                try:
                    if mailbox is None:
                        mailbox = outlook.MailQueue(HOME / 'mail', outlook.utcnow() - timedelta(hours=24))
                    inbox = outlook.OutlookInbox(mailbox.get('config'), mailbox.get('identity'))
                    self.mail.update(state='scanning', detail='')
                    outlook.scan(mailbox, inbox, outlook.utcnow(), self.stop.is_set)
                    inbox = None
                    sent = core.MailForwarder(mailbox, self.client).forward()
                    self.mail.update(state='watching', detail='', last_success_at=outlook.stamp(outlook.utcnow()),
                                     captured=self.mail['captured'] + sent)
                except outlook.OutlookUnavailable as error:
                    self.mail.update(state='waiting_for_outlook', detail=str(error))
                except outlook.StopRequested:
                    break
                except core.Offline as error:
                    self.mail.update(state='waiting_for_atlas', detail=str(error))
                except pythoncom.com_error as error:
                    self.mail.update(state='retrying', detail=f'Outlook read failed (0x{error.hresult & 0xffffffff:08X}); retrying.')
                except Exception as error:  # Never stop the Companion for one bad pass; no mail content is logged.
                    log.exception('Mail pass failed')
                    self.mail.update(state='retrying', detail=f'{type(error).__name__}; retrying.')
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and not self.stop.is_set():
                    pythoncom.PumpWaitingMessages()
                    time.sleep(0.25)
        finally:
            if mailbox is not None:
                mailbox.close()
            pythoncom.CoUninitialize()

    # Window, clipboard listener and tray --------------------------------------------------
    def tooltip(self):
        clipboard = 'paused' if self.forwarder.paused else f'{self.forwarder.captured} copies sent'
        atlas = 'connected' if self.atlas['state'] == 'connected' else 'waiting for Atlas'
        return f'Atlas Companion · {atlas} · clipboard {clipboard}'[:127]

    def refresh(self):
        if self.hwnd:
            self.gui.PostMessage(self.hwnd, REFRESH, 0, 0)

    def show_icon(self, message=None):
        gui, con = self.gui, self.con
        icon_path = Path(__file__).resolve().parents[2] / 'resources' / 'atlas-companion.ico'
        try:
            icon = gui.LoadImage(0, str(icon_path), con.IMAGE_ICON, 0, 0, con.LR_LOADFROMFILE | con.LR_DEFAULTSIZE)
        except self.pywintypes.error:
            icon = gui.LoadIcon(0, con.IDI_APPLICATION)
        flags = gui.NIF_ICON | gui.NIF_MESSAGE | gui.NIF_TIP
        data = (self.hwnd, 0, flags, TRAY, icon, self.tooltip())
        gui.Shell_NotifyIcon(message or (gui.NIM_MODIFY if self.icon_added else gui.NIM_ADD), data)
        self.icon_added = True

    def menu(self):
        gui, con = self.gui, self.con
        menu = gui.CreatePopupMenu()
        gui.AppendMenu(menu, con.MF_STRING, MENU_OPEN, 'Open Atlas')
        gui.AppendMenu(menu, con.MF_STRING | (con.MF_CHECKED if self.forwarder.paused else 0), MENU_PAUSE, 'Pause clipboard')
        mail = {'watching': 'Outlook: watching', 'off': 'Outlook: off (switch on in Live Inbox)'}.get(self.mail['state'], 'Outlook: ' + self.mail['state'].replace('_', ' '))
        gui.AppendMenu(menu, con.MF_STRING | con.MF_GRAYED, 0, mail)
        gui.AppendMenu(menu, con.MF_SEPARATOR, 0, '')
        gui.AppendMenu(menu, con.MF_STRING, MENU_QUIT, 'Quit Atlas Companion')
        x, y = gui.GetCursorPos()
        gui.SetForegroundWindow(self.hwnd)
        gui.TrackPopupMenu(menu, con.TPM_LEFTALIGN | con.TPM_BOTTOMALIGN, x, y, 0, self.hwnd, None)
        gui.PostMessage(self.hwnd, con.WM_NULL, 0, 0)

    def open_atlas(self):
        try:
            webbrowser.open((self.client.url if self.client else 'http://127.0.0.1:8770') + '/installer')
        except Exception:
            log.exception('Could not open Atlas')

    def wndproc(self, hwnd, message, wparam, lparam):
        gui, con, user32 = self.gui, self.con, ctypes.windll.user32
        if message == WM_CLIPBOARDUPDATE:
            # Apps often write the clipboard several times in a row: read once it settles.
            user32.SetTimer(hwnd, CLIP_TIMER, DEBOUNCE_MS, None)
            return 0
        if message == WM_TIMER and wparam == CLIP_TIMER:
            user32.KillTimer(hwnd, CLIP_TIMER)
            if self.settings.get('clipboard', True) and not self.forwarder.paused:
                content = self.read_clipboard()
                if content:
                    try:
                        self.outbox.put_nowait(content)
                    except queue.Full:
                        log.info('Clipboard backlog full; a copy was dropped.')
            return 0
        if message == TRAY:
            if lparam in (con.WM_RBUTTONUP, con.WM_CONTEXTMENU):
                self.menu()
            elif lparam == con.WM_LBUTTONDBLCLK:
                self.open_atlas()
            return 0
        if message == REFRESH:
            self.show_icon()
            return 0
        if message == self.taskbar_created:
            self.icon_added = False
            self.show_icon()
            return 0
        if message == WM_COMMAND:
            command = wparam & 0xFFFF
            if command == MENU_OPEN:
                self.open_atlas()
            elif command == MENU_PAUSE:
                self.forwarder.paused = not self.forwarder.paused
                self.refresh()
            elif command == MENU_QUIT:
                gui.DestroyWindow(hwnd)
            return 0
        if message == con.WM_DESTROY:
            user32.RemoveClipboardFormatListener(hwnd)
            if self.icon_added:
                gui.Shell_NotifyIcon(gui.NIM_DELETE, (hwnd, 0))
            self.stop.set()
            gui.PostQuitMessage(0)
            return 0
        return gui.DefWindowProc(hwnd, message, wparam, lparam)

    def run(self):
        gui, con = self.gui, self.con
        self.taskbar_created = gui.RegisterWindowMessage('TaskbarCreated')
        wc = gui.WNDCLASS()
        wc.hInstance = self.api.GetModuleHandle(None)
        wc.lpszClassName = 'AtlasCompanionWindow'
        wc.lpfnWndProc = self.wndproc
        atom = gui.RegisterClass(wc)
        self.hwnd = gui.CreateWindow(atom, 'Atlas Companion', con.WS_OVERLAPPED, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
        if not ctypes.windll.user32.AddClipboardFormatListener(self.hwnd):
            raise OSError('Windows refused the clipboard listener.')
        self.show_icon()
        workers = [threading.Thread(target=target, name=name, daemon=True)
                   for target, name in ((self.heartbeat, 'heartbeat'), (self.sender, 'clipboard'), (self.mail_loop, 'outlook'))]
        for worker in workers:
            worker.start()
        log.info('Atlas Companion %s started for %s', core.VERSION, user_name())
        gui.PumpMessages()
        self.stop.set()
        for worker in workers:
            worker.join(timeout=5)
        log.info('Atlas Companion stopped')


def message_box(text):
    ctypes.windll.user32.MessageBoxW(0, text, 'Atlas Companion', 0x40)


def main():
    if os.name != 'nt':
        print('The Atlas Companion runs on Windows, in your normal account.')
        return 1
    HOME.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(HOME / 'companion.log', maxBytes=512_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    if ctypes.windll.shell32.IsUserAnAdmin():
        message_box('Run the Atlas Companion as yourself, not "Run as administrator": it has to see your own '
                    'Outlook and clipboard. Atlas Admin keeps running elevated as usual.')
        return 1
    try:
        import win32gui  # noqa: F401
    except ImportError:
        message_box('pywin32 is missing for this account. Run windows\\Install-Atlas-Companion.bat once, then start the Companion again.')
        return 1
    from backend.inbox import outlook_watcher
    try:
        with outlook_watcher.process_lock(HOME, 'companion.lock'):
            Companion().run()
    except outlook_watcher.AlreadyRunning:
        message_box('The Atlas Companion is already running: look for its icon in the notification area.')
        return 0
    except Exception:
        log.exception('Atlas Companion stopped unexpectedly')
        message_box(f'The Atlas Companion stopped unexpectedly. Details: {HOME / "companion.log"}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
