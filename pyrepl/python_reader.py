#   Copyright 2000-2002 Michael Hudson mwh@python.net
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

# one impressive collections of imports:
from pyrepl.completing_reader import CompletingReader as CR
from pyrepl import completing_reader as cr, reader
from pyrepl import copy_code, commands, completer
from pyrepl import module_lister
import new, codeop, sys, os, re, code, traceback
import atexit, warnings
try:
    import cPickle as pickle
except ImportError:
    import pickle

if not hasattr(codeop, "CommandCompiler"):
    def default_compile(string, fname, mode):
        return compile(string, fname, mode)

    _code = copy_code.copy_code_with_changes(
        default_compile.func_code,
        flags = default_compile.func_code.co_flags|16)

    nested_compile = new.function(_code, globals(), "nested_compile")

    del _code, default_compile

    def CommandCompiler():
        return codeop.compile_command
else:
    CommandCompiler = code.CommandCompiler

def eat_it(*args):
    """this function eats warnings, if you were wondering"""
    pass

class maybe_accept(commands.Command):
    def do(self):
        r = self.reader
        text = ''.join(r.buffer)
        try:
            code = r.compiler(text)
        except (OverflowError, SyntaxError, ValueError):
            self.finish = 1
        else:
            if code is None:
                r.insert("\n")
            else:
                self.finish = 1

from_line_prog = re.compile(
    "^from\s+(?P<mod>[A-Za-z_.0-9]*)\s+import\s+(?P<name>[A-Za-z_.0-9]*)")
import_line_prog = re.compile(
    "^(?:import|from)\s+(?P<mod>[A-Za-z_.0-9]*)\s*$")

def mk_saver(reader):
    def saver(reader=reader):
        try:
            file = open(os.path.expanduser("~/.pythoni.hist"), "w")
        except IOError:
            pass
        else:
            pickle.dump(reader.history, file)
            file.close()
    return saver

python_keymap = cr.completing_keymap + (
    ('\\n', 'maybe-accept'),
    ('\\M-\\n', 'self-insert'))

class PythonicReader(CR):
    keymap = python_keymap
    
    CR_init = CR.__init__
    def __init__(self, console, locals,
                 compiler=None):
        self.CR_init(console)
        self.completer = completer.Completer(locals)
        st = self.syntax_table
        for c in "._0123456789":
            st[c] = reader.SYNTAX_WORD
        self.locals = locals
        if compiler is None:
            self.compiler = CommandCompiler()
        else:
            self.compiler = compiler
        try:
            file = open(os.path.expanduser("~/.pythoni.hist"))
        except IOError:
            pass
        else:
            try:
                self.history = pickle.load(file)
            except:
                self.history = []
            self.historyi = len(self.history)
            file.close()
        atexit.register(mk_saver(self))
        for c in [maybe_accept]:
            self.commands[c.__name__] = c
            self.commands[c.__name__.replace('_', '-')] = c        
    
    def install_keymap(self):
        self.console.install_keymap(self.keymap)

    def get_completions(self, stem):
        b = ''.join(self.buffer)
        m = import_line_prog.match(b)
        if m:
            mod = m.group("mod")
            try:
                return module_lister.find_modules(mod)
            except ImportError:
                pass
        m = from_line_prog.match(b)
        if m:
            mod, name = m.group("mod", "name")
            try:
                l = module_lister._packages[mod]
            except KeyError:
                try:
                    mod = __import__(mod, self.locals, self.locals, [1])
                    return [x for x in dir(mod) if x.startswith(name)]
                except ImportError:
                    pass
            else:
                return [x[len(mod) + 1:]
                        for x in l if x.startswith(mod + '.' + name)]
        try:
            l = cr.uniqify(self.completer.complete(stem))
            return l
        except (NameError, AttributeError):
            return []

