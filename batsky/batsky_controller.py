#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from enum import Enum
import logging
import time
import click
import zmq
from sortedcontainers import SortedDict # for fake_events (test only)
from ClusterShell.NodeSet import NodeSet

RJMS_WARMUP_DURATION = 0.5
RJMS_WAKE_UP_PERIOD = 1.0

CONTROLLER_PORT = 27000
BATSKY_JOB_PORT = 27100
logger = logging.getLogger()

class Job(object):

    class State(Enum):
        UNKNOWN = -1
        IN_SUBMISSON = 0
        SUBMITTED = 1
        RUNNING = 2
        COMPLETED_SUCCESSFULLY = 3
        COMPLETED_FAILED = 4
        COMPLETED_WALLTIME_REACHED = 5
        COMPLETED_KILLED = 6
        REJECTED = 7
        IN_KILLING = 8

    def __init__(
            self,
            id,
            subtime,
            walltime,
            res,
            profile,
            json_dict):
        self.id = id
        self.submit_time = subtime
        self.requested_time = walltime
        self.requested_resources = res
        self.profile = profile
        self.finish_time = None  # will be set on completion by batsim
        self.job_state = Job.State.UNKNOWN
        self.return_code = None
        self.progress = None
        self.json_dict = json_dict
        self.profile_dict = None
        self.allocation = None
        self.metadata = None

    def __repr__(self):
        return(
            ("{{Job {0}; sub:{1} res:{2} reqtime:{3} prof:{4} "
                "state:{5} ret:{6} alloc:{7}, meta:{8}}}\n").format(
            self.id, self.submit_time, self.requested_resources,
            self.requested_time, self.profile,
            self.job_state,
            self.return_code, self.allocation, self.metadata))
       
    @staticmethod
    def from_json_string(json_str):
        json_dict = json.loads(json_str)
        return Job.from_json_dict(json_dict)

    @staticmethod
    def from_json_dict(json_dict):
        return Job(json_dict["id"],
                   json_dict["subtime"],
                   json_dict.get("walltime", -1),
                   json_dict["res"],
                   json_dict["profile"],
                   json_dict)

#class BatskySched(BatsimScheduler):
class BatskySched(object):
    def __init__(self, controller):
        self.controller = controller
        self.bs = None
                
    def onAfterBatsimInit(self):
        pass

    def onSimulationBegins(self):

        self.controller.rjms_warmup()

        logger.info('Simulation Begins')
        if self.bs.time() > RJMS_WAKE_UP_PERIOD:
            logger.error("Batsim time, greater than RJMS_WAKE_UP_PERIOD is not supported (TODO): {} {}".
                         format(self.bs.time(), RJMS_WAKE_UP_PERIOD))
        else:
            self.controller.rjms_simulated_start_time = self.controller.rjms_simulated_time
            
        self.rjms_round()

    def onSimulationEnds(self):
        logger.info("That's All Folk")
        exit()
        
    def onJobSubmission(self, job):
        logger.debug('onJobSubmission')
        self.controller.rjms_job_submission(job)
        self.rjms_round()

    def onJobCompletion(self, job):
        logger.debug('onJobCompletion')
        self.controller.rjms_job_completion(job)           
        self.rjms_round()
    
    def onRequestedCall(self):
        logger.debug('onRequestedCall')
        self.rjms_round()

    def rjms_round(self):
        round_time, rjms_events = self.controller.rjms_round(self.bs.time())
        if rjms_events:
            logger.error('TODO process event')
            pass

        # add call me latter
        self.bs.wake_me_up_at(self.bs.time() + RJMS_WAKE_UP_PERIOD)
        
        #self.bs.execute_jobs(jobs)
        
