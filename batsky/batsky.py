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
CONTROLLER_PORT = 27000

fooleds = {}
fd2fooleds = {}

logger = logging.getLogger()


select_pipe_read, select_pipe_write  = os.pipe()

wm = pyinotify.WatchManager()  # Watch Manager
mask = pyinotify.IN_DELETE | pyinotify.IN_CREATE  # watched events

controller_sock = None

def get_ask_send_time(fooled):

    sec = fooled.sock.recv(8)
    if sec == b'':
        fooled.sock.close()
        return False
    usec = fooled.sock.recv(8)
    fooled.nb_call += 1
    #logger.debug("New sock: %d",  self.sock.fileno())
    logger.debug("E:{}: {}, time: {}.{}".format(fooled.pid, fooled.nb_call,
                                                int.from_bytes(sec,byteorder='little'),
                                                int.from_bytes(usec,byteorder='little')))
    #print("First echo, time: {}.{}".format(int.from_bytes(sec,byteorder='little'),
    #                                       int.from_bytes(usec,byteorder='little')))
    # Ask time to controller
    controller_sock.send(('{}.{}'.format(int.from_bytes(sec,byteorder='little'),
                                                         int.from_bytes(usec,byteorder='little'))).encode('utf8')
    )

    simulated_time = (controller_sock.recv(32)).decode('utf8')
    sec_usec = simulated_time.split('.')

    sec = int.to_bytes(int(sec_usec[0]), 8, byteorder='little')
    usec = b'\x00\x00\x00\x00\x00\x00\x00\x00'
    if len(sec_usec) == 2:
        usec = int.to_bytes(int(sec_usec[1]), 8, byteorder='little') 

    fooled.sock.send(sec)
    fooled.sock.send(usec)
    
    return True

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
    
        self.nb_call = 0
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
    
        given_pid_bytes = self.sock.recv(4)
        given_pid = int.from_bytes(given_pid_bytes, byteorder='little')
        
        assert self.pid == given_pid

        if not get_ask_send_time(self):
            logger.error('Connection broken with: {} {}'.format(self.pid, self.cmdline))
        
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
        if event.pathname and type(event.pathname) == str: 
            logger.debug("Removing: %s", event.pathname)
            pid = get_pid(event.pathname)
            if pid:
                fooleds[get_pid(pid)].status="finished"
            else:
                logger.debug("Not a fooled process endpoint")
        else:
            logger.debug("Not a fooled process endpoint")

@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
@click.option('-c', '--controller', type=click.STRING, help='Specify which hostname is the controller.')
@click.option('-o', '--controller-options', type=click.STRING,
              help='Specify options for the controller (use quoted string).')
def cli(debug, logfile, controller, controller_options):

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
        
    logger.info('Controller: %s', controller)

    if not os.path.exists(BATSKY_SOCK_DIR):
        os.makedirs(BATSKY_SOCK_DIR)
        
    notifier = pyinotify.ThreadedNotifier(wm, EventHandler())
    notifier.start()
    
    wdd = wm.add_watch(BATSKY_SOCK_DIR, mask, rec=True)


    if controller and controller==socket.gethostname():
        import subprocess
        cmd = ['batsky-controller']
        if controller_options:
            cmd += controller_options.split()
        subprocess.Popen(cmd)

    global controller_sock
    
    if controller:
        controller_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connected = False
        while not connected:
            try: 
                controller_sock.connect((controller, CONTROLLER_PORT))
                connected = True
            except OSError as error:
                if error.errno == errno.ECONNREFUSED:
                    logger.debug("Try to connect to controller: {}".format(controller))
                    time.sleep(0.5)    
        
    # main loop
    while True:
        #logger.debug("Main loop: wait on select")
        #logger.debug("select_pipe_read: %d", select_pipe_read)
        ready_fds = select.select(list(fd2fooleds.keys()) + [select_pipe_read] , [], list(fd2fooleds.keys()) + [select_pipe_read])
        #print(ready_fds[0])
        for fd in ready_fds[0]:
            if fd == select_pipe_read:
                # Add another fd to my_read_fds, etc.
                #logger.debug("New participant")
                a= os.read(select_pipe_read, 1)
                #logger.debug("read select_pipe: %d",a)
            
            else:
                #logger.debug('receive from: %d', fd)
                assert(fd in fd2fooleds)
                fooled = fd2fooleds[fd]
        
                if not get_ask_send_time(fooled):
                     logger.info('Connection closed with: {} {}'.format(fooled.pid, fooled.cmdline))
                     del fd2fooleds[fd]

        for fd in ready_fds[2]:
            logger.debug("Something happen to fd: %d", fd) 
        
    notifier.stop()
    
