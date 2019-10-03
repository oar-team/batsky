#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import socket
import zmq
import click
import logging

FAKE_JOB_PORT = 27100

logger = logging.getLogger()

@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
@click.option('-c', '--controller', type=click.STRING, help='Specify which hostname is the controller.')
@click.option('-w', '--workload-jobid', type=click.STRING, help="Wokload's Job id")
def cli(debug, logfile, controller, workload_jobid):
    
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
        
    logger.info('Job running: {}'.format(workload_jobid))
    
    context = zmq.Context()
    controller_sock = context.socket(zmq.PUSH)
    controller_sock.connect("tcp://{}:{}".format(controller, FAKE_JOB_PORT))

    finalize_sock = context.socket(zmq.PULL)
    finalize_port = finalize_sock.bind_to_random_port("tcp://*")
    
    # get the nodelist form Slurm
    nodeset = os.environ['SLURM_NODELIST']
    
    logger.debug('Job: {}, nodeset: {}, port {}'.format(workload_jobid, nodeset, finalize_port))
    controller_sock.send_json({'job_id': workload_jobid, 'nodeset': nodeset,
                               'hostname': socket.gethostname(), 'port': int(finalize_port)})

    # Wait
    logger.debug('Wait the finalized signal: {}'.format(workload_jobid))
    finalize_state = finalize_sock.recv_json()
    next_state = finalize_state['next_state']
    logger.info('Finalized with state: {}'.format(next_state))
    if next_state != 'completed':
        logger.erro('State "{}" not supported'.format(next_state))

if __name__ == '__main__':
    cli()
