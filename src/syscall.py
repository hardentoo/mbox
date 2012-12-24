import os
import stat
import errno
import struct
import dbg
import ctypes

from util import *

#
# syscall : (ret, arg0, arg1, arg2, ...)
#
# ([name:]type)
#  - if name is not speficied, type.split("_")[1] will be name
#  - arg# also aliased
#
SYSCALLS = {
  "open"       : ("f_fd" , "f_path"      , "f_flag" , "f_mode"             ),
  "openat"     : ("f_fd" , "dirfd:at_fd" , "f_path" , "f_flag"  , "f_mode" ),
  "close"      : ("err"  , "f_fd"                                          ),
  "getdents"   : ("f_len", "f_fd"        , "f_dirp" , "f_size"             ),
  "stat"       : ("err"  , "f_path"      , "f_statp"                       ),
  "fstat"      : ("err"  , "f_fd"        , "f_statp"                       ),
  "fstatat"    : ("err"  , "dirfd:at_fd" , "f_path" , "f_statp" , "f_int"  ),
  "lstat"      : ("err"  , "f_path"      , "f_statp"                       ),
  "unlink"     : ("err"  , "f_path"                                        ),
  "unlinkat"   : ("err"  , "dirfd:at_fd" , "f_path" , "f_int"              ),
  "getxattr"   : ("serr" , "f_path"      , "f_cstr" , "f_ptr"   , "f_int"  ),
  "access"     : ("err"  , "f_path"      , "f_int"                         ),
  "faccessat"  : ("err"  , "dirfd:at_fd" , "f_path" , "f_int"              ),
  "chdir"      : ("err"  , "f_path"                                        ),
  "fchdir"     : ("err"  , "dirfd:at_fd"                                   ),
  "rename"     : ("err"  , "old:f_path"  , "new:f_path"                    ),
  "renameat"   : ("err"  , "oldfd:f_fd"  , "old:f_path", "newfd:f_fd", "new:f_path" ),
  "fcntl"      : ("err"  , "f_fd"        , "f_fcntlcmd"                    ),
  "readlink"   : ("f_len", "f_path"      , "f_ptr"  , "f_int"              ),
  "readlinkat" : ("f_len", "dirfd:at_fd" , "f_path" , "f_ptr"   , "f_int"  ),
  "mkdir"      : ("err"  , "f_path"      , "f_mode"                        ),
  "mkdirat"    : ("err"  , "dirfd:at_fd" , "f_path" , "f_mode"             ),
  "chmod"      : ("err"  , "f_path"      , "f_mode"                        ),
  "fchmodat"   : ("err"  , "dirfd:at_fd" , "f_path" , "f_mode"             ),
  "creat"      : ("err"  , "f_path"      , "f_mode"                        ),
  "chown"      : ("err"  , "f_path"      , "o:f_int", "g:f_int"            ),
  "fchownat"   : ("err"  , "dirfd:at_fd" , "f_path" , "o:f_int", "g:f_int" ),
  "truncate"   : ("err"  , "f_path"      , "f_int"                         ),
  "rmdir"      : ("err"  , "f_path"                                        ),
  "utimensat"  : ("err"  , "dirfd:at_fd" , "f_path" , "f_ptr"  , "f_int"   ),
}

# XXX. syscall priorities that we should check
#
#  fcntl: ok
#  dup/dup2: ok
#  ftruncate: ok
#  flock: ok
#
#  ioctl
#  mmap
#  socket
#  connect
#  f/utime/s/at
#  mknod
#  futex
#
#  setxattr
#  lsetxattr
#  fsetxattr
#  getxattr
#  lgetxattr
#  fgetxattr
#  listxattr
#  llistxattr
#  flistxattr
#  removexattr
#  lremovexattr
#  fremovexattr

# newstat
for sc in ["stat", "fstat", "lstat", "fstatat"]:
    SYSCALLS["new" + sc] = SYSCALLS.get(sc, [])

# num -> name
SYSCALL_MAP = {}