class ReaderConsole(code.InteractiveInterpreter):
    II_init = code.InteractiveInterpreter.__init__
    def __init__(self, console, locals=None):
        if locals is None:
            locals = {}
        self.II_init(locals)
        self.compiler = CommandCompiler()
        self.compile = getattr(self.compiler, "compiler", compile)
        self.reader = PythonicReader(console, locals, self.compiler)
        locals['Reader'] = self.reader

    def run_user_init_file(self):
        for key in "PYREPLSTARTUP", "PYTHONSTARTUP":
            initfile = os.environ.get(key)
            if initfile is not None and os.path.exists(initfile):
                break
        else:
            return
        try:
            execfile(initfile, self.locals, self.locals)
        except:
            traceback.print_exc()

    def execute(self, text):
        try:
            code = self.compile(text, '<input>', 'single')
            if code.co_flags & 16:
                self.compile = nested_compile
        except (OverflowError, SyntaxError, ValueError):
            self.showsyntaxerror("<input>")
        else:
            self.runcode(code)

    def interact(self):
        while 1:
            try: # catches EOFError's and KeyboardInterrupts during execution
                try: # catches KeyboardInterrupts during editing
                    try: # warning saver
                        # can't have warnings spewed onto terminal
                        sv = warnings.showwarning
                        warnings.showwarning = eat_it
                        l = self.reader.readline()
                    finally:
                        warnings.showwarning = sv
                except KeyboardInterrupt:
                    print "KeyboardInterrupt"
                else:
                    if l:
                        self.execute(l)
            except EOFError:
                break
            except KeyboardInterrupt:
                continue

    def prepare(self):
        self.sv_sw = warnings.showwarning
        warnings.showwarning = eat_it
        self.reader.prepare()
        self.reader.refresh() # we want :after methods...

    def restore(self):
        self.reader.restore()
        warnings.showwarning = self.sv_sw

    def handle1(self, block=1):
        try:
            self.reader.handle1(block)
        except KeyboardInterrupt:
            self.restore()
            print "KeyboardInterrupt"
            self.prepare()
        else:
            if self.reader.finished:
                text = ''.join(self.reader.buffer)
                self.restore()
                if text:
                    self.execute(text)
                self.prepare()

    def tkfilehandler(self, file, mask):
        try:
            self.handle1(block=0)
        except:
            self.exc_info = sys.exc_info()

    # how the <expletive> do you get this to work on Windows (without
    # createfilehandler)?  threads, I guess
    def really_tkinteract(self):
        import _tkinter
        _tkinter.createfilehandler(
            self.reader.console.fd, _tkinter.READABLE,
            self.tkfilehandler)
        self.exc_info = None
        while 1:
            # dooneevent will return 0 without blocking if there are
            # no Tk windows, 1 after blocking until an event otherwise
            # so the following does what we want (this wasn't expected
            # to be obvious).
            if not _tkinter.dooneevent(_tkinter.ALL_EVENTS):
                self.handle1(block=1)
            if self.exc_info:
                type, value, tb = self.exc_info
                self.exc_info = None
                raise type, value, tb
        
    def tkinteract(self):
        """Run a Tk-aware Python interactive session.

        This function simulates the Python top-level in a way that
        allows Tk's mainloop to run."""
        
        # attempting to understand the control flow of this function
        # without help may cause internal injuries.  so, some
        # explanation.

        # The outer while loop is there to restart the interaction if
        # the user types control-c when execution is deep in our
        # innards.  I'm not sure this can't leave internals in an
        # inconsistent state, but it's a good start.

        # then the inside loop keeps calling self.handle1 until
        # _tkinter gets imported; then control shifts to
        # self.really_tkinteract, above.

        # this function can only return via an exception; we mask
        # EOFErrors (but they end the interaction) and
        # KeyboardInterrupts cause a restart.  All other exceptions
        # are likely bugs in pyrepl (well, 'cept for SystemExit, of
        # course).
        
        while 1:
            try:
                try:
                    self.prepare()
                    try:
                        while 1:
                            if sys.modules.has_key("_tkinter"):
                                self.really_tkinteract()
                                # really_tkinteract is not expected to
                                # return except via an exception, but:
                                break
                            self.handle1()
                    except EOFError:
                        pass
                finally:
                    self.restore()
            except KeyboardInterrupt:
                continue
            else:
                break

def main(use_pygame_console=0):
    si, se, so = sys.stdin, sys.stderr, sys.stdout
    try:
        if use_pygame_console:
            from pyrepl.pygame_console import PyGameConsole, FakeStdin, FakeStdout
            con = PyGameConsole()
            sys.stderr = sys.stdout = FakeStdout(con)
            sys.stdin = FakeStdin(con)
        else:
            from pyrepl.unix_console import UnixConsole
            con = UnixConsole(1, None)
        print "Python", sys.version, "on", sys.platform
        print 'Type "copyright", "credits" or "license" for more information.'
        sys.path.insert(0, os.getcwd())

        mainmod = new.module('__main__')
        sys.modules['__main__'] = mainmod

        rc = ReaderConsole(con, mainmod.__dict__)
        rc.run_user_init_file()
        rc.tkinteract()
    finally:
        sys.stdin, sys.stderr, sys.stdout = si, se, so

if __name__ == '__main__':
    main()
