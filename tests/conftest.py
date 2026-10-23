import json

import pytest

from pykeynote import _osa


class FakeOsa:
    """Stands in for osascript. Queue replies with ``reply``; inspect ``calls``."""

    def __init__(self):
        self.calls = []
        self.replies = []

    def reply(self, value, language="JavaScript"):
        self.replies.append(json.dumps(value) if language == "JavaScript" else str(value))

    def __call__(self, language, script, argv):
        args = json.loads(argv[0]) if language == "JavaScript" else list(argv)
        self.calls.append((language, script, args))
        return self.replies.pop(0) if self.replies else ("null" if language == "JavaScript" else "")

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def osa(monkeypatch):
    fake = FakeOsa()
    monkeypatch.setattr(_osa, "_execute", fake)
    return fake
