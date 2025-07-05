from __future__ import annotations

import io
import typing
import urllib.parse
import warnings

from twisted.web import client, http, http_headers

if typing.TYPE_CHECKING:
    from twisted.internet import base


class Shortener:
    def __init__(self, reactor: base.ReactorBase, domain: str) -> None:
        self.api_url = (f'https://{domain}/create.php').encode('ascii')
        self.agent = client.Agent(reactor)

    async def shorten(self, url : str) -> str | None:
        payload = {
            'format': 'simple',
            'url': url,
        }
        payload = urllib.parse.urlencode(payload).encode('ascii')

        response = await self.agent.request(b'POST', self.api_url,
            headers=http_headers.Headers({
                'Content-Type': ('application/x-www-form-urlencoded',),
            }), bodyProducer=client.FileBodyProducer(io.BytesIO(payload)))

        if response.code != http.OK:
            return None

        with warnings.catch_warnings():
            # Workaround Twisted bug #8227: https://github.com/twisted/twisted/issues/8227
            warnings.filterwarnings('ignore', category=DeprecationWarning)
            payload = await client.readBody(response)

        return payload.decode('ascii')

def main() -> None:
    import twisted.internet  # noqa: PLC0415
    # Please mypy
    reactor = typing.cast('base.ReactorBase', twisted.internet.reactor)

    url = 'https://example.org'

    s = Shortener(reactor, 'is.gd')
    d = twisted.internet.defer.Deferred.fromCoroutine(s.shorten(url))
    d.addCallback(print).addCallback(lambda _: reactor.stop())
    reactor.run()

if __name__ == '__main__':
    main()
