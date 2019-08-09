# -*- coding: utf-8 -*-
import os
import time
import logging
import re
import click
import pyinotify
import socket
import select
import errno

BATSKY_SOCK_DIR = '/tmp/batsky'

fooleds = {}
fd2fooleds = {}

logger = logging.getLogger()


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
            logger.debug("IOError while opening proc file: {} {} ".format(pathname, str(e)))
    
        self.nb_call = 1
        self.status = 'active'

        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connected = False
        while not connected:
            try: 
                self.sock.connect(pathname)
                connected = True
            except OSError as error:
                if error.errno == errno.ECONNREFUSED:
                    logger.debug("Connection refused for: %s",  pathname)
                    time.sleep(0.001)
                    connected = False
    
        given_pid_bytes = self.sock.recv(4)
        given_pid = int.from_bytes(given_pid_bytes,byteorder='little')
        
        assert self.pid == given_pid

        sec = self.sock.recv(8)
        usec = self.sock.recv(8)
        #logger.debug("New sock: %d",  self.sock.fileno())
        logger.debug("E:{}: {}, time: {}.{}".format(self.pid, self.nb_call,
                                                    int.from_bytes(sec,byteorder='little'),
                                                    int.from_bytes(usec,byteorder='little')))
        #print("First echo, time: {}.{}".format(int.from_bytes(sec,byteorder='little'),
        #                                       int.from_bytes(usec,byteorder='little')))
        
        self.sock.send(sec)
        self.sock.send(usec)
        fd2fooleds[self.sock.fileno()] = self
        # Signal main loop of the new participant arrival
        os.write(select_pipe_write, b'x')


class EventHandler(pyinotify.ProcessEvent):
    def process_IN_CREATE(self, event):
        logger.debug("Creating: %s", event.pathname)
        process_fooled =  ProcessFooled(event.pathname)
        fooleds[process_fooled.pid] = process_fooled
        logger.debug("Pid {} fd {} Cmdline: {}".format(process_fooled.pid,
                                                       process_fooled.sock.fileno(),
                                                       process_fooled.cmdline))
        
        
    def process_IN_DELETE(self, event):
        #logger.debug("Removing: %s", event.pathname)
        pid = get_pid(event.pathname)
        if pid:
            fooleds[get_pid(pid)].status="finished"
        else:
            logger.debug("Not a fooled process endpoint")
        

@click.command()
@click.option('-e', '--echo', is_flag=True, help='Echo the time observed by the intercepted.')
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
@click.option('-m', '--master', type=click.STRING, help='Specify which hostname is the master.')
def cli(echo,debug,logfile, master):

    if debug:
        logger.setLevel(logging.DEBUG)

    if logfile:
        fh = logging.FileHandler(logfile)
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s %(levelname)-6s %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh) 

    else:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s %(levelname)-6s %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    logger.info('Master: %s', master)

    if not os.path.exists(BATSKY_SOCK_DIR):
        os.makedirs(BATSKY_SOCK_DIR)
        
    notifier = pyinotify.ThreadedNotifier(wm, EventHandler())
    notifier.start()
    
    wdd = wm.add_watch(BATSKY_SOCK_DIR, mask, rec=True)
    
    # main loop
    while True:
        #logger.debug("Main loop: wait on select")
        #logger.debug("select_pipe_read: %d", select_pipe_read)
        ready_fds = select.select(list(fd2fooleds.keys()) + [select_pipe_read], [], list(fd2fooleds.keys()) + [select_pipe_read])
        for fd in ready_fds[0]:
            if select_pipe_read in ready_fds[0]:
                # Add another fd to my_read_fds, etc.
                #logger.debug("New participant")
                a= os.read(select_pipe_read, 1)
                #logger.debug("read select_pipe: %d",a)
            else:
                #logger.debug('receive from: %d', fd)
                fool = fd2fooleds[fd]
                sock = fool.sock
                sec = sock.recv(8)
                if sec == b'':
                    sock.close()
                    fd2fooleds.pop(fd)
                    #logger.debug("Socket is closed: %d", fd)
                else:
                    usec = sock.recv(8)
                    fool.nb_call += 1
                    logger.debug("E:{}: {}, time: {}.{}".format(fool.pid, fool.nb_call,
                                                          int.from_bytes(sec,byteorder='little'),
                                                          int.from_bytes(usec,byteorder='little')))
                    sock.send(sec)
                    sock.send(usec)
        for fd in ready_fds[2]:
            logger.debug("Something happen to fd: %d", fd) 
        
    notifier.stop()
    
