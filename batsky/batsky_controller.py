#!/usr/bin/env python3

# TODO: switch to asynchronous launch (Popen) for sbatch

from enum import Enum
import logging
import time
import datetime
import click
import socket
import zmq
import json
from subprocess import call, Popen
from sortedcontainers import SortedDict # for fake_events (test only)
from ClusterShell.NodeSet import NodeSet

RJMS_WARM_UP_DURATION = 5.0
RJMS_COOL_DOWN_DURATION = 5.0

#RJMS_WAKE_UP_PERIOD = 0.1

RJMS_WAKE_UP_PERIOD_MIN = 0.05
RJMS_WAKE_UP_PERIOD_COEF = 1.2
RJMS_WAKE_UP_PERIOD_MAX = 64

RJMS_PULL_DURATION = 0.3
RJMS_PULL_INTER_SLEEP = 0.001

CONTROLLER_PORT = 27000
BATSKY_JOB_PORT = 27100

logger = logging.getLogger()

class RJMSJob(object):
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
        
    def __init__(self, id, batsim_job):
        self.id = id
        self.batsim_job = batsim_job
        self.allocation = None
        self.hostname = None
        self.port = None
        self.state = RJMSJob.State.UNKNOWN
    def __repr__(self):
        return(
            ("{{RJMS Job {0}; state: {1} port: {2} allocation: {3}}}\n").format(
                 self.id, self.state, self.port, self.allocation))

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
        self.previous_wake_up = -1
                
    def onAfterBatsimInit(self):
        pass

    def onSimulationBegins(self):

        self.controller.rjms_warmup()
        self.controller.rjms_real_simulation_start_time = time.time()
        
        logger.info('Simulation Begins')
        if self.bs.time() != 0:
            logger.error('Simulation Begin time different from 0 is not supported: {}'
                         .format(self.bs.time()))
        #if self.bs.time() > RJMS_WAKE_UP_PERIOD:
        #    logger.error("Batsim time, greater than RJMS_WAKE_UP_PERIOD is not supported (TODO): {} {}".
        #                 format(self.bs.time(), RJMS_WAKE_UP_PERIOD))
        else:
            self.controller.rjms_simulated_start_time = self.controller.rjms_simulated_time
            
        self.rjms_round()

    def onSimulationEnds(self):
        logger.info("That's All Folk")
        logger.info("Return into an echo mode, during cool down")
        core_simulation_duration = time.time() - self.controller.rjms_real_simulation_start_time
        logger.info("Core simulation duration: {}".format(core_simulation_duration))
        self.controller.rjms_cooldown()
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
        self.rjms_round(False)

    def rjms_round(self, reset_rjms_wake_up_period=True):
        round_time, rjms_events = self.controller.rjms_round(self.bs.time())
        self.bs.consume_time(round_time)
        if rjms_events:
            logger.debug('RJMS_EVENTS')
            # Reset backoff
            self.rjms_wake_up_period = RJMS_WAKE_UP_PERIOD_MIN
            if 'jobs_to_execute' in rjms_events:
                self.bs.execute_jobs(rjms_events['jobs_to_execute'])
            else:
                logger.error('TODO process unsupported events: '.format(rjms_events))
                exit()
        #        
        # Add call me latter with backoff time
        #
        if reset_rjms_wake_up_period:
             self.rjms_wake_up_period = RJMS_WAKE_UP_PERIOD_MIN

        next_wake_up = self.bs.time() + self.controller.rjms_wake_up_period     
        logger.debug('RJMS_WAKE_UP_PERIOD: {}'.format(self.controller.rjms_wake_up_period))
        print('WHAT {} {} {} {}'.format( self.bs.time(), self.controller.rjms_wake_up_period,
                                         self.bs.time() + self.controller.rjms_wake_up_period,
                                         self.previous_wake_up))

        # Call me later if not other call me later has been sent
        if self.bs.time() >=  self.previous_wake_up:
            print('New wake_up')
            self.bs.wake_me_up_at(next_wake_up)
            self.previous_wake_up = next_wake_up
        
        # Update Backoff
        if  self.controller.rjms_wake_up_period < RJMS_WAKE_UP_PERIOD_MAX:
            self.controller.rjms_wake_up_period *= RJMS_WAKE_UP_PERIOD_COEF
            if self.controller.rjms_wake_up_period > RJMS_WAKE_UP_PERIOD_MAX:
                self.controller.rjms_wake_up_period = RJMS_WAKE_UP_PERIOD_MAX

        
        #self.bs.wake_me_up_at(self.bs.time() + RJMS_WAKE_UP_PERIOD)
                
