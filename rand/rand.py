#!/usr/bin/python
"""
RAND: A simple, randomized channel assignment strategy based on DES-Chan, a
framework for channel assignment algorithms for testbeds. One wireless 
interface is operated on a common global channel, while the remaining interfaces
are set to random channels of the 5GHz WLAN frequency band.

Authors:    Simon Seif <seif.simon@googlemail.com>,
            Felix Juraschek <fjuraschek@gmail.com>,
            Matthias Philipp <mphilipp@inf.fu-berlin.de>,

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


import os
import sys
import random
import subprocess

# insert path to des_chan framework
p = subprocess.Popen('logname', stdout=subprocess.PIPE,stderr=subprocess.PIPE)
logname, errors = p.communicate()
sys.path.insert(0, '/home/' + logname.strip())

from des_chan import util

def random_assignment():
    # select random channels for wlan1 and wlan2
    b = [36, 44, 48, 52, 60, 64, 100, 108, 112]
    rand_channels = random.sample(b,2)

    # set wlan0 to the default channel 14
    util.set_up_interface("wlan0")
    util.set_channel("wlan0",14,True)

    # set wlan1 and wlan2 to the randomly selected channels
    util.set_up_interface("wlan1")
    util.set_channel("wlan1",rand_channels[0],True)
    util.set_up_interface("wlan2")
    util.set_channel("wlan2",rand_channels[1],True)


if __name__ == "__main__":
    random_assignment()

    