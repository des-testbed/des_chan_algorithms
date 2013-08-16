#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""
MICA: Minimum Interference Channel Assignment

Implementation based on:

    A.P. Subramanian, H. Gupta, and S.R. Das 
    Minimum interference channel assignment in multi-radio wireless mesh networks 
    In Sensor, Mesh and Ad Hoc Communications and Networks, 2007. SECON '07 
    4th Annual IEEE Communications Society Conference on, pages 481-490, June 2007

This module holds the exception class for MICA.

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


class MICAError(Exception):

    def __init__(self, value):
        Exception.__init__(self, value)
        self.value = value

    def __str__(self):
        return str(self.value)


