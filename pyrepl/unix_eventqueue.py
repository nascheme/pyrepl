#   Copyright 2000-2008 Michael Hudson-Doyle <micahel@gmail.com>
#                       Armin Rigo
#
#                        All Rights Reserved
#
#
# Permission to use, copy, modify, and distribute this software and
# its documentation for any purpose is hereby granted without fee,
# provided that the above copyright notice appear in all copies and
# that both that copyright notice and this permission notice appear in
# supporting documentation.
#
# THE AUTHOR MICHAEL HUDSON DISCLAIMS ALL WARRANTIES WITH REGARD TO
# THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS, IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL,
# INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER
# RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF
# CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
# CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

# Bah, this would be easier to test if curses/terminfo didn't have so
# much non-introspectable global state.

from collections import deque

from pyrepl import keymap
from pyrepl.console import Event
from pyrepl import curses
from .trace import trace
from termios import tcgetattr, VERASE
import os
try:
    unicode
except NameError:
    unicode = str


_keynames = {
    "delete": "kdch1",
    "down": "kcud1",
    "end": "kend",
    "enter": "kent",
    "home": "khome",
    "insert": "kich1",
    "left": "kcub1",
    "page down": "knp",
    "page up": "kpp",
    "right": "kcuf1",
    "up": "kcuu1",
}


#function keys x in 1-20 -> fX: kfX
_keynames.update(('f%d' % i, 'kf%d' % i) for i in range(1, 21))


def general_keycodes():
    keycodes = {}
    for key, tiname in _keynames.items():
        keycode = curses.tigetstr(tiname)
        trace('key {key} tiname {tiname} keycode {keycode!r}', **locals())
        if keycode:
            keycodes[keycode] = key
    return keycodes


def EventQueue(fd, encoding):
    keycodes = general_keycodes()
    if os.isatty(fd):
        backspace = tcgetattr(fd)[6][VERASE]
        keycodes[backspace] = unicode('backspace')
    k = keymap.compile_keymap(keycodes)
    trace('keymap {k!r}', k=k)
    return EncodedQueue(k, encoding)


class EncodedQueue(object):
    def __init__(self, keymap, encoding):
        self.k = self.ck = keymap
        self.events = deque()
        self.buf = bytearray()
        self.encoding = encoding

    def get(self):
        if self.events:
            return self.events.popleft()
        else:
            return None

    def empty(self):
        return not self.events

    def flush_buf(self):
        old = self.buf
        self.buf = bytearray()
        return bytes(old)

    def insert(self, event):
        trace('added event {event}', event=event)
        self.events.append(event)

    def push(self, char):
        ord_char = char if isinstance(char, int) else ord(char)
        self.buf.append(ord_char)
        if char in self.k:
            if self.k is self.ck:
                #sanity check, buffer is empty when a special key comes
                assert len(self.buf) == 1
            k = self.k[char]
            trace('found map {k!r}', k=k)
            if isinstance(k, dict):
                self.k = k
            else:
                self.insert(Event('key', k, self.flush_buf()))
                self.k = self.ck

        elif self.buf and self.buf[0] == 033: # 033 == escape
            # escape sequence not recognized by our keymap: propagate it
            # outside so that i can be recognized as an M-... key (see also
            # the docstring in keymap.py, in particular the line \\E.
            trace('unrecognized escape sequence, propagating...')
            self.k = self.ck
            self.insert(Event('key', '\033', '\033'))
            for c in self.flush_buf()[1:]:
                self.push(chr(c))

        else:
            try:
                decoded = bytes(self.buf).decode(self.encoding)
            except UnicodeError:
                return
            else:
                self.insert(Event('key', decoded, self.flush_buf()))
            self.k = self.ck
