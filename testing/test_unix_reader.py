from __future__ import unicode_literals
from pyrepl.unix_eventqueue import EncodedQueue

from pyrepl import curses


def test_simple():
    q = EncodedQueue({}, 'utf-8')

    a = b'\u1234'.decode('unicode-escape')
    b = a.encode('utf-8')
    for c in b:
        q.push(c)

    event = q.get()
    assert q.get() is None
    assert event.data == a
    assert event.raw == b

