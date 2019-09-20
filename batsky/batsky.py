# -*- coding: utf-8 -*-
import os
import time
import logging
import re
import click
import socket
import select
import errno
import subprocess

BATSKY_SOCK_DIR = '/tmp/batsky'
BATSKY_NOTIFY_SOCK = BATSKY_SOCK_DIR + '/notify.sock'
CONTROLLER_PORT = 27000

fooleds = {}
fd2fooleds = {}

logger = logging.getLogger()

controller_sock = None

ask_controller = True

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
    if ask_controller:
        controller_sock.send(('{}.{}'.format(int.from_bytes(sec,byteorder='little'),
                                             int.from_bytes(usec,byteorder='little'))).encode('utf8')
        )
        
        simulated_time = (controller_sock.recv(32)).decode('utf8')
        sec_usec = simulated_time.split('.')
        
        sec = int.to_bytes(int(sec_usec[0]), 8, byteorder='little')
        usec = b'\x00\x00\x00\x00\x00\x00\x00\x00'
        if len(sec_usec) == 2:
            usec = int.to_bytes(int(sec_usec[1]), 8, byteorder='little') 

    # Else echo time
    
    fooled.sock.send(sec)
    fooled.sock.send(usec)
    
    return True

class ProcessFooled(object):
    def __init__(self, pid):
        self.pid = pid
        self.pathname = "/tmp/batsky/{}_batsky.sock".format(pid)
        try:
            with open("/proc/{}/cmdline".format(self.pid), 'r') as cmdline_file:
                self.cmdline = cmdline_file.read().split('\0')[:-1]
                #ret_val = data.replace('\0', ' '))
        except IOError as e:
            logger.debug("IOError while opening proc file: {} {} ".format(self.pathname, str(e)))
    
        self.nb_call = 0
        self.status = 'active'

        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connected = False
        while not connected:
            try: 
                self.sock.connect(self.pathname)
                connected = True
            except OSError as error:
                if error.errno == errno.ECONNREFUSED:
                    logger.debug("Connection refused for: %s",  self.pathname)
                    time.sleep(0.001)
    
        given_pid_bytes = self.sock.recv(4)
        given_pid = int.from_bytes(given_pid_bytes, byteorder='little')
        
        assert self.pid == given_pid

        if not get_ask_send_time(self):
            logger.error('Connection broken with: {} {}'.format(self.pid, self.cmdline))
        
        fd2fooleds[self.sock.fileno()] = self
        # Signal main loop of the new participant arrival        

@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
@click.option('-c', '--controller', type=click.STRING, help='Specify which hostname is the controller.')
@click.option('-o', '--controller-options', type=click.STRING,
              help='Specify options for the controller (use quoted string).')
@click.option('-n', '--notifyer-options', type=click.STRING,
              help='Specify options for the notifyer (use quoted string).')
@click.option('-m', '--mode', type=click.STRING,
              help='Specify particular execution mode: echo', default='echo')
def cli(debug, logfile, controller, controller_options, notifyer_options, mode):

    if mode == 'echo':
        global ask_controller
        ask_controller = False
    
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

    # Launch notifyer
    cmd = ['batsky-notify']
    if notifyer_options:
            cmd += notifyer_options.split()
    subprocess.Popen(cmd)


    # connect to batsky_notify sock
    batsky_notify_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connected = False
    while not connected:
        try: 
            batsky_notify_sock.connect(BATSKY_NOTIFY_SOCK)
            connected = True
        except OSError as error:
            if error.errno == errno.ECONNREFUSED:
                logger.debug("Connection refused for:  batsky_notify sock")
                time.sleep(0.05)
                connected = False     
    logger.debug("Connected to batsky notifyer")
    

    if controller and controller==socket.gethostname():
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
        ready_fds = select.select(list(fd2fooleds.keys()) + [batsky_notify_sock.fileno()] , [], list(fd2fooleds.keys()) + [batsky_notify_sock.fileno()])
        #print(ready_fds[0])
        for fd in ready_fds[0]:
            if fd == batsky_notify_sock.fileno():
                # Add another fd to my_read_fds, etc.
                #logger.debug("New participant")
                #logger.debug("read select_pipe: %d",a)
                given_pid_bytes = batsky_notify_sock.recv(4)
                pid = int.from_bytes(given_pid_bytes,byteorder='little')
                
                process_fooled =  ProcessFooled(pid)
                fooleds[process_fooled.pid] = process_fooled
                logger.debug("Pid {} fd {} Cmdline: {}".format(process_fooled.pid,
                                                               process_fooled.sock.fileno(),
                                                               process_fooled.cmdline))
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
    
