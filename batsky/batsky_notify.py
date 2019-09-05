# -*- coding: utf-8 -*-
import os
import time
import logging
import re
import click
import pyinotify
import asyncio
import socket

import errno

BATSKY_SOCK_DIR = '/tmp/batsky'
BATSKY_NOTIFY_SOCK = BATSKY_SOCK_DIR + '/notify.sock'

logger = logging.getLogger()

wm = pyinotify.WatchManager()  # Watch Manager
loop = asyncio.get_event_loop()
mask = pyinotify.IN_CREATE  # watched events

batsky_sock = None

def get_pid(pathname):
    pid = -1
    match = re.match(r'\D+(\d+)\D+',pathname)
    if match:
        pid = int(match.group(1)) 
    return pid

class EventHandler(pyinotify.ProcessEvent):
    def process_IN_CREATE(self, event):
        logger.debug("Creating: %s", event.pathname)
        #process_fooled =  ProcessFooled(event.pathname)
        #fooleds[process_fooled.pid] = process_fooled
        #logger.debug("Pid {} fd {} Cmdline: {}".format(process_fooled.pid,
        #                                               process_fooled.sock.fileno(),
        #                                               process_fooled.cmdline))
        pid = get_pid(event.pathname)
        if pid != -1:
            batsky_sock.send(pid.to_bytes(4, byteorder='little'))
            logger.debug("signal sent for: {}".format(pid))

@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
def cli(debug,logfile):

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

    if not os.path.exists(BATSKY_SOCK_DIR):
        os.makedirs(BATSKY_SOCK_DIR)

    try:
        os.unlink(BATSKY_NOTIFY_SOCK)
    except OSError:
        if os.path.exists(BATSKY_NOTIFY_SOCK):
            raise

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(BATSKY_NOTIFY_SOCK)
    sock.listen(1)
    global batsky_sock 
    batsky_sock , _ = sock.accept()

    logger.info('\nBatsky connected...')
        
    notifier = pyinotify.AsyncioNotifier(wm, loop, default_proc_fun=EventHandler())
    
    wdd = wm.add_watch(BATSKY_SOCK_DIR, mask, rec=True)
    
    try:
        loop.run_forever()
    except:
        logger.info('\nShutting down...')

    loop.stop()    
    notifier.stop()
    
