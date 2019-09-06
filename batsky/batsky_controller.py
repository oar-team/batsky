# -*- coding: utf-8 -*-

import logging
import re
import click
import zmq


CONTROLLER_PORT = 27000

logger = logging.getLogger()

class Batsim(object):
    def __init__(self):
        pass

class Controller(object):
    def __init__(self, mode):
        self.mode = mode
        self.context = zmq.Context()
        self.socket_batsky = self.context.socket(zmq.STREAM)
        self.socket_batsky.bind("tcp://*:" + str(CONTROLLER_PORT))

        self.batsim = Batsim()

        self.poller = zmq.Poller()
        self.poller.register(self.socket_batsky, zmq.POLLIN)

        self.start_time = None
        self.simulated_time = 0

        self.batskyers = {} 
        
    def run(self, loop=True):
        while True:
            socks = dict(self.poller.poll())
            client_id_b, message_b = self.socket_batsky.recv_multipart()

            client_id = int.from_bytes(client_id_b,byteorder='big')

            message = message_b.decode('utf8')
            if message == u'':
                logger.info("(de)connexion from id: {} {}".format(client_id_b, client_id))
            else:
                requested_time = float(message)
                logger.info("received from id: {} {}".format(client_id_b, client_id))
                logger.info("requested time: {}".format(requested_time))
                if not self.start_time:
                    self.start_time = requested_time
                    logger.info("Start_time: {} sec".format(self.start_time))
                if self.mode == 'incr':
                    self.simulated_time += 0.000001
                else:
                    delta = (requested_time - self.start_time)/10 # fast machine ;)
                    if delta > self.simulated_time:
                        self.simulated_time = delta

                simulated_time_str = '%.6f'%(self.simulated_time)
                    
                logger.info('Simulated Time {}'.format(simulated_time_str))
                message_b = (simulated_time_str).encode('utf8')
                self.socket_batsky.send_multipart((client_id_b, message_b))
                
            if not loop: # for test unit purpose
                break

    
@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
@click.option('-s', '--socket-endpoint', type=click.STRING,
              help='Batsim socket endpoint to use.', default='tcp://*:28000')
@click.option('-m', '--mode', type=click.STRING, help ='Time mode', default='incr')
def cli(debug, logfile, socket_endpoint, mode):
    
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
        
    logger.info('Controller running')

    controller = Controller(mode)
    controller.run()