class FakeBatsim(object):
    
    def __init__(self, batsky_scheduler, workload_file):
        self.batsky_sched = batsky_scheduler
        self.batsky_sched.bs = self

        self.jobs = dict()
        
        self._current_time = 0
        self.nb_jobs_submitted = 0
        self.nb_jobs_completed = 0
        self.nb_jobs_toExecute = 0

        self.running_simulation = False

        self.workload = None
        if workload_file:
            with open(workload_file) as json_file:
                self.workload = json.load(json_file)
            self._fake_events = self.events_from_workload(self.workload)
        else:
            self._fake_events = SortedDict({
            0.0: [{'timestamp': 0.0, 'type': 'SIMULATION_BEGINS', 'data': {}}],
                5.0: [{'timestamp': 5.0, 'type': 'JOB_SUBMITTED', 'data':
                       {'job_id': 'w0!1',
                        'job': {'id':'w0!1', 'subtime': 5.0, 'res': 1, 'walltime': 12,
                                'profile': {'type': 'delay', 'delay': 10}}
                       }}],
                20.0: [{'timestamp': 20.0, 'type': 'SIMULATION_ENDS', 'data': {}}] 
            })

        #0.0: [{'type': '', 'data': {}}],
        
        self._read_bat_msg()
        
        self.batsky_sched.onAfterBatsimInit()

        
    def events_from_workload(self, workload):
        # TODO support mutiple events at same timestamp
        fake_events = SortedDict({0.0: [{'timestamp': 0.0, 'type': 'SIMULATION_BEGINS', 'data': {}}]})
        max_event_time = 0.0
        max_walltime = 0
        for job in workload['jobs']:
            assert 'subtime' in job
            timestamp = job['subtime']
            if timestamp == 0: # just to not have 2 events at 0.0
                timestamp = 1e-06
            profile = workload['profiles'][job['profile']]
            assert profile['type'] == 'delay'
            job_event = {'timestamp': timestamp, 'type': 'JOB_SUBMITTED'}
            job_event['data'] = { 'job_id': str(job['id']),
                                  'job': {'id': str(job['id']), 'subtime': timestamp,
                                          'res': job['res'], 'walltime': timestamp,
                                          'profile': {'type': 'delay', 'delay': profile['delay']}
                                  }}
            self.nb_jobs_toExecute += 1

            assert  timestamp not in fake_events

            fake_events.update({timestamp: [job_event]})
            
            if timestamp > max_event_time:
                max_event_time = timestamp
            if job['walltime'] > max_walltime:
                max_walltime = job['walltime'] 
                
        # Simulation finished when all jobs are executed
        #simulation_end_time = max_event_time + max_walltime + 50
        #fake_events.update({simulation_end_time: [{'timestamp': simulation_end_time,
        #                                           'type': 'SIMULATION_ENDS', 'data': {}}]})
        return fake_events

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
        # Generate the events of completion 
    
        for job in jobs:
            events= []
            completion_time = self.time() + job.profile['delay']
            if completion_time in self._fake_events:
                events = self._fake_events.get(completion_time)
                
            assert job.profile['type'] == 'delay'
            events.append({'timestamp': completion_time, 'type': 'JOB_COMPLETED',
                           'data': {'job_id': job.id}})
            logger.debug('Execute_job: insert completion events for job: {} completion_time: {}'.
                         format(job.id, completion_time))
            
            self._fake_events.update({completion_time: events})

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

                if self.nb_jobs_completed == self.nb_jobs_toExecute:
                    self.batsky_sched.onSimulationEnds()
                
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
    def __init__(self, mode, start_command, stop_command=None, controller_name=None):
        self.mode = mode
        self.start_command = start_command
        self.stop_command = stop_command
        self.controller_name = controller_name
        if not controller_name:
            self.controller_name = socket.gethostname()

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

        self.rjms_real_simulation_start_time = None
        
        self.rjms_wake_up_period = RJMS_WAKE_UP_PERIOD_MIN
        
        self.batskyers = {}

        self.rjms_jobs = {}

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
        
    def map_allocation2nodeset(self, allocation):
        # TODO for use w/ the real batsim
        return allocation
            
    def rjms_warmup(self):
        logger.debug('RJMS Warm Up')
        if self.start_command:
            logger.debug('Launch start command: {}'.format(self.start_command))
            Popen(self.start_command.split())
    
        t0 = time.time()
        while (self.mode=='echo') or (not self.rjms_start_time or
            (time.time() - t0) < RJMS_WARM_UP_DURATION):
            for sock in dict(self.poller.poll()):
                if sock == self.batsky_socket:
                    client_id_b, client_id, message = self.read_basky_socket()
                    if message:
                        requested_time = float(message)
                        #logger.info("Request client_id, time: {} {}".
                        #            format(client_id, requested_time))

                        if not self.rjms_start_time:
                            self.rjms_start_time = requested_time
                        
                        # Force monotonic time
                        if requested_time > self.rjms_simulated_time:
                            self.rjms_simulated_time = requested_time
                        
                        # Echo time during warmup phase
                        rjms_simulated_time_str = '%.6f'%(self.rjms_simulated_time)
                        #logger.info('RJMS Simulated Time {}, Warm up time: {}'.
                        #            format(rjms_simulated_time_str, time.time() - t0))
                        self.send_batsky_socket(client_id_b, rjms_simulated_time_str)
                else:
                    logger.error('Not the expected socket')
        logger.debug('RJMS Warm Up done')

    def rjms_cooldown(self):
        logger.debug('RJMS Cooling down begins')
        if self.stop_command:
             logger.debug('Launch stop command: {}'.format(self.stop_command))
             Popen(self.stop_command.split())
    
        t0 = time.time()
        new_start_time = self.rjms_simulated_time
        while (time.time() - t0) < RJMS_COOL_DOWN_DURATION:
            time.sleep(0.5)
            #print("Cool down: {} {}".format(time.time() - t0, RJMS_COOL_DOWN_DURATION ))
            for sock in dict(self.poller.poll()):
                if sock == self.batsky_socket:
                    client_id_b, client_id, message = self.read_basky_socket()
                    if message:
                        requested_time = float(message)
                        #logger.info("Request client_id, time: {} {}".
                        #            format(client_id, requested_time))

                        delta_t = requested_time - t0
                        new_rjms_simulated_time = delta_t + new_start_time
                        
                        # Force monotonic time
                        if new_rjms_simulated_time > self.rjms_simulated_time:
                            self.rjms_simulated_time = new_rjms_simulated_time
                        
                        # Echo time during warmup phase
                        rjms_simulated_time_str = '%.6f'%(self.rjms_simulated_time)
                        #logger.info('RJMS Simulated Time {}'.format(rjms_simulated_time_str))
                        self.send_batsky_socket(client_id_b, rjms_simulated_time_str)
                else:
                    logger.error('Not the expected socket in COOL DOWN (sim-emulation not finished)')
                    break
        logger.debug('RJMS Cooling down done')

    def rjms_job_submission(self, job):

        rjms_job = RJMSJob(job.id, job)
        self.rjms_jobs[job.id] = rjms_job

        slurm_cmd = 'sbatch -N{} -t {} --output=/tmp/res.txt --wrap "'.format(job.requested_resources,
                                                                              datetime.timedelta(seconds=int(job.requested_time)))

        rjms_base_cmd = 'SLURM_NODELIST=node1 ' 
        rjms_base_cmd = slurm_cmd
        #batsky_job_cmd = '/batsky/batsky/batsky_job.py -l /tmp/batsky-job.log -d '
        batsky_job_cmd = 'batsky-job -l /tmp/batsky-job{}.log -d '.format(job.id.replace('!', '_'))
        #background = '&'
        background = '"&'
        rjms_cmd = rjms_base_cmd + batsky_job_cmd +'-c {} -w \'{}\' {}'.format(self.controller_name,
                                                                               job.id, background)
        #rjms_cmd = 'date'
        logger.debug('Submit: {}'.format(rjms_cmd))
        try:
            retcode = call(rjms_cmd, shell=True)
            if retcode < 0:
                logger.error('Job submission return an error code: {}'.format(retcode))
        except OSError as e:
            logger.error('Job submission failed: {}'.format(e))
            exit(-1)

    def rjms_job_completion(self, job):
        #Signal batsky_job
        #import pdb; pdb.set_trace()
        logger.debug("Job completion, signals batsky_job; job_id: {}".format(job.id))
        rjms_job = self.rjms_jobs[job.id]
        finalize_sock = self.context.socket(zmq.PUSH)
        #import pdb; pdb.set_trace()
        finalize_sock.connect("tcp://{}:{}".format(rjms_job.hostname, rjms_job.port))
        finalize_sock.send_json({'next_state': 'completed'})
        #logger.debug("Signal sent............................")
        finalize_sock.close()
        rjms_job.state = RJMSJob.State.COMPLETED_SUCCESSFULLY
        
    def rjms_round(self, batsim_time):
        rjms_events = {}
        self.rjms_simulated_time = self.rjms_simulated_start_time + batsim_time

        round_time_t0 = time.time()
        
        logger.debug('Batsim time: {} , RJMS Simulated Time: {}'.
                     format(batsim_time, self.rjms_simulated_time))

        while (time.time() - round_time_t0) < 2*(RJMS_PULL_DURATION + RJMS_PULL_INTER_SLEEP):
            for sock in dict(self.poller.poll(int(1000 * RJMS_PULL_DURATION))):
                if sock == self.batsky_socket:
                    client_id_b, client_id, message = self.read_basky_socket()
                    if message:
                        requested_time = float(message)
                        #logger.info('Request client_id, time: {} {}'.
                        #            format(client_id, requested_time))
                        self.send_batsky_socket(client_id_b, '%.6f'%(self.rjms_simulated_time) )
                elif sock == self.jobs_socket:
                    allocation_data = self.jobs_socket.recv_json()
                    job_id = allocation_data['job_id']
                    job = self.rjms_jobs[job_id]
                    job.allocation = allocation_data['nodeset']
                    job.batsim_job.allocation = self.map_allocation2nodeset(allocation_data['nodeset'])
                    job.port = allocation_data['port']
                    job.hostname = allocation_data['hostname']
                    logger.info('RJMS is launching the job: {}'.format(job_id))
                    
                    #TODO loop again or test is there is another waiting job to execute

                    if 'jobs_to_execute' not in rjms_events:
                        rjms_events['jobs_to_execute'] = []
     
                    rjms_events['jobs_to_execute'].append(job.batsim_job)

                    round_time = time.time() - round_time_t0
                    logger.debug('Controller Round time: {}'.format(round_time))
                else:
                    # Will never reach this place
                    logger.error('Unexpect socket in rjms_round !')
                    
            time.sleep(RJMS_PULL_INTER_SLEEP)
            
        round_time = time.time() - round_time_t0
        logger.debug('Controller Round time: {}'.format(round_time))

        #import pdb; pdb.set_trace()
        return round_time, rjms_events
            