# read from the file
pn = os.path.join(os.path.dirname(__file__), "syscall64.tbl")
for l in open(pn):
    l = l.strip()
    if l.startswith("#") or len(l) == 0:
        continue

    # parsing syscall table
    (num, abi, name) = l.split()[:3]

    # syscall number as integer
    num = int(num)
    
    # construct a table
    SYSCALL_MAP[num] = name

    # NR_syscall
    exec "NR_%s = %d" % (name, num)
    
def scname(scnum):
    return SYSCALL_MAP.get(scnum, "N/A")

def to_clong(arg):
    return ctypes.c_long(arg).value

def to_culong(arg):
    return ctypes.c_ulong(arg).value

# system call state
SC_ENTERING = 0
SC_EXITING  = 1

class Syscall:
    def __init__(self, proc):
        self.rtn   = None
        self.proc  = proc
        self.regs  = proc.getregs()
        self.name  = scname(self.regs.orig_rax)
        self.state = SC_ENTERING
        self.args  = []

        # generate args
        args = SYSCALLS.get(self.name, [])
        for (i, arg) in enumerate(args[1:]):
            (name, kls) = self.__parse_syscall(arg)
            val = self.__parse_arg(proc, self.regs, kls, i)

            # alias: arg#, name, args
            setattr(self, "arg%d" % i, val)
            setattr(self, name, val)
            self.args.append(val)
            
        # return
        setattr(self, "ret", None)
        
    @property
    def entering(self):
        return self.state == SC_ENTERING

    @property
    def exiting(self):
        return self.state == SC_EXITING

    def update(self):
        assert self.state == SC_ENTERING and self.ret is None
        self.state = SC_EXITING

        # check if same syscall
        regs = self.proc.getregs()
        if regs.orig_rax != self.regs.orig_rax:
            #
            # XXX. there are some inconsistent state when signaled
            dbg.info("XXX:%s (new:%x, old:%x)" % (str(self), regs.orig_rax, self.regs.orig_rax))
            # dbg.stop()
            # 
            pass

        # generate 
        ret = "err"
        args = SYSCALLS.get(self.name, [])
        if len(args) > 0:
            ret = args[0]
        (name, kls) = self.__parse_syscall(ret)
        val = self.__parse_arg(self.proc, regs, kls, -1)

        setattr(self, "ret", val)
        setattr(self, name , val)
        
    def __parse_syscall(self, arg):
        kls  = arg
        name = None
        if ":" in arg:
            (name, kls) = arg.split(":")
        else:
            if "_" in kls:
                name = kls.split("_")[1]
            else:
                name = kls
        return (name, eval(kls))

    def __get_reg_from_seq(self, regs, seq):
        rn = ("rdi", "rsi", "rdx", "r10", "r8", "r9", "rax")[seq]
        return getattr(regs, rn)
    
    def __parse_arg(self, proc, regs, kls, seq):
        arg = self.__get_reg_from_seq(regs, seq)
        if kls.argtype == "str":
            arg = proc.read_str(arg)
        return newarg(kls, arg, seq, self)

    def __str__(self):
        pid = self.proc.pid
        seq = ">" if self.entering else "<"
        rtn = "[%d]%s %s(%s)" % (pid, seq, self.name, ",".join(str(a) for a in self.args))
        if self.exiting:
            rtn += " = %s" % self.ret
        return rtn

#
# weave functions for arguments
#  - don't like super() in python, so weave here
#
def newarg(kls, arg, seq, sc):
    val = kls(arg, sc)
    setattr(val, kls.argtype, arg)
    setattr(val, "seq", seq)
    setattr(val, "old", None)
    return val

