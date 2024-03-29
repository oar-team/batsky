#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import re
import os.path as op


from codecs import open
from setuptools import setup, find_packages


def read(fname):
    ''' Return the file content. '''
    here = op.abspath(op.dirname(__file__))
    with open(op.join(here, fname), 'r', 'utf-8') as fd:
        return fd.read()

readme = read('README.rst')
changelog = read('CHANGES.rst').replace('.. :changelog:', '')

requirements = [
    'pyzmq',
    'pyinotify',
    'click',
    'clustershell'
]

version = ''
version = re.search(r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]',
                    read(op.join('batsky', '__init__.py')),
                    re.MULTILINE).group(1)

if not version:
    raise RuntimeError('Cannot find version information')


setup(
    name='batsky',
    author="Olivier Richard",
    author_email='olivier.richard@imag.fr',
    version=version,
    url='https://github.com/oar-team/batsky',
    packages=find_packages(),
    install_requires=requirements,
    include_package_data=True,
    zip_safe=False,
    description="Framework companion to Batsim which control timeline according to simulation for legacy applications.",
    long_description=readme + '\n\n' + changelog,
    keywords='batsky',
    license='BSD',
    classifiers=[
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: BSD License',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: Implementation :: CPython',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Clustering',
    ],
    entry_points='''
    [console_scripts]
    batsky=batsky.batsky:cli
    batsky-notify=batsky.batsky_notify:cli
    batsky-controller=batsky.batsky_controller:cli
    batsky-job=batsky.batsky_job:cli
    batsky-sim=batsky.batsky_sim:cli
    ''',    
)