class FakeBatsim(object):
    
    def __init__(self, batsky_scheduler):
        self.batsky_sched = batsky_scheduler
        self.batsky_sched.bs = self

        self.jobs = dict()
        
        self._current_time = 0
        self.nb_jobs_submitted = 0
        
        self.running_simulation = False
        
        self._fake_events = SortedDict({
            0.0: [{'timestamp': 0.0, 'type': 'SIMULATION_BEGINS', 'data': {}}],
            5.0: [{'timestamp': 5.0, 'type': 'JOB_SUBMITTED', 'data':
                   {'job_id': 'w0!1',
                    'job': {'id':'w0!1', 'subtime': 5.0, 'res': 1, 'walltime': 12.0 },
                    'profile': {'type': 'delay', 'delay': 10}
                   }}],
            20.0: [{'timestamp': 20.0, 'type': 'SIMULATION_ENDS', 'data': {}}] 
        })

        #0.0: [{'type': '', 'data': {}}],
        
        self._read_bat_msg()
        
        self.batsky_sched.onAfterBatsimInit()


    def time(self):
        return self._current_time

    def consume_time(self, t):
        self._current_time += float(t)
        return self._current_time
          
        return True
    def wake_me_up_at(self, at_time):
        events= []
        if at_time in self._fake_events:
            events = self._fake_events.get(at_time)
        events.append({'timestamp': at_time, 'type': 'REQUESTED_CALL', 'data': {}})
        self._fake_events.update({at_time: events})

    def execute_jobs(self, jobs):
        pass
        # "timestamp": 1012,
        #"type": "EXECUTE_JOB",
        #"data": {
        #"job_id": "workload!job_1235",
        #"alloc": "12-100",
    def start(self):
        cont = True
        while cont:
            cont = self.do_next_event()
    
    def do_next_event(self):
        return self._read_bat_msg()

    def _read_bat_msg(self):
        (batsim_time, events) = self._fake_events.popitem(index=0)
        logger.debug('Batsim time {}  Events: {}'.format(batsim_time, events))
        self._current_time = batsim_time

        for event in events:
            event_type = event['type']
            event_data = event.get('data', {})
            
            if event_type == 'SIMULATION_BEGINS':
                assert not self.running_simulation, "A simulation is already running (is more than one instance of Batsim active?!)"
                self.running_simulation = True
                self.batsky_sched.onSimulationBegins()

            elif event_type == 'SIMULATION_ENDS':
                self.batsky_sched.onSimulationEnds()

            elif event_type == 'JOB_SUBMITTED':
                job_id = event_data['job_id']
                job, profile = self.get_job_and_profile(event)
                job.job_state = Job.State.SUBMITTED
                self.nb_jobs_submitted += 1
                self.jobs[job_id] = job
                self.batsky_sched.onJobSubmission(job)
                
            elif event_type == 'JOB_COMPLETED':
                job_id = event_data['job_id']
                j = self.jobs[job_id]
                j.finish_time = event['timestamp']
                self.batsky_sched.onJobCompletion(j)
                if j.job_state == Job.State.COMPLETED_WALLTIME_REACHED:
                    self.nb_jobs_timeout += 1
                elif j.job_state == Job.State.COMPLETED_FAILED:
                    self.nb_jobs_failed += 1
                elif j.job_state == Job.State.COMPLETED_SUCCESSFULLY:
                    self.nb_jobs_successful += 1
                elif j.job_state == Job.State.COMPLETED_KILLED:
                    self.nb_jobs_killed += 1
                self.nb_jobs_completed += 1
                
            elif event_type == 'REQUESTED_CALL':
                self.batsky_sched.onRequestedCall()

        return True

    def get_job_and_profile(self, event):
        json_dict = event["data"]["job"]
        job = Job.from_json_dict(json_dict)
    
        if "profile" in event["data"]:
            profile = event["data"]["profile"]
        else:
            profile = {}
            
        return job, profile


    
