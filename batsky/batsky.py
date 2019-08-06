# -*- coding: utf-8 -*-
import os
import time
import logging
import re
import click
import pyinotify
import socket
import select

LOG = logging.getLogger()

BATSKY_SOCK_DIR = '/tmp/batsky'

fooleds = {}
fd2fooleds = {}

select_pipe_read, select_pipe_write  = os.pipe()

wm = pyinotify.WatchManager()  # Watch Manager
mask = pyinotify.IN_DELETE | pyinotify.IN_CREATE  # watched events


def get_pid(pathname):
    pid = -1
    match = re.match(r'\D+(\d+)\D+',pathname)
    if match:
        pid = int(match.group(1)) 
    return pid

class ProcessFooled(object):
    def __init__(self, pathname):
        self.pathname = pathname
        self.pid = get_pid(pathname)
        try:
            with open("/proc/{}/cmdline".format(self.pid), 'r') as cmdline_file:
                self.cmdline = cmdline_file.read().split('\0')[:-1]
                #ret_val = data.replace('\0', ' '))
        except IOError as e:
            print("IOError while opening proc file: {} {} ".format(pathname, str(e)))
    
        self.nb_call = 1
        self.status = 'active'

        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(pathname)

        given_pid_bytes = self.sock.recv(4)
        given_pid = int.from_bytes(given_pid_bytes,byteorder='little')
        assert self.pid == given_pid

        sec = self.sock.recv(8)
        usec = self.sock.recv(8)
        print("First echo, time: ", int.from_bytes(sec,byteorder='little'), int.from_bytes(usec,byteorder='little'))
        self.sock.send(sec)
        self.sock.send(usec)
        fd2fooleds[self.sock.fileno()] = self
        # Signal main loop of the new participant arrival 
        os.write(select_pipe_write, b'x')


class EventHandler(pyinotify.ProcessEvent):
    def process_IN_CREATE(self, event):
        print("Creating:", event.pathname)
        process_fooled =  ProcessFooled(event.pathname)
        fooleds[process_fooled.pid] = process_fooled
        print("Cmdline:", process_fooled.cmdline)
        
        
    def process_IN_DELETE(self, event):
        print("Removing:", event.pathname)
        pid = get_pid(event.pathname)
        if pid:
            fooleds[get_pid(pid)].status="finished"
        else:
            print("Not a fooled process endpoint")
        

@click.command()
@click.option('-e', '--echo', is_flag=True, help='Echo the time observed by the intercepted.')
def cli(echo):

    if not os.path.exists(BATSKY_SOCK_DIR):
        os.makedirs(BATSKY_SOCK_DIR)
        
    notifier = pyinotify.ThreadedNotifier(wm, EventHandler())
    notifier.start()
    
    wdd = wm.add_watch(BATSKY_SOCK_DIR, mask, rec=True)
    
    # main loop
    while True:
        print("Main loop: wait on select")
        ready_fds = select.select(list(fd2fooleds.keys()) + [select_pipe_read], [], [])
        for fd in ready_fds[0]:
            if select_pipe_read in ready_fds[0]:
                # Add another fd to my_read_fds, etc.
                print("New participant")
                os.read(select_pipe_read, 1)
            else:
                fool = fd2fooleds[fd]
                sock = fool.sock
                sec = sock.recv(8)
                usec = sock.recv(8)
                fool.nb_call += 1
                print("echo # {}, time: {}.{}".format(fool.nb_call,
                                                      int.from_bytes(sec,byteorder='little'),
                                                      int.from_bytes(usec,byteorder='little'))
                      )
                sock.send(sec)
                sock.send(usec)
        
    notifier.stop()
    
