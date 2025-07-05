from __future__ import annotations

import base64
import typing

from twisted import logger
from twisted.internet import protocol
from twisted.internet import ssl as tls
from twisted.words.protocols import irc

if typing.TYPE_CHECKING:
    import configparser

    from twisted.internet import abstract, base, posixbase
    from twisted.python import failure


IRC_DEBUG = False

class CommitBot(irc.IRCClient):
    log = logger.Logger()
    factory: CommitBotFactory | None = None
    transport: abstract.FileDescriptor | None = None

    def __init__(self) -> None:
        self.channelsJoined : set[str] = set()
        self.saslTimeout : base.DelayedCall | None = None
        self.saslData : str | None = None

    def notify(self, tag: str, message: str) -> None:
        for channel in self.channelsJoined:
            filt = self.filters.get(channel)
            if filt and tag not in filt:
                continue
            self.msg(channel, message)

    def lineReceived(self, line: bytes) -> typing.Any:  # noqa: ANN401
        if IRC_DEBUG:
            self.log.debug('<<< {line!r}', line=line)
        return super().lineReceived(line)

    def _reallySendLine(self, line: str | bytes) -> typing.Any:  # noqa: ANN401
        if IRC_DEBUG:
            self.log.debug('>>> {line!r}', line=line)
        return super()._reallySendLine(line)

    def connectionMade(self) -> None:
        assert(self.factory)
        config = self.factory.config
        # Variables are not annotated in Twisted and mypy erroneously set them to None
        self.password = config['server_password'] or None # type: ignore[assignment]
        self.nickname = config['nick']
        self.username = config['username']
        self.realname = config['realname'] # type: ignore[assignment]
        self.channelsToJoin = [cp.rsplit(',', maxsplit=1) for cp in config['channels'].split()]

        self.filters : dict[str, list[str]] = {}
        for cp in self.channelsToJoin:
            filt = config.get(f'filter.{cp[0]}')
            if filt is None:
                continue
            self.filters[cp[0]] = [tag for tag in filt.split(' ') if tag]

        self.log.info("Connected")

        if (config['sasl_user'] and
            config['sasl_pass']):
            # Begin capability negotiation: request sasl
            self.log.info("Checking for SASL authentication support")
            self.sendLine('CAP REQ :sasl')

        super().connectionMade()

    def connectionLost(self, reason: failure.Failure = protocol.connectionDone) -> None:
        assert(self.factory)
        self.factory.protocolDead(self)

        super().connectionLost(reason)

        self.log.info("Disconnected")

    # callbacks for events
    def irc_CAP(self, _prefix: str, params: list[str]) -> None:
        subcommand, params = params[1].upper(), params[2:]

        if subcommand == 'NAK':
            # No SASL available
            self.log.info("SASL authentication not supported")
            # End negotiation to finish the register
            self.sendLine('CAP END')
            return

        if subcommand == 'ACK':
            extensions = params[-1].lower().split(' ')
            if 'sasl' not in extensions:
                # No SASL although we requested it: should never happen
                # End negotiation to finish the register
                self.sendLine('CAP END')

            # SASL enabled: authenticate
            self.log.info("SASL authentication started")
            self.saslData = ''
            self.sendLine('AUTHENTICATE PLAIN')
            assert(self.transport)
            reactor = typing.cast('base.ReactorBase', self.transport.reactor)
            self.saslTimeout = reactor.callLater(10, self._saslTimedout)

    def irc_AUTHENTICATE(self, _prefix: str, params: list[str]) -> None:
        if len(params) > 1:
            return
        data = params[0]
        assert(self.saslData is not None)
        self.saslData = self.saslData + data

        SASL_MAX_BLOCK_SIZE : typing.Final[int] = 400
        if len(data) == SASL_MAX_BLOCK_SIZE:
            # More data expected
            return

        data = self.saslData
        self.saslData = ''

        data = base64.b64decode(data) if data != '+' else b''

        out = self.saslAuthenticate(data)

        out = base64.b64encode(out).decode('ascii') if out else '+'

        while len(out) > SASL_MAX_BLOCK_SIZE:
            part, out = out[:SASL_MAX_BLOCK_SIZE], out[SASL_MAX_BLOCK_SIZE:]
            self.sendLine('AUTHENTICATE ' + part)
        if out:
            self.sendLine('AUTHENTICATE ' + out)
        else:
            self.sendLine('AUTHENTICATE +')

    def irc_903(self, _prefix: str, _params: list[str]) -> None: # RPL_SASLSUCCESS
        self.log.info("SASL authentication succeeded")
        # End negotiation to finish the register
        self._saslEnd()

    def irc_904(self, _prefix: str, _params: list[str]) -> None: # ERR_SASLFAIL
        self.log.warn("SASL authentication failed: closing")
        assert(self.transport)
        self.transport.loseConnection()

    def irc_905(self, _prefix: str, _params: list[str]) -> None: # ERR_SASLTOOLONG
        self.log.warn("SASL authentication data was too long")
        # End negotiation to finish the register
        self._saslEnd()

    def irc_906(self, _prefix: str, _params: list[str]) -> None: # ERR_SASLABORTED
        self.log.warn("SASL authentication aborted: closing")
        assert(self.transport)
        self.transport.loseConnection()

    irc_907 = irc_903 # ERR_SASLALREADY

    def _saslEnd(self) -> None:
        if self.saslTimeout:
            self.saslTimeout.cancel()
            self.saslTimeout = None
        # End negotiation to finish the register
        self.sendLine('CAP END')

    def _saslTimedout(self) -> None:
        if self.saslTimeout is None:
            return
        self.saslTimeout = None
        self.log.warn("SASL authentication timed out")
        # End negotiation to finish the register
        self.sendLine('CAP END')

    def signedOn(self) -> None:
        """Called when bot has successfully signed on to server."""
        self.log.info("Signed on")
        assert(self.factory)
        self.factory.protocolReady(self)
        if self.channelsToJoin:
            channel = self.channelsToJoin.pop()
            self.join(*channel)

    def alterCollidedNick(self, nickname: str) -> str:
        assert(self.transport)
        reactor = typing.cast('base.ReactorBase', self.transport.reactor)
        reactor.callLater(30, self.setNick, nickname)
        return nickname + '_'

    def joined(self, channel: str) -> None:
        """This will get called when the bot joins the channel."""
        self.log.info("Channel {channel} joined", channel=channel)
        self.channelsJoined.add(channel)
        if self.channelsToJoin:
            cp = self.channelsToJoin.pop()
            self.join(*cp)

    def kickedFrom(self, channel: str, kicker: str, message: str) -> None:
        self.log.info("Kicked from {channel} by {kicker} (reason: {message})",
                      channel=channel, kicker=kicker, message=message)
        self.channelsJoined.discard(channel)

        if message == 'die':
            assert(self.transport)
            reactor = typing.cast('base.ReactorBase', self.transport.reactor)
            reactor.stop()
            return

        self.join(channel)

    def saslAuthenticate(self, data: bytes) -> bytes:
        if data != b'':
            return b''

        assert(self.factory)
        username = self.factory.config['sasl_user'].encode('utf-8')
        password = self.factory.config['sasl_pass'].encode('utf-8')

        return b'\x00'.join((username, username, password))

    def ctcpQuery(self, user: str, channel: str, messages: list[tuple[str, str]]) -> None:
        # Ignore CTCP
        pass

