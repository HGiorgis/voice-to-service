"""
Interactive terminal WebSocket consumer. Spawns a PTY shell so commands
like `python manage.py createsuperuser` can receive stdin.
PTY is Unix-only; on Windows the terminal page loads but shell is unavailable.
"""
import os
import sys
import threading
import queue
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer


class TerminalConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.master_fd = None
        self.pid = None
        self.output_queue = queue.Queue()
        self._closed = threading.Event()

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not getattr(user, "is_staff", False):
            await self.close(code=4003)
            return
        await self.accept()
        # Spawn PTY in a thread (fork can't run in async)
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, self._spawn_pty)
        if not ok:
            msg = "\r\nInteractive shell is not available on Windows. Use Docker or Linux.\r\n"
            if sys.platform != "win32":
                msg = "\r\nFailed to spawn shell.\r\n"
            await self.send(text_data=msg)
            await self.close()
            return
        # Start thread that reads from PTY and puts in queue
        t = threading.Thread(target=self._read_pty_loop, daemon=True)
        t.start()
        # Send initial prompt by writing newline to pty
        try:
            if self.master_fd is not None:
                os.write(self.master_fd, b"\r\n")
        except OSError:
            pass
        # Run sender loop (get from queue and send to client)
        asyncio.create_task(self._sender_loop())

    def _spawn_pty(self):
        if os.name == "nt" or sys.platform == "win32":
            return False
        try:
            import pty
            import select
            master, slave = pty.openpty()
            pid = os.fork()
            if pid == 0:
                os.close(master)
                os.setsid()
                os.dup2(slave, 0)
                os.dup2(slave, 1)
                os.dup2(slave, 2)
                if slave > 2:
                    os.close(slave)
                env = os.environ.copy()
                env["TERM"] = "xterm-256color"
                env["PS1"] = "$ "
                try:
                    os.execve("/bin/bash", ["-i"], env)
                except FileNotFoundError:
                    os.execve("/bin/sh", ["-i"], env)
                os._exit(127)
            os.close(slave)
            self.master_fd = master
            self.pid = pid
            return True
        except Exception:
            return False

    def _read_pty_loop(self):
        import select
        while self.master_fd is not None and not self._closed.is_set():
            try:
                r, _, _ = select.select([self.master_fd], [], [], 0.2)
                if not r:
                    continue
                data = os.read(self.master_fd, 4096)
                if not data:
                    self.output_queue.put(None)  # EOF
                    break
                try:
                    text = data.decode("utf-8", errors="replace")
                    self.output_queue.put(text)
                except Exception:
                    pass
            except (OSError, ValueError):
                self.output_queue.put(None)
                break
        try:
            if self.master_fd is not None:
                os.close(self.master_fd)
        except OSError:
            pass
        self.master_fd = None

    async def _sender_loop(self):
        loop = asyncio.get_event_loop()
        while True:
            try:
                data = await loop.run_in_executor(
                    None, lambda: self.output_queue.get(timeout=0.3)
                )
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if data is None:
                break
            try:
                await self.send(text_data=data)
            except Exception:
                break
        try:
            await self.close()
        except Exception:
            pass

    async def receive(self, text_data=None, bytes_data=None):
        if self.master_fd is None:
            return
        data = text_data or (bytes_data.decode("utf-8", errors="replace") if bytes_data else "")
        if not data:
            return
        try:
            to_send = data if isinstance(data, bytes) else data.encode("utf-8")
            os.write(self.master_fd, to_send)
        except OSError:
            pass

    async def disconnect(self, close_code):
        self._closed.set()
        if self.pid is not None:
            try:
                os.kill(self.pid, 9)
            except OSError:
                pass
            self.pid = None
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None
        self.output_queue.put(None)
