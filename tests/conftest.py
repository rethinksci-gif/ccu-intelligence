import socket

import httpx
import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """No test may reach the network: real HTTP transports, DNS and socket connections all fail loudly."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must never use the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
