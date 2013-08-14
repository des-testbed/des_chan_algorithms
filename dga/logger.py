#!/usr/bin/python
"""
DGA: Implementation of the Distributed Greedy Algorithm for channel assignment

Custom logger class for different message classes and channel assignment
specific data structures. 


Authors:    Simon Seif <seif.simon@googlemail.com>,
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


import time
import sys


class Logger:
	
	def __init__(self,debugging=False):
		self.msgCount=0
		self.debugging=debugging
		
	def message(self):
		""" Log a message.

		"""
		self.msgCount+=1
		print "[MESSAGE] [%s] %i" % (time.strftime("%H:%M:%S"), self.msgCount)
		sys.stdout.flush()
		

	def debug(self,msg):
		""" Log  debug message.

		"""
		if self.debugging:
			print "[DEBUG] [%s] %s" % (time.strftime("%H:%M:%S"), msg)
			sys.stdout.flush()
		
		
	def error(self,msg):
		""" Log error message.

		"""
		print "[ERROR] [%s] %s" % (time.strftime("%H:%M:%S"), msg)
		sys.stdout.flush()
		
		
	def warn(self,msg):
		""" Log warning.

		"""
		print "[WARN ] [%s] %s" % (time.strftime("%H:%M:%S"),msg)
		sys.stdout.flush()
		
		
	def info(self,msg):
		""" Log info message.

		"""
		print "[INFO ] [%s] %s" % (time.strftime("%H:%M:%S"),msg)
		sys.stdout.flush()
		
		
	def neighbours(self,neighbours):
		""" Log neighbor list.

		"""
		print "[NEIGHBOURS] "+repr(neighbours)[5:-2].replace("'","")
		sys.stdout.flush()
			
		
	def assignment(self,assignment):
		""" Log current channel assignment.

		"""
		line = ""
		for interface,channel in assignment.items():
			line+= interface+":"+repr(channel)+","
		
		line = line[:-1]
		print "[ASSIGNMENT] "+line
		sys.stdout.flush()

		
	def interferenceSet(self,interferenceSet):
		""" Log interference set.

		"""
		line =""
		for node,channels in interferenceSet.items():
			line += node+":"
			for channel in channels:
				line+=repr(channel)+","
			line = line[:-1]
			line+=";"
		line=line[:-1]
		
		nodecount = len(interferenceSet)
				
		print "[INTERFERENCESET] "+line+" #"+repr(nodecount)
		sys.stdout.flush()

			
	def channels(self,band,channels):
		""" Log available channels on the given band.

		"""
		print "[CHANNELS "+band+"] "+repr(channels)[5:-2]
		sys.stdout.flush()

