#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""
MICA: Minimum Interference Channel Assignment

Implementation based on:

    A.P. Subramanian, H. Gupta, and S.R. Das 
    Minimum interference channel assignment in multi-radio wireless mesh networks 
    In Sensor, Mesh and Ad Hoc Communications and Networks, 2007. SECON '07 
    4th Annual IEEE Communications Society Conference on, pages 481-490, June 2007


Authors:    Matthias Philipp <mphilipp@inf.fu-berlin.de>,
            Felix Juraschek <fjuraschek@gmail.com>

Copyright 2008-2013, Freie Universitaet Berlin (FUB). All rights reserved.

These sources were developed at the Freie Universitaet Berlin, 
Computer Systems and Telematics / Distributed, embedded Systems (DES) group 
(http://cst.mi.fu-berlin.de, http://www.des-testbed.net)
-------------------------------------------------------------------------------
This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see http://www.gnu.org/licenses/ .
--------------------------------------------------------------------------------
For further information and questions please use the web site
       http://www.des-testbed.net
       
"""


import netifaces
import sys
#import getopt
import os
import time
import subprocess
from syslog import *
import ConfigParser

from mica import Mica

# insert path to des_chan framework
p = subprocess.Popen('logname', stdout=subprocess.PIPE,stderr=subprocess.PIPE)
logname, errors = p.communicate()
sys.path.insert(0, '/home/' + logname.strip())

from des_chan import util


def prepare_interfaces():
    """Shuts down all wireless interfaces and sets up the default interface
    on the default channel. The ETX daemon is triggered to retrieve the local
    network topology.

    """
    # shutdown all interfaces
    util.shut_down_interfaces()
    # setup default interface on default channel
    util.set_up_interface(default_iface)
    util.set_channel(default_iface, default_channel)
    subprocess.call("/etc/init.d/etxd restart", shell=True)
    for i in range(wait, 0, -1):
        print i
        time.sleep(1)


def main():
    """Initiate and start the MICA algorithm.

    """
    prepare_interfaces()
    #alg = Mica(if_names, channels, port, debug, experiment_id)
    alg = Mica(if_names, channels, port, interferencemodel, debug, experiment_id)
    alg.start()


def usage():
    print "python micad.py <configfile>"


if __name__ == "__main__":
    """Parse the config file and send to background, if started in daemon mode.

    """
    try:
        config = ConfigParser.ConfigParser()
        config.read(sys.argv[1])

        port = config.getint("General","port")
        foreground = config.getboolean("General","foreground")
        if_names = config.get("General","interfaces").split(",")
        channels = map(int,config.get("General","channels").split(","))
        wait = config.getint("General", "wait")
        experiment_id = config.getint("General","experiment_id")
        logfile = config.get("General","logfile")
        debug = config.getboolean("General","debug")
        interferencemodel = config.get("General","interferencemodel")

        default_channel = config.getint("Default Channel","channel")
        default_iface = config.get("Default Channel","interface")
        
        # prepare logger
        openlog("mica", LOG_PID|LOG_PERROR, LOG_DAEMON)

        if debug:
            syslog(LOG_DEBUG, "PORT:          %s" % port)
            syslog(LOG_DEBUG, "CHANNELS:      %s" % channels)
            syslog(LOG_DEBUG, "DEBUG:         %s" % debug)
            syslog(LOG_DEBUG, "FOREGROUND:    %s" % foreground)
            syslog(LOG_DEBUG, "EXPERIMENT_ID: %s" % experiment_id)
            syslog(LOG_DEBUG, "WAIT:          %s" % wait)
            syslog(LOG_DEBUG, "LOGFILE:       %s" % logfile)
            syslog(LOG_DEBUG, "Default channel: %s" % default_channel)
            syslog(LOG_DEBUG, "Default iface: %s" % default_iface)

        for if_name in if_names:
            # check if interface is valid
            if if_name not in netifaces.interfaces():
                syslog(LOG_WARNING, "Warning: Interface %s does not exist, ignoring it." % if_name)
                if_names.remove(if_name)

        if len(if_names) < 1:
            syslog(LOG_ERR, "Error: No valid network interfaces specified, exiting.")
            sys.exit(1)

        if not foreground:
            # do the UNIX double-fork magic, see Stevens' "Advanced 
            # Programming in the UNIX Environment" for details (ISBN 0201563177)
            try: 
                pid = os.fork() 
                if pid > 0:
                    # exit first parent
                    sys.exit(0) 
            except OSError, e: 
                print >>sys.stderr, "fork #1 failed: %d (%s)" % (e.errno, e.strerror) 
                sys.exit(1)

            # decouple from parent environment
            os.chdir("/") 
            os.setsid() 
            os.umask(0) 

            # do second fork
            try: 
                pid = os.fork() 
                if pid > 0:
                    # exit from second parent, save eventual PID before
                    pidfile = open("/var/run/micad.pid", "w")
                    pidfile.write("%d" % pid)
                    pidfile.close()
                    sys.exit(0) 
            except OSError, e: 
                print >>sys.stderr, "fork #2 failed: %d (%s)" % (e.errno, e.strerror) 
                sys.exit(1) 

            # Redirect standard file descriptors.
            si = file('/dev/null', 'r')
            so = file(LOGFILE, 'a+')
            se = file(LOGFILE, 'a+', 0)
            os.dup2(si.fileno(), sys.stdin.fileno())
            os.dup2(so.fileno(), sys.stdout.fileno())
            os.dup2(se.fileno(), sys.stderr.fileno())

    except Exception as e:
        usage()
        print e
        sys.exit(1)

    # start the daemon main loop
    main() 