class arg(object):
    def hijack(self, proc, new):
        if self.argtype == "str":
            self._hijack_str(proc, new)
        elif self.argtype == "int":
            self._hijack_int(proc, new)

    def restore(self, proc, new):
        if self.argtype == "str":
            self._restore_str(proc, new)
        elif self.argtype == "int":
            self._restore_int(proc, new)

    def _get_arg(self, proc, seq):
        r  = ("rdi", "rsi", "rdx", "r10", "r8", "r9", "rax")[seq]
        regs = proc.getregs()
        return (r, getattr(regs, r))

    def _hijack_str(self, proc, new):
        assert type(new) is str and len(new) < MAX_PATH - 1
        assert self.seq >= 0

        # memcpy to the lower part of stack (unique regions per argument)
        ptr = proc.getreg("rsp") - MAX_PATH * (self.seq+1)
        proc.write_str(ptr, new)

        # write to the proper register
        (reg, self.old) = self._get_arg(proc, self.seq)
        proc.setreg(reg, ptr)

    def _restore_str(self, proc, new):
        assert type(new) is str
        (reg, _) = self._get_arg(proc, self.seq)
        proc.setreg(reg, self.old)

    def _hijack_int(self, proc, new):
        assert type(new) is int
        (reg, self.old) = self._get_arg(proc, self.seq)
        proc.setreg(reg, new)

    def _restore_int(self, proc, new):
        assert type(new) is int
        (reg, _) = self._get_arg(proc, self.seq)
        proc.setreg(reg, self.old)

class err(arg):
    argtype = "int"
    def __init__(self, arg, sc):
        self.arg = to_clong(arg)
    def ok(self):
        return self.arg == 0
    def err(self):
        return self.arg != 0
    def restore(self, proc, new):
        if self.int != new:
            self.old = new
            self._restore_int(proc, new)
    def __str__(self):
        if self.ok():
            return "ok"
        if self.arg > 2**16:
            return "0x%x" % self.arg
        return errno.errorcode.get(-self.arg, str(self.arg))

class serr(err):
    argtype = "int"
    def __init__(self, arg, sc):
        super(serr, self).__init__(arg, sc)
    def ok(self):
        return self.arg >= 0
    def err(self):
        return self.arg < 0

class ptr(arg):
    def __init__(self, arg, sc):
        self.ptr = arg
    def __str__(self):
        return "0x%x" % self.ptr

class f_int(arg):
    argtype = "int"
    def __init__(self, arg, sc):
        self.arg = arg
    def __str__(self):
        return "%d" % self.arg

f_size = f_int
f_len  = f_int

class f_ptr(ptr):
    argtype = "int"
    def __init__(self, arg, sc):
        super(f_ptr, self).__init__(arg, sc)

class f_cstr(arg):
    argtype = "str"
    def __init__(self, arg, sc):
        self.arg = arg
    def __str__(self):
        return "%s" % self.arg

class f_dirp(ptr):
    argtype = "int"
    def __init__(self, arg, sc):
        super(f_dirp, self).__init__(arg, sc)
        self.sc = sc

    def hijack(self, proc, blob):
        raise NotImplemented()

    def restore(self, proc, blob):
        # < alloced memory
        assert len(blob) < self.sc.size.int
        # overwrite buf
        proc.write_bytes(self.ptr, blob)
        # overwrite ret (size of blob)
        proc.setreg("rax", len(blob))

    def read(self):
        assert self.sc.ret
        return self.sc.proc.readBytes(self.ptr, self.sc.ret.int)

class f_fd(arg):
    argtype = "int"
    def __init__(self, arg, sc):
        self.fd = to_clong(arg)
    def err(self):
        return self.fd < 0
    def __str__(self):
        if self.fd >= 0:
            return "%d" % self.fd
        return "%s" % errno.errorcode[-self.fd]

#
# specifications
#

MAX_INT  = 2**64
MAX_PATH = 256

O_ACCMODE  = 00000003
O_RDONLY   = 00000000
O_WRONLY   = 00000001
O_RDWR     = 00000002
O_CREAT    = 00000100   # create file if it does not exist
O_EXCL     = 00000200   # error if create and file exists
O_NOCTTY   = 00000400   #
O_TRUNC    = 00001000   # truncate size to 0
O_APPEND   = 00002000   # append when writing
O_NONBLOCK = 00004000   # non-blocking
O_DSYNC    = 00010000   # used to be O_SYNC, see below
O_DIRECT   = 00040000   # direct disk access hint
O_LARGEFILE= 00100000
O_DIRECTORY= 00200000   # must be a directory
O_NOFOLLOW = 00400000   # don't follow links
O_NOATIME  = 01000000   # no access time
O_CLOEXEC  = 02000000   # set close_on_exec