@click.command()
@click.option('-d', '--debug', is_flag=True, help='Debug flag.')
@click.option('-l', '--logfile', type=click.STRING, help='Specify log file.')
@click.option('-s', '--submission-hostname', type=click.STRING, help='Specify the host to execute submission commande (TODO).')
@click.option('-b', '--batsim-socket', type=click.STRING,
              help='Batsim socket endpoint to use.', default='tcp://*:28000')
@click.option('-r', '--rjms', type=click.STRING, default='slurm',
              help= 'Select resources and jobs management system.')  
@click.option('-S', '--internal-delay-simulator', is_flag=True,
              help="Use simple internal simulator which support only the delay execution job's profile") 
@click.option('-m', '--mode', type=click.STRING, help ='Time mode: echo or None')
@click.option('-w', '--workload-file', type=click.STRING, help='Workload file name')
@click.option('-a', '--start-command',  type=click.STRING, help='command launch at warm up')
@click.option('-e', '--stop-command',  type=click.STRING, help='command launch at cooling down')

def cli(debug, logfile, submission_hostname, batsim_socket, rjms, internal_delay_simulator, workload_file, mode, start_command, stop_command):

    if submission_hostname:
        logger.error('submission_hostname option NOT YET IMPLEMENTED')
        exit(-1)

    if rjms != 'slurm':
        logger.error('Up to now, only slurm is supported')
        exit(-1)

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

    if internal_delay_simulator:
        controller = Controller(mode, start_command, stop_command)
        batsky_scheduler = BatskySched(controller)
        fake_batsim = FakeBatsim(batsky_scheduler, workload_file)        
        fake_batsim.start()
    else:
        logger.error('Batsim NOT YET SUPPORTED')
        

if __name__ == '__main__':
    cli()
