from __future__ import annotations

import configparser
import sys
import typing

from twisted.internet import defer, protocol
from twisted.logger import Logger, globalLogPublisher, textFileLogObserver
from twisted.words.protocols.irc import assembleFormattedText
from twisted.words.protocols.irc import attributes as A

from . import http_hooks, irc_bot, shortener

if typing.TYPE_CHECKING:
    from collections import abc

    from twisted.internet import posixbase
    from twisted.python import failure


class CommitFormatter:
    def __init__(self, config: abc.MutableMapping[str, str],
                 reactor: posixbase.PosixReactorBase, irc: irc_bot.CommitBotFactory) -> None:
        self.shortener = shortener.Shortener(reactor, config['shortener_domain'])
        self.irc = irc

    def __call__(self, *args: typing.Any, **kwargs: typing.Any) -> None: # noqa: ANN401
        # Force a cleanup of the failure to avoid relying on the GC and get stack traces immediately
        def cleanup(f: failure.Failure) -> failure.Failure:
            f.cleanFailure()
            return f
        defer.Deferred.fromCoroutine(self.format(*args, **kwargs)).addErrback(cleanup)

    async def format(self, _origin: str, event: str, payload: dict[str, typing.Any]) -> None:
        repo = payload['repository']['name']
        sender = payload['sender']['login']

        if event == 'pull_request':
            if payload['action'] not in ('opened', 'closed', 'reopened'):
                return
            url = payload['pull_request']['html_url']
            surl = (await self.shortener.shorten(url)) or url
            msg = A.normal["[", A.fg.magenta[repo], "] ", sender, " ",
                A.bold[payload['action']], " pull request #", A.bold[str(payload['number'])], ": ",
                payload['pull_request']['title'], " (",
                    A.fg.magenta[payload['pull_request']['base']['ref'], '...',
                                 payload['pull_request']['head']['ref']], ") ",
                A.fg.lightCyan[A.underline[surl]]]
            self.irc.notify(repo, assembleFormattedText(msg))
        elif event == 'push':
            url = payload['compare']
            surl = (await self.shortener.shorten(url)) or url
            branch = payload['ref'].removeprefix('refs/heads/')
            commits = payload['commits']
            forced = payload['forced']
            msg = A.normal["[", A.fg.magenta[repo], "] ", sender, " ",
                           "forced pushed" if forced else "pushed", " ",
                           A.bold[str(len(commits))], " new commits to ", A.fg.magenta[branch], ": ",
                           A.fg.lightCyan[A.underline[surl]]]
            self.irc.notify(repo, assembleFormattedText(msg))
            for c in commits[0:3]:
                msg = A.normal[A.fg.magenta[repo], "/", A.fg.magenta[branch], " ",
                               A.fg.gray[c['id'][0:7]], " ",
                               c['author']['username'], ": ",
                               c['message'].split('\n', maxsplit=1)[0]]
                self.irc.notify(repo, assembleFormattedText(msg))

def main() -> None:
    globalLogPublisher.addObserver(textFileLogObserver(sys.stderr))
    log = Logger()

    # Turn off factory related messages
    protocol.Factory.noisy = False

    configfile = 'config.ini'
    if len(sys.argv) >= 2: # noqa: PLR2004
        configfile = sys.argv[1]

    log.info('Using {configfile} configuration file', configfile=configfile)

    config = configparser.ConfigParser()
    config['irc'] = {
        'server': '',
        'port': '7000',
        'tls': 'true',
        'server_password': '',
        'nick': 'CommitBot',
        'sasl_user': '',
        'sasl_pass': '',
        'username': 'CommitBot',
        'realname': 'Commit bot',
        'channels': '',
    }
    config['http'] = {
        'host': '127.0.0.1',
        'port': '5651',
        'github_secret': '',
    }
    config['formatter'] = {
        'shortener_domain': 'is.gd', # 'v.gd' is also possible
    }

    with open(configfile) as cf:
        config.read_file(cf)

    import twisted.internet  # noqa: PLC0415
    # Please mypy
    reactor = typing.cast('posixbase.PosixReactorBase', twisted.internet.reactor)

    bot = irc_bot.create(config['irc'], reactor)
    formatter = CommitFormatter(config['formatter'], reactor, bot)

    http_hooks.create(config['http'], reactor, formatter)

    # run everything
    reactor.run()

if __name__ == '__main__':
    main()