class f_path(arg):
    argtype = "str"
    def __init__(self, arg, sc):
        self.path = arg

    def exists(self):
        return exists(self.path)

    def is_dir(self):
        return dir_exists(self.path)

    def normpath(self, cwd):
        pn = normpath(self.path)
        if pn.startswith("/"):
            return pn
        else:
            return normpath(join(cwd, pn))

    def chroot(self, root, cwd):
        pn = normpath(self.path)
        # absolute path
        if pn.startswith("/"):
            return chjoin(root, pn[1:])
        # cwd
        assert cwd.startswith("/")
        return chjoin(root, cwd[1:], pn)

    def __str__(self):
        return "%s%s" % (self.path, "" if exists(self.path) else "(N)")

class f_sysc(arg):
    argtype = "int"
    def __init__(self, arg, sc):
        self.seq  = -1
        self.flag = arg

    # rax is now used as return value
    def restore(self, proc, blob):
        pass

class f_flag(arg):
    argtype = "int"
    def __init__(self, arg, sc):
        self.flag = arg
    def is_rdonly(self):
        return (self.flag & O_ACCMODE) == O_RDONLY
    def is_wronly(self):
        return (self.flag & O_ACCMODE) == O_WRONLY
    def is_rdwr(self):
        return (self.flag & O_ACCMODE) == O_RDWR
    def is_wr(self):
        return self.is_wronly() or self.is_rdwr()
    def is_trunc(self):
        return (self.flag & O_TRUNC)
    def is_dir(self):
        return (self.flag & O_DIRECTORY)
    def chk(self, f):
        return self.flag & f
    def __str__(self):
        rtn = []
        for f in ["O_RDONLY", "O_WRONLY", "O_RDWR"]:
            if self.flag & O_ACCMODE == eval(f):
                rtn.append(f)

        for f in ["O_CREAT"     , "O_EXCL"     , "O_NOCTTY"    ,
                  "O_TRUNC"     , "O_APPEND"   , "O_NONBLOCK"  ,
                  "O_DSYNC"     , "O_DIRECT"   , "O_LARGEFILE" ,
                  "O_DIRECTORY" , "O_NOFOLLOW" , "O_NOATIME"   ,
                  "O_CLOEXEC"]:
            if self.flag & eval(f) != 0:
                rtn.append(f)

        return "|".join(rtn)

class f_mode(arg):
    argtype = "int"
    def __init__(self, arg, sc):
        self.mode = None
        if not hasattr(sc, "flag") or sc.flag.chk(O_CREAT):
            self.mode = arg
    def __str__(self):
        if self.mode is None:
            return "-"
        return "0%o" % self.mode

AT_FDCWD = -100

class at_fd(f_fd):
    def __init__(self, arg, sc):
        super(at_fd, self).__init__(arg, sc)
    def __str__(self):
        if self.fd == AT_FDCWD:
            return "AT_FDCWD"
        return super(at_fd, self).__str__()

class f_statp(ptr):
    argtype = "int"
    def __init__(self, arg, sc):
        super(f_statp, self).__init__(arg, sc)
        self.sc = sc

#
# dirents related
#
def parse_dirents(blob):
    rtn = []
    off = 0
    while off < len(blob):
        d = dirent()
        d.parse(blob, off)
        rtn.append(d)
        off += d.d_reclen
    return rtn

def get_dirents(path):
    #
    # NOTE. slow, call getdirent() syscall intead
    #
    if not dir_exists(path):
        return []
    rtn = []
    off = 1
    for f in os.listdir(path):
        s = os.lstat(join(path, f))
        d = dirent()
        d.d_name   = f
        d.d_type   = __st_to_dt(s)
        d.d_ino    = s.st_ino
        d.d_off    = off
        d.d_reclen = ((len(f)+19+24)/24)*24
        rtn.append(d)
        off += 1
    return rtn

