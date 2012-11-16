import struct

from ctypes import c_long 
from ctypes import c_ulong
from ctypes import cdll
from ctypes import addressof
from ctypes import Structure

from ctypes.util import find_library

libc = cdll.LoadLibrary(find_library('c'))

libc_ptrace = libc.ptrace
libc_ptrace.argtypes = (c_ulong, c_ulong, c_ulong, c_ulong)
libc_ptrace.restype  = c_ulong

# ptrace cmd
PTRACE_TRACEME    = 0
PTRACE_PEEKTEXT   = 1
PTRACE_PEEKDATA   = 2
PTRACE_PEEKUSR    = 3
PTRACE_POKETEXT   = 4
PTRACE_POKEDATA   = 5
PTRACE_POKEUSR    = 6
PTRACE_CONT       = 7
PTRACE_KILL       = 8
PTRACE_SINGLESTEP = 9
PTRACE_GETREGS    = 12
PTRACE_SETREGS    = 13
PTRACE_GETFPREGS  = 14
PTRACE_SETFPREGS  = 15
PTRACE_ATTACH     = 16
PTRACE_DETACH     = 17
PTRACE_GETFPXREGS = 18
PTRACE_SETFPXREGS = 19
PTRACE_SYSCALL    = 24

# extra cmds
PTRACE_SETOPTIONS  = 0x4200
PTRACE_GETEVENTMSG = 0x4201
PTRACE_GETSIGINFO  = 0x4202
PTRACE_SETSIGINFO  = 0x4203
PTRACE_GETREGSET   = 0x4204
PTRACE_SETREGSET   = 0x4205
PTRACE_SEIZE       = 0x4206
PTRACE_INTERRUPT   = 0x4207
PTRACE_LISTEN      = 0x4208
PTRACE_SEIZE_DEVEL = 0x80000000

# set opts
PTRACE_O_TRACESYSGOOD	= 0x00000001
PTRACE_O_TRACEFORK      = 0x00000002
PTRACE_O_TRACEVFORK     = 0x00000004
PTRACE_O_TRACECLONE     = 0x00000008
PTRACE_O_TRACEEXEC      = 0x00000010
PTRACE_O_TRACEVFORKDONE = 0x00000020
PTRACE_O_TRACEEXIT      = 0x00000040
PTRACE_O_MASK           = 0x0000007f

# events
PTRACE_EVENT_FORK       = 1
PTRACE_EVENT_VFORK      = 2
PTRACE_EVENT_CLONE      = 3
PTRACE_EVENT_EXEC       = 4
PTRACE_EVENT_VFORK_DONE = 5
PTRACE_EVENT_EXIT       = 6

# reverse map
PTRACE_EVENTS = {
    PTRACE_EVENT_FORK       : "FORK"       ,
    PTRACE_EVENT_VFORK      : "VFORK"      ,
    PTRACE_EVENT_CLONE      : "CLONE"      ,
    PTRACE_EVENT_EXEC       : "EXEC"       ,
    PTRACE_EVENT_VFORK_DONE : "VFORK_DONE" ,
    PTRACE_EVENT_EXIT       : "EXIT"       ,
}

# cpu flag
class user_regs_struct(Structure):
    _fields_ = (
        ("r15"      , c_ulong) ,
        ("r14"      , c_ulong) ,
        ("r13"      , c_ulong) ,
        ("r12"      , c_ulong) ,
        ("rbp"      , c_ulong) ,
        ("rbx"      , c_ulong) ,
        ("r11"      , c_ulong) ,
        ("r10"      , c_ulong) ,
        ("r9"       , c_ulong) ,
        ("r8"       , c_ulong) ,
        ("rax"      , c_ulong) ,
        ("rcx"      , c_ulong) ,
        ("rdx"      , c_ulong) ,
        ("rsi"      , c_ulong) ,
        ("rdi"      , c_ulong) ,
        ("orig_rax" , c_ulong) ,
        ("rip"      , c_ulong) ,
        ("cs"       , c_ulong) ,
        ("eflags"   , c_ulong) ,
        ("rsp"      , c_ulong) ,
        ("ss"       , c_ulong) ,
        ("fs_base"  , c_ulong) ,
        ("gs_base"  , c_ulong) ,
        ("ds"       , c_ulong) ,
        ("es"       , c_ulong) ,
        ("fs"       , c_ulong) ,
        ("gs"       , c_ulong)
        )
        
def ptrace(cmd, pid, addr, data):
    rtn = libc_ptrace(cmd, pid, addr, data)
    return c_long(rtn).value

def ptrace_getregs(pid):
    regs = user_regs_struct()
    ptrace(PTRACE_GETREGS, pid, 0, addressof(regs))
    return regs

def ptrace_setregs(pid, regs):
    ptrace(PTRACE_SETREGS, pid, 0, addressof(regs))

def ptrace_syscall(pid):
    ptrace(PTRACE_SYSCALL, pid, 0, 0)

def ptrace_traceme():
    ptrace(PTRACE_TRACEME, 0, 0, 0)

def ptrace_peek(pid, addr):
    word = ptrace(PTRACE_PEEKDATA, pid, addr, 0)
    return struct.pack("L", word)

def ptrace_poke(pid, addr, data):
    ptrace(PTRACE_POKEDATA, pid, addr, data)

def byte2word(byte):
    return struct.unpack("L", byte)[0]