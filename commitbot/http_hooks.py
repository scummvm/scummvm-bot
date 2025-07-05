from __future__ import annotations

import hashlib
import hmac
import json
import typing

from twisted.internet import endpoints
from twisted.web import http, resource, server

if typing.TYPE_CHECKING:
    from collections import abc

    from twisted.internet import base


class Root(resource.Resource):
    def __init__(self) -> None:
        super().__init__()
        self.putChild(b'', self)

    def render_GET(self, _request : server.Request) -> bytes:
        return b"pyGitBot lives here. Direct your hooks to /github.\n"

class GithubHook(resource.Resource):
    isLeaf = True

    def __init__(self, reactor : base.ReactorBase,
                 notify : abc.Callable[[str, str, dict[str, typing.Any]], None],
                 secret : str | None = None) -> None:
        super().__init__()
        self.reactor = reactor
        self.notify = notify
        self.secret = secret

    def render_GET(self, _request : server.Request) -> bytes:
        return b"You found the Github hook!\n"

    def render_POST(self, request : server.Request) -> bytes:
        event = request.getHeader('X-Github-Event')
        assert(request.content)
        payload = request.content.read()
        if self.secret:
            signature = request.getHeader('X-Hub-Signature-256')
            if signature is None:
                request.setResponseCode(http.FORBIDDEN)
                return b'Missing signature\n'
            if not self.checkSignature(payload, signature):
                request.setResponseCode(http.FORBIDDEN)
                return b'Invalid signature\n'

        self.reactor.callLater(0, self.notify, 'github', event, json.loads(payload))
        return b''

    def checkSignature(self, payload : bytes, signature : str) -> bool:
        assert(self.secret)
        h = hmac.new(self.secret.encode('utf-8'), msg=payload, digestmod=hashlib.sha256)
        expected = "sha256=" + h.hexdigest()
        return hmac.compare_digest(expected, signature)

def create(config : abc.MutableMapping[str, str],
           reactor : base.ReactorBase,
           notify : abc.Callable[[str, str, dict[str, typing.Any]], None]) -> None:
    root = Root()
    root.putChild(b'github', GithubHook(reactor, notify, config['github_secret'] or None))
    site = server.Site(root)

    endpoint = endpoints.TCP4ServerEndpoint(reactor, int(config['port']), interface=config['host'])
    endpoint.listen(site)