DT_UNKNOWN = 0  # The file type is unknown
DT_FIFO    = 1  # This is a named pipe (FIFO)
DT_CHR     = 2  # This is a character device
DT_DIR     = 4  # This is a directory
DT_BLK     = 6  # This is a block device
DT_REG     = 8  # This is a regular file
DT_LNK     =10  # This is a symbolic link
DT_SOCK    =14  # This is a UNIX domain socket

def __st_to_dt(s):
    mod = s.st_mode
    for m in ["BLK", "CHR", "DIR", "FIFO", "LNK", "REG", "SOCK"]:
        if getattr(stat, "S_IS" + m)(mod):
            rtn = eval("DT_" + m)
            break
    return rtn

#
# NOTE.
#  - d_off seems to be ignored in everywhere
#    tmpfs sets the order of dirent to d_off
#  - d_reclen seems to be aligned 24, so I abide by too
#
class dirent:
    fields = [("d_ino"   , "<Q"),
              ("d_off"   , "<Q"),
              ("d_reclen", "<H")]

    def __init__(self):
        for (field, fmt) in dirent.fields:
            setattr(self, field, None)
        self.d_name = ""
        self.d_type = DT_UNKNOWN

    def parse(self, buf, beg):
        offset = beg
        for (field, fmt) in dirent.fields:
            val = struct.unpack_from(fmt, buf, offset)
            setattr(self, field, val[0])
            dbg.dirent(field, "%x" % offset, "val=", getattr(self, field))
            offset += struct.calcsize(fmt)

        self.d_name = buf[offset:beg + self.d_reclen - 1].rstrip("\x00")
        self.d_type = ord(buf[beg + self.d_reclen - 1])

        dbg.dirent("offset:%x, '%s'(%d)" % (offset, self.d_name, len(self.d_name)))

    def pack(self):
        # regular header
        blob = ""
        for (field, fmt) in dirent.fields:
            blob += struct.pack(fmt, getattr(self, field))
        # name:char[]
        blob += self.d_name
        # padding
        blob += "\x00" * (self.d_reclen - len(blob) - 1)
        # type
        blob += chr(self.d_type)
        return blob

    def __str__(self):
        return "%d(offset:%d, len:%d): %s (type:%s)" \
          % (self.d_ino, self.d_off, self.d_reclen, self.d_name, self.d_type)

F_DUPFD         = 0  # dup
F_GETFD         = 1  # get close_on_exec
F_SETFD         = 2  # set/clear close_on_exec
F_GETFL         = 3  # get file->f_flags
F_SETFL         = 4  # set file->f_flags
F_GETLK         = 5  #
F_SETLK         = 6  #
F_SETLKW        = 7  #
F_SETOWN        = 8  # for sockets.
F_GETOWN        = 9  # for sockets.
F_SETSIG        = 10 # for sockets.
F_GETSIG        = 11 # for sockets.
F_GETLK64       = 12 # using 'struct flock64'
F_SETLK64       = 13 #
F_SETLKW64      = 14 #
F_SETOWN_EX     = 15 #
F_GETOWN_EX     = 16 #
F_GETOWNER_UIDS = 17 #

class f_fcntlcmd(arg):
    argtype = "int"
    def __init__(self, arg, sc):
        self.cmd = arg
    def __str__(self):
        for f in ["F_DUPFD"     , "F_GETFD"   , "F_SETFD"    , "F_GETFL"     ,
                  "F_SETFL"     , "F_GETLK"   , "F_SETLK"    , "F_SETLKW"    ,
                  "F_SETOWN"    , "F_GETOWN"  , "F_SETSIG"   , "F_GETSIG"    ,
                  "F_GETLK64"   , "F_SETLK64" , "F_SETLKW64" , "F_SETOWN_EX" ,
                  "F_GETOWN_EX" , "F_GETOWNER_UIDS"]:
            if eval(f) == self.cmd:
                return f
        return "N/A"

def print_syscalls():
    for (num, name) in sorted(list(SYSCALL_MAP.items())):
        mark = "*" if name in SYSCALLS else " "
        print "%s%3d: %s" % (mark, num, name)
    
if __name__ == '__main__':
    print_syscalls()