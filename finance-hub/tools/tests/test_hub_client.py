"""Regression checks for live-but-inaccessible hubs, proxy leakage and event-loop blocking."""
import asyncio
from contextlib import asynccontextmanager
import fcntl
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hub_client as bridge
import hub_common as common
from hub_common import HubPaths


STATE = {"pid": 123, "phase": "ready", "project_id": "finance",
         "health_url": "http://127.0.0.1:8791/healthz",
         "url": "http://127.0.0.1:8791/mcp", "token": "test-secret"}
READY = {"project_id": "finance", "phase": "ready"}


class LifecycleChecks(unittest.TestCase):
    def test_live_unreachable_hub_does_not_spawn_or_delete_state(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = HubPaths(Path(folder))
            paths.prepare()
            paths.state_file.write_text("original")
            with patch.object(bridge, "read_state", return_value=STATE), \
                 patch.object(bridge, "pid_alive", return_value=True), \
                 patch.object(bridge, "health", return_value=None), \
                 patch.object(bridge, "_spawn_hub") as spawn:
                began = time.monotonic()
                with self.assertRaisesRegex(bridge.HubUnavailable, "Not starting a second hub") as error:
                    bridge.ensure_hub(paths, lambda _: None)
                self.assertLess(time.monotonic() - began, .5)
                self.assertNotIn(STATE["token"], str(error.exception))
                spawn.assert_not_called()
                self.assertEqual(paths.state_file.read_text(), "original")

    def test_wrong_project_or_phase_is_not_accepted(self):
        for probe in [{"project_id": "other", "phase": "ready"},
                      {"project_id": "finance", "phase": "starting"}]:
            with patch.object(bridge, "pid_alive", return_value=True), \
                 patch.object(bridge, "health", return_value=probe):
                with self.assertRaises(bridge.HubUnavailable):
                    bridge._ready_state(STATE, "finance")

    def test_healthy_existing_hub_is_reused(self):
        with patch.object(bridge, "pid_alive", return_value=True), \
             patch.object(bridge, "health", return_value=READY):
            self.assertIs(bridge._ready_state(STATE, "finance"), STATE)

    def test_busy_startup_lock_is_bounded_and_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = HubPaths(Path(folder)); paths.prepare()
            paths.lock_file.write_text("other startup")
            with paths.lock_file.open("a") as existing:
                fcntl.flock(existing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                began = time.monotonic()
                with self.assertRaisesRegex(bridge.HubUnavailable, "lock is busy"):
                    with bridge._startup_lock(paths, .01):
                        self.fail("must not acquire another process's lock")
                self.assertLess(time.monotonic() - began, .5)
            self.assertEqual(paths.lock_file.read_text(), "other startup")

    def test_cold_start_child_failure_is_reported_without_waiting(self):
        child = Mock(); child.poll.return_value = 3; child.returncode = 3
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(bridge, "read_state", return_value=None), \
             patch.object(bridge, "_spawn_hub", return_value=child):
            with self.assertRaisesRegex(bridge.HubUnavailable, "exited with code 3"):
                bridge.ensure_hub(HubPaths(Path(folder)), lambda _: None)

    def test_cold_start_accepts_new_matching_healthy_state(self):
        child = Mock(); child.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(bridge, "_hub_settings", return_value=(180, "finance")), \
             patch.object(bridge, "read_state", side_effect=[None, None, STATE]), \
             patch.object(bridge, "health", return_value=READY), \
             patch.object(bridge, "_spawn_hub", return_value=child) as spawn:
            self.assertEqual(bridge.ensure_hub(HubPaths(Path(folder)), lambda _: None), STATE)
            spawn.assert_called_once()

    def test_health_does_not_use_environment_proxy(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"project_id":"finance","phase":"ready"}'
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9"}), \
             patch.object(common.urlrequest, 'build_opener', return_value=opener) as build:
            self.assertEqual(common.health(STATE['health_url'], STATE['token']), READY)
            self.assertEqual(build.call_args.args[0].proxies, {})


class SessionChecks(unittest.IsolatedAsyncioTestCase):
    async def test_socks_environment_is_ignored_for_loopback_session(self):
        seen = []
        @asynccontextmanager
        async def transport(url, *, http_client):
            seen.append(http_client._trust_env)
            yield (None, None, None)
        session = AsyncMock(); session.initialize = AsyncMock()
        session.__aenter__.return_value = session
        handler = AsyncMock(return_value="read-success")
        with patch.dict(os.environ, {"ALL_PROXY": "socks5://127.0.0.1:9"}), \
             patch.object(bridge, "ensure_hub", return_value=STATE), \
             patch.object(bridge, "streamable_http_client", transport), \
             patch.object(bridge, "ClientSession", return_value=session):
            result = await bridge.hub_request(HubPaths(Path('/tmp')), 'codex', 'test',
                                              'test', lambda _: None, handler)
        self.assertEqual(result, "read-success")
        self.assertEqual(seen, [False])
        handler.assert_awaited_once_with(session)

    async def test_synchronous_startup_does_not_block_event_loop(self):
        release = threading.Event()
        def slow_check(*_args):
            if not release.wait(1):
                raise RuntimeError("event loop failed to release startup worker")
            raise bridge.HubUnavailable("expected test stop")
        with patch.object(bridge, "ensure_hub", slow_check):
            task = asyncio.create_task(bridge.hub_request(HubPaths(Path('/tmp')), 'codex',
                                       'test', 'test', lambda _: None, AsyncMock()))
            await asyncio.sleep(.02)
            release.set()
            with self.assertRaisesRegex(bridge.HubUnavailable, "expected test stop"):
                await task


if __name__ == '__main__':
    unittest.main()
