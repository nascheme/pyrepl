#   Copyright 2000-2010 Michael Hudson-Doyle <micahel@gmail.com>
#                       Antonio Cuni
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

import os
import signal

# Catgories of actions:
#  killing
#  yanking
#  motion
#  editing
#  history
#  finishing
# [completion]


class Command(object):
    finish = 0
    kills_digit_arg = 1

    def __init__(self, reader, event_name, event):
        self.reader = reader
        self.event = event
        self.event_name = event_name

    def do(self):
        pass

    @classmethod
    def usereader(cls, func):
        is_method = 'self' in func.__code__.co_varnames

        def wrap(f):
            if is_method:
                return f
            else:
                return staticmethod(f)

        class ReaderCommand(cls):
            do_reader = wrap(func)

            def do(self):
                self.do_reader(self.reader)

        ReaderCommand.__name__ = func.__name__
        return ReaderCommand


def kill_range(reader, start, end):
    if start == end:
        return
    r = reader
    b = reader.buffer
    text = b[start:end]
    del b[start:end]
    if is_kill(r.last_command):
        if start < r.pos:
            r.kill_ring[-1] = text + r.kill_ring[-1]
        else:
            r.kill_ring[-1] = r.kill_ring[-1] + text
    else:
        r.kill_ring.append(text)
    r.pos = start
    r.dirty = 1


class KillCommand(Command):
    pass


class YankCommand(Command):
    pass


class MotionCommand(Command):
    pass


class EditCommand(Command):
    pass


class FinishCommand(Command):
    finish = 1


def is_kill(command):
    return command and issubclass(command, KillCommand)


def is_yank(command):
    return command and issubclass(command, YankCommand)

# etc


class digit_arg(Command):
    kills_digit_arg = 0

    def do(self):
        r = self.reader
        c = self.event[-1]
        if c == "-":
            if r.arg is None:
                r.arg = -1
            else:
                r.arg = -r.arg
        else:
            d = int(c)
            if r.arg is None:
                r.arg = d
            else:
                if r.arg < 0:
                    r.arg = 10 * r.arg - d
                else:
                    r.arg = 10 * r.arg + d
        r.dirty = 1


@Command.usereader
def clear_screen(r):
    r.console.clear()
    r.dirty = 1


@Command.usereader
def refresh(reader):
    reader.dirty = 1


@Command.usereader
def repaint(self):
    self.reader.dirty = 1
    self.reader.console.repaint_prep()


@KillCommand.usereader
def kill_line(r):
    b = r.buffer
    eol = r.eol()
    for c in b[r.pos:eol]:
        if not c.isspace():
            kill_range(r, r.pos, eol)
            return
    else:
        kill_range(r, r.pos, eol + 1)


@KillCommand.usereader
def unix_line_discard(r):
    kill_range(r, r.bol(), r.pos)

# XXX unix_word_rubout and backward_kill_word should actually
# do different things...


@KillCommand.usereader
def unix_word_rubout(r):
    for i in range(r.get_arg()):
        kill_range(r, r.bow(), r.pos)


@KillCommand.usereader
def kill_word(r):
    for i in range(r.get_arg()):
        kill_range(r, r.pos, r.eow())


@KillCommand.usereader
def backward_kill_word(r):
    for i in range(r.get_arg()):
        kill_range(r, r.bow(), r.pos)


@YankCommand.usereader
def yank(r):
    if r.kill_ring:
        r.insert(r.kill_ring[-1])
    else:
        r.error("nothing to yank")


@YankCommand.usereader
def yank_pop(r):
    if not r.kill_ring:
        r.error("nothing to yank")
    elif not is_yank(r.last_command):
        r.error("previous command was not a yank")
    else:
        b = r.buffer
        repl = len(r.kill_ring[-1])
        r.kill_ring.insert(0, r.kill_ring.pop())
        t = r.kill_ring[-1]
        b[r.pos - repl:r.pos] = t
        r.pos = r.pos - repl + len(t)
        r.dirty = 1


@FinishCommand.usereader
def interrupt(r):
    r.console.finish()
    os.kill(os.getpid(), signal.SIGINT)


@Command.usereader
def suspend(r):
    p = r.pos
    r.console.finish()
    os.kill(os.getpid(), signal.SIGSTOP)
    ## this should probably be done
    ## in a handler for SIGCONT?
    r.console.prepare()
    r.pos = p
    r.posxy = 0, 0
    r.dirty = 1
    r.console.screen = []


