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
import signal

BATSKY_SOCK_DIR = '/tmp/batsky'
BATSKY_NOTIFY_SOCK = BATSKY_SOCK_DIR + '/notify.sock'
CONTROLLER_PORT = 27000

fooleds = {}
fd2fooleds = {}

logger = logging.getLogger()

controller_name = ''
controller_sock = None

ask_controller = True


def connect_controller():
    global controller_sock
    delay = 0.001
    controller_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connected = False
    while not connected:
        try: 
            controller_sock.connect((controller_name, CONTROLLER_PORT))
            connected = True
        except OSError as error:
            if error.errno == errno.ECONNREFUSED:
                logger.debug("Try to connect to controller: {}".format(controller_name))
                time.sleep(delay)
                if delay < 0.7:
                    delay = 1.3*delay
    logger.debug("Connected to controller: {}".format(controller_name))
    
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
        simulated_time = ''
        while simulated_time == '' : 
            try:
                controller_sock.send(('{}.{}'.format(int.from_bytes(sec,byteorder='little'),
                                                     int.from_bytes(usec,byteorder='little'))).encode('utf8')
                )
                
                simulated_time = (controller_sock.recv(32)).decode('utf8')
            except socket.error as e:
                logger.info("Controller connection failed: {}".format(e))
            if simulated_time == '':
                logger.debug("Try to reconnect with controller: {}".
                             format(controller_name))
                connect_controller()
                time.sleep(.1)
                
        sec_usec = simulated_time.split('.')
        
        sec = int.to_bytes(int(sec_usec[0]), 8, byteorder='little')
        usec = b'\x00\x00\x00\x00\x00\x00\x00\x00'
        if len(sec_usec) == 2:
            usec = int.to_bytes(int(sec_usec[1]), 8, byteorder='little') 

    # Else echo time
  
    try:
        fooled.sock.send(sec)
        fooled.sock.send(usec)
    except socket.error as e:
        return False
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

def handler(signum, frame):
    print("Signal");
        
@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
@click.option('-c', '--controller', type=click.STRING, help='Specify which hostname is the controller.')
@click.option('-o', '--controller-options', type=click.STRING,
              help='Specify options for the controller (use quoted string).')
@click.option('-n', '--notifyer-options', type=click.STRING,
              help='Specify options for the notifyer (use quoted string).')
@click.option('-m', '--mode', type=click.STRING,
              help='Specify particular execution mode: echo')
@click.option('-u', '--not-launch-controller', is_flag=True, default=False,
              help='Not launch controller.')
def cli(debug, logfile, controller, controller_options, notifyer_options, mode, not_launch_controller):

    #def handler(signum, frame):
    #    logger.info("Receive Signal: {} {}".format(signum, frame));
        
    #for i in [x for x in dir(signal) if x.startswith("SIG")]:
    #    try:
    #        signum = getattr(signal,i)
    #        signal.signal(signum, handler)
    #        print(i,signum)
    #    except (OSError, ValueError) as m: #OSError for Python3, RuntimeError for 2
    #        print ("Skipping {}".format(i))
                
    if mode and mode == 'echo':
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
    global controller_name
    controller_name = controller
    
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
    

    if controller and controller==socket.gethostname() and not not_launch_controller:
        cmd = ['batsky-controller']
        if controller_options:
            cmd += controller_options.split()
        subprocess.Popen(cmd)

    
    if controller:
        connect_controller()
        
    # main loop
    while True:
        #logger.debug("Main loop: wait on select")
        #logger.debug("select_pipe_read: %d", select_pipe_read)
        ready_fds = select.select(list(fd2fooleds.keys()) + [batsky_notify_sock.fileno()] , [], list(fd2fooleds.keys()) + [batsky_notify_sock.fileno()])
        
        #print(ready_fds[0])
        #for fd in ready_fds[2]: #error
        #    logger.error("Select: socker error : {}".format(fd))
        #    if fd == controller_sock.fileno():
        #        logger.debug("Select: error connection with controller: {}, try to reconnect".
        #                     format(controller_name))
        #        connect_controller()
                
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

    logger.debug("Something strange happen") 
    notifier.stop()
    
