#!/usr/bin/env python3
"""Prints what the beat sender is sending (proves it works without Unreal).
   python3 beat_listen.py [port]      (default 7701)"""
import socket, sys
from beat_sender import osc_decode
port = int(sys.argv[1]) if len(sys.argv) > 1 else 7701
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(('0.0.0.0', port))
print('listening on %d' % port)
while True:
    addr, args = osc_decode(s.recv(2048))
    if addr in ('/ney/onbeat',) and args == [1] or addr in ('/ney/section', '/ney/tempo'):
        print(addr, *args, flush=True)
