"""Filesystem-backed Telegram simulator for development, demos, and multi-process tests."""

from bento.adapters.fake_telegram.account import FakeTelegramAccount
from bento.adapters.fake_telegram.chats import FakeTelegramChats
from bento.adapters.fake_telegram.cloud import FAKE_USER, DocumentUpload, FakeTelegramCloud
from bento.adapters.fake_telegram.options import FAKE_LOGIN_CODE, FAKE_PASSWORD, FakeTelegramOptions
from bento.adapters.fake_telegram.parts import FakeRemotePartStore
from bento.adapters.fake_telegram.session import FakeTelegramSession
from bento.adapters.fake_telegram.transport import FakeVaultTransport

__all__ = [
    "FAKE_LOGIN_CODE",
    "FAKE_PASSWORD",
    "FAKE_USER",
    "DocumentUpload",
    "FakeRemotePartStore",
    "FakeTelegramAccount",
    "FakeTelegramChats",
    "FakeTelegramCloud",
    "FakeTelegramOptions",
    "FakeTelegramSession",
    "FakeVaultTransport",
]