@MotionCommand.usereader
def up(r):
    for i in range(r.get_arg()):
        bol1 = r.bol()
        if bol1 == 0:
            if r.historyi > 0:
                r.select_item(r.historyi - 1)
                return
            r.pos = 0
            r.error("start of buffer")
            return
        bol2 = r.bol(bol1 - 1)
        line_pos = r.pos - bol1
        if line_pos > bol1 - bol2 - 1:
            r.sticky_y = line_pos
            r.pos = bol1 - 1
        else:
            r.pos = bol2 + line_pos


@MotionCommand.usereader
def down(r):
    b = r.buffer
    for i in range(r.get_arg()):
        bol1 = r.bol()
        eol1 = r.eol()
        if eol1 == len(b):
            if r.historyi < len(r.history):
                r.select_item(r.historyi + 1)
                r.pos = r.eol(0)
                return
            r.pos = len(b)
            r.error("end of buffer")
            return
        eol2 = r.eol(eol1 + 1)
        if r.pos - bol1 > eol2 - eol1 - 1:
            r.pos = eol2
        else:
            r.pos = eol1 + (r.pos - bol1) + 1


@MotionCommand.usereader
def left(r):
    new_pos = r.pos - r.get_arg()
    r.pos = max(0, new_pos)
    if new_pos < 0:
        r.error("start of buffer")


@MotionCommand.usereader
def right(r):
    new_pos = r.pos + r.get_arg()
    buffsize = len(r.buffer)
    r.pos = min(new_pos, buffsize)
    if new_pos > buffsize:
        r.error("end of buffer")


@MotionCommand.usereader
def beginning_of_line(r):
    r.pos = r.bol()


@MotionCommand.usereader
def end_of_line(r):
    r.pos = r.eol()


@MotionCommand.usereader
def home(r):
    r.pos = 0


@MotionCommand.usereader
def end(r):
    r.pos = len(r.buffer)


@MotionCommand.usereader
def forward_word(r):
    for i in range(r.get_arg()):
        r.pos = r.eow()


@MotionCommand.usereader
def backward_word(r):
    for i in range(r.get_arg()):
        r.pos = r.bow()


@EditCommand.usereader
def self_insert(self, r):
    r.insert(self.event * r.get_arg())


@EditCommand.usereader
def insert_nl(r):
    r.insert("\n" * r.get_arg())


@EditCommand.usereader
def transpose_characters(r):
    b = r.buffer
    s = r.pos - 1
    if s < 0:
        r.error("cannot transpose at start of buffer")
    else:
        if s == len(b):
            s -= 1
        t = min(s + r.get_arg(), len(b) - 1)
        c = b[s]
        del b[s]
        b.insert(t, c)
        r.pos = t
        r.dirty = 1


@EditCommand.usereader
def backspace(r):
    b = r.buffer
    for i in range(r.get_arg()):
        if r.pos > 0:
            r.pos -= 1
            del b[r.pos]
            r.dirty = 1
        else:
            r.error("can't backspace at start")


@EditCommand.usereader
def delete(self, r):
    b = r.buffer
    if r.pos == 0 and not b and self.event[-1] == "\004":
        r.update_screen()
        r.console.finish()
        raise EOFError
    for i in range(r.get_arg()):
        if r.pos != len(b):
            del b[r.pos]
            r.dirty = 1
        else:
            r.error("end of buffer")


class accept(FinishCommand):
    pass


@Command.usereader
def help(reader):
    reader.msg = reader.help_text
    reader.dirty = 1


@Command.usereader
def invalid_key(self, reader):
    pending = reader.console.getpending()
    s = ''.join(self.event) + pending.data
    reader.error("`%r' not bound" % s)


@Command.usereader
def invalid_command(self, reader):
    reader.error("command `%s' not known" % self.event_name)


@Command.usereader
def qIHelp(self, r):
    r.insert((self.event + r.console.getpending().data) * r.get_arg())
    r.pop_input_trans()


class QITrans(object):
    def push(self, evt):
        self.evt = evt

    def get(self):
        return ('qIHelp', self.evt.raw)


class quoted_insert(Command):
    kills_digit_arg = 0

    def do(self):
        self.reader.push_input_trans(QITrans())