class Controller(object):
    def __init__(self, mode):
        self.mode = mode
        self.context = zmq.Context()
        self.batsky_socket = self.context.socket(zmq.STREAM)
        self.batsky_socket.bind("tcp://*:" + str(CONTROLLER_PORT))

        self.jobs_socket = self.context.socket(zmq.PULL)
        self.jobs_socket.bind("tcp://*:" + str(BATSKY_JOB_PORT))
        
        self.poller = zmq.Poller()
        self.poller.register(self.batsky_socket, zmq.POLLIN)
        self.poller.register(self.jobs_socket, zmq.POLLIN)


        self.rjms_start_time = None
        self.rjms_simulated_start_time = 0.0
        self.rjms_simulated_time = 0.0
        
        self.batskyers = {}

        self.running_jobs = {}


    def read_basky_socket(self):
        client_id_b, message_b = self.batsky_socket.recv_multipart()  
        client_id = int.from_bytes(client_id_b,byteorder='big')
        message = message_b.decode('utf8')
        if message == u'':
            logger.info("(de)connexion from id: {} {}".format(client_id_b, client_id))
        return client_id_b, client_id, message

    def send_batsky_socket(self, client_id_b, message):
        message_b = (message).encode('utf8')        
        self.batsky_socket.send_multipart((client_id_b, message_b))
        
    def rjms_warmup(self):
        logger.debug('RJMS Warm Up')
        while (not self.rjms_start_time or
               (self.rjms_simulated_time - self.rjms_start_time) < RJMS_WARMUP_DURATION):
            for sock in dict(self.poller.poll()):
                if sock == self.batsky_socket:
                    client_id_b, client_id, message = self.read_basky_socket()
                    if message:
                        requested_time = float(message)
                        logger.info("Request client_id, time: {} {}".
                                    format(client_id, requested_time))

                        if not self.rjms_start_time:
                            self.rjms_start_time = requested_time
                        
                        # Force monotonic time
                        if requested_time > self.rjms_simulated_time:
                            self.rjms_simulated_time = requested_time
                        
                        # Echo time during warmup phase
                        rjms_simulated_time_str = '%.6f'%(self.rjms_simulated_time)
                        logger.info('RJMS Simulated Time {}'.format(rjms_simulated_time_str))
                        self.send_batsky_socket(client_id_b, rjms_simulated_time_str)
                else:
                    logger.error('Not the expected socket')

    def rjms_job_submission(self, job):
        logger.debug("TODO rjms_job_submission")

    def rjms_job_completion(self, job):
        logger.debug("TODO rjms_job_completion")
        
    def rjms_round(self, batsim_time):
        rjms_events = []
        self.rjms_simulated_time = self.rjms_simulated_start_time + batsim_time

        round_time_t0 = time.time()
        logger.debug('Batsim time: {} , RJMS Simulated Time: {}'.
                     format(batsim_time, self.rjms_simulated_time))
        
        for sock in dict(self.poller.poll()):
            if sock == self.batsky_socket:
                client_id_b, client_id, message = self.read_basky_socket()
                if message:
                    requested_time = float(message)
                    logger.info("Request client_id, time: {} {}".
                                format(client_id, requested_time))
                    self.send_batsky_socket(client_id_b, '%.6f'%(self.rjms_simulated_time) )
        
        round_time = time.time() - round_time_t0
        logger.debug('Controller Round time: {}'.format(round_time))
        #import pdb; pdb.set_trace()
        return round_time, rjms_events
        
    def run(self, loop=True):
        while True:
            
            socks = dict(self.poller.poll())
            
            for s in socks:

                if s == self.socket_jobs:
                    msg = self.socket_jobs.recv_json()
                    logger.debug('Receive from job: '.format(msg))
                else:
                    
                    client_id_b, message_b = self.batsky_socket.recv_multipart()

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
                            self.simulated_time += 0.0000001 # 100 ns
                        elif self.mode == 'fast2':
                            self.simulated_time = self.start_time + 2 * (requested_time - self.start_time)
                        elif self.mode == 'zeroed':
                            self.simulated_time = requested_time - self.start_time
                        else: # echo mode by default
                            self.simulated_time = requested_time
                            #delta = (requested_time - self.start_time)
                            #if delta > self.simulated_time:
                            #    self.simulated_time = delta

                        simulated_time_str = '%.6f'%(self.simulated_time)
                    
                        logger.info('Simulated Time {}'.format(simulated_time_str))
                        message_b = (simulated_time_str).encode('utf8')
                        self.batsky_socket.send_multipart((client_id_b, message_b))
                    
            if not loop: # for test unit purpose
                break

    
@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
@click.option('-s', '--socket-endpoint', type=click.STRING,
              help='Batsim socket endpoint to use.', default='tcp://*:28000')
@click.option('-m', '--mode', type=click.STRING, help ='Time mode: echo, incr, zeroed, fast10', default='fast2')
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
    batsky_scheduler = BatskySched(controller)
    fake_batsim = FakeBatsim(batsky_scheduler)
    
    fake_batsim.start()
    
if __name__ == '__main__':
    cli()
