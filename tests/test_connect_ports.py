from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from naoqi_control.log import _StdLog
from naoqi_control.robot import _connect_session, _normalize_ports


class _Session:
    def __init__(self, refused_ports: set[int]) -> None:
        self.url: str | None = None
        self.closed = False
        self._refused_ports = refused_ports

    def connect(self, url: str) -> None:
        port = int(url.rsplit(":", 1)[1])
        if port in self._refused_ports:
            raise RuntimeError("Connect error: 111: Connection refused")
        self.url = url

    def close(self) -> None:
        self.closed = True


class TestConnectPorts(unittest.TestCase):
    def test_default_ports(self) -> None:
        self.assertEqual(_normalize_ports(None), [9559, 9561])
        self.assertEqual(_normalize_ports(9561), [9561])

    def test_skips_connection_refused_and_uses_the_next_port(self) -> None:
        sessions: list[_Session] = []

        def factory() -> _Session:
            session = _Session({9559})
            sessions.append(session)
            return session

        with patch("naoqi_control.robot.qi.Session", side_effect=factory):
            session, port = _connect_session("192.168.2.50", [9559, 9561], _StdLog())

        self.assertEqual(port, 9561)
        self.assertEqual(session.url, "tcp://192.168.2.50:9561")
        self.assertTrue(sessions[0].closed)
        self.assertFalse(sessions[1].closed)

    def test_other_connect_errors_stop_the_search(self) -> None:
        session = MagicMock()
        session.connect.side_effect = RuntimeError("Connect error: timed out")

        with patch("naoqi_control.robot.qi.Session", return_value=session):
            with self.assertRaises(RuntimeError) as ctx:
                _connect_session("192.168.2.50", [9559, 9561], _StdLog())

        self.assertIn("timed out", str(ctx.exception))
        session.close.assert_called_once()

    def test_all_ports_refused(self) -> None:
        with patch("naoqi_control.robot.qi.Session", return_value=_Session({9559, 9561})):
            with self.assertRaises(RuntimeError) as ctx:
                _connect_session("192.168.2.50", [9559, 9561], _StdLog())

        self.assertIn("9559, 9561", str(ctx.exception))
