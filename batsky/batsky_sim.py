#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import zmq
import click
import logging


BATSIM_PORT = 28000

@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
@click.option('-c', '--controller', type=click.STRING, help='Specify which hostname is the controller.')
@click.option('-f', '--workload-file', type=click.STRING, help='Specify workload file.')
@click.option('-s', '--start-time', type=click.float, default=0.0,
              help='Specify start time of simulation')
def cli(debug, logfile, controller, workload_file):
    
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
        
    logger.info('Simple delay job only bat-simulator')
    
    context = zmq.Context()
    batsim_sock = context.socket(zmq.PAIR)
    batsim_sock.bind("tcp://*:{}".format(BATSIM_PORT))


    #controller_sock.send_json({'wjid': int(workload_jobid), 'nodeset': str(nodeset),
    #                           'port': int(finalize_port)})
    
if __name__ == '__main__':
    cli()
