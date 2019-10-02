#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import click
import socket
import time
import errno

CONTROLLER_PORT = 27000

logger = logging.getLogger()

def connect_controller(controller):
    delay = 0.02
    controller_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connected = False
    while not connected:
        try: 
            controller_sock.connect((controller, CONTROLLER_PORT))
            connected = True
        except OSError as error:
            if error.errno == errno.ECONNREFUSED:
                logger.debug("Try to connect to controller: {}".format(controller))
                time.sleep(delay)
                if delay < 1:
                    delay = 1.5*delay
    logger.debug("Connected to controller: {}".format(controller))
    return controller_sock

@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-c', '--controller', type=click.STRING, default='localhost',
              help='Specify which hostname is the controller.')
@click.option('-p', '--period', type=click.FLOAT, default=0.5, help='Time period beetwen requestqs.')
def cli(debug, controller, period):
    
    if debug:
        logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)-6s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    controller_sock = connect_controller(controller)

    logger.debug('Period: {}'.format(period))
    
    while True:
        now = time.time()
        logger.debug('Now: {}'.format(now))
               
        controller_sock.send(str(now).encode('utf8'))                                        
        simulated_time = (controller_sock.recv(32)).decode('utf8')
        logger.debug('Simulated time: {}'.format(simulated_time))
        time.sleep(period)

if __name__ == '__main__':
    cli()
