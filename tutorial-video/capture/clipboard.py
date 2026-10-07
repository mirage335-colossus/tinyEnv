#!/usr/bin/env python3
"""Serve one UTF-8 clipboard value on an owned virtual X11 display."""
import ctypes as C, os, sys
X=C.CDLL('libX11.so.6')
Display=C.c_void_p; Window=C.c_ulong; Atom=C.c_ulong; Time=C.c_ulong
class SelectionRequest(C.Structure):
 _fields_=[('type',C.c_int),('serial',C.c_ulong),('send_event',C.c_int),('display',Display),('owner',Window),('requestor',Window),('selection',Atom),('target',Atom),('property',Atom),('time',Time)]
class SelectionNotify(C.Structure):
 _fields_=[('type',C.c_int),('serial',C.c_ulong),('send_event',C.c_int),('display',Display),('requestor',Window),('selection',Atom),('target',Atom),('property',Atom),('time',Time)]
class Event(C.Union):
 _fields_=[('type',C.c_int),('request',SelectionRequest),('notify',SelectionNotify),('padding',C.c_long*24)]
X.XOpenDisplay.argtypes=[C.c_char_p];X.XOpenDisplay.restype=Display
X.XDefaultRootWindow.argtypes=[Display];X.XDefaultRootWindow.restype=Window
X.XCreateSimpleWindow.argtypes=[Display,Window,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_uint,C.c_ulong,C.c_ulong];X.XCreateSimpleWindow.restype=Window
X.XInternAtom.argtypes=[Display,C.c_char_p,C.c_int];X.XInternAtom.restype=Atom
X.XSetSelectionOwner.argtypes=[Display,Atom,Window,Time]
X.XChangeProperty.argtypes=[Display,Window,Atom,Atom,C.c_int,C.c_int,C.c_void_p,C.c_int]
X.XSendEvent.argtypes=[Display,Window,C.c_int,C.c_long,C.POINTER(Event)]
X.XNextEvent.argtypes=[Display,C.POINTER(Event)];X.XFlush.argtypes=[Display]
d=X.XOpenDisplay(os.environ['DISPLAY'].encode())
if not d:raise RuntimeError('Cannot open display')
w=X.XCreateSimpleWindow(d,X.XDefaultRootWindow(d),0,0,1,1,0,0,0)
a=lambda s:X.XInternAtom(d,s.encode(),0)
clipboard,targets,utf8,string,atom=a('CLIPBOARD'),a('TARGETS'),a('UTF8_STRING'),a('STRING'),a('ATOM')
data=sys.stdin.buffer.read();buf=C.create_string_buffer(data)
X.XSetSelectionOwner(d,clipboard,w,0);X.XFlush(d)
while True:
 e=Event();X.XNextEvent(d,C.byref(e))
 if e.type!=30:continue
 r=e.request;prop=r.property or r.target;ok=True
 if r.target==targets:
  allowed=(Atom*3)(targets,utf8,string);X.XChangeProperty(d,r.requestor,prop,atom,32,0,allowed,3)
 elif r.target in [utf8,string]:X.XChangeProperty(d,r.requestor,prop,r.target,8,0,buf,len(data))
 else:ok=False
 n=Event();n.notify=SelectionNotify(31,0,1,d,r.requestor,r.selection,r.target,prop if ok else 0,r.time)
 X.XSendEvent(d,r.requestor,0,0,C.byref(n));X.XFlush(d)