class CommitBotFactory(protocol.ReconnectingClientFactory):
    protocol = CommitBot

    def __init__(self, config: configparser.SectionProxy) -> None:
        self.config = config
        self.protocols : set[CommitBot] = set()

    def connect(self, reactor: posixbase.PosixReactorBase) -> None:
        if self.config.getboolean('tls'):
            ca_path = self.config.get('ca_path')
            if ca_path:
                with open(ca_path, 'rb') as ca:
                    ca_data = ca.read()
                authority = tls.Certificate.loadPEM(ca_data)
            else:
                authority = None
            options = tls.optionsForClientTLS(self.config['server'], authority)
            reactor.connectSSL(self.config['server'], int(self.config['port']), self, options)
        else:
            reactor.connectTCP(self.config['server'], int(self.config['port']), self)

    def protocolReady(self, protocol: CommitBot) -> None:
        self.protocols.add(protocol)
        self.resetDelay()

    def protocolDead(self, protocol: CommitBot) -> None:
        # Don't use remove: if we don't get past the welcome, we will never add the protocol
        self.protocols.discard(protocol)

    def notify(self, *args: typing.Any, **kwargs: typing.Any) -> None: # noqa: ANN401
        for p in self.protocols:
            p.notify(*args, **kwargs)

def create(config: configparser.SectionProxy, reactor: posixbase.PosixReactorBase) -> CommitBotFactory:
    f = CommitBotFactory(config)
    f.connect(reactor)
    return f
