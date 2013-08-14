#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""
DGA: Implementation of the Distributed Greedy Algorithm for channel assignment

DGA has been originally proposed in:

B.-J. Ko, V. Misra, J. Padhye, and D. Rubenstein, Distributed channel
assignment in multi-radio 802.11 mesh networks, in Wireless Communications and
Networking Conference (WCNC), 2007.

This implementation and an evaluation on the DES-Testbed (www.des-testbed.net)
has been documented in:

Juraschek, F., S. Seif, and M. Günes, Distributed Channel Assignment in 
Large-Scale Wireless Mesh Networks: A Performance Analysis, IEEE International
Conference on Communications (ICC), Budapest, Hungary, June, 2013. 


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


import random
import dmp
import os
import logger
import subprocess
import sys
import time
import ConfigParser

# insert path to des_chan framework
p = subprocess.Popen('logname', stdout=subprocess.PIPE,stderr=subprocess.PIPE)
logname, errors = p.communicate()
sys.path.insert(0, '/home/' + logname.strip())

from des_chan.topology import etx 
from des_chan import util 
from des_chan.interference import co

from twisted.internet import reactor

# GLOBALS
# own hostname
hostname = os.uname()[1].split(".")[0] 

# LOGGING
DEBUG = False
log = logger.Logger(DEBUG)

# TIMEOUT CONFIG
ETX_TIMEOUT = 90
INTERFACE_SETUP_TIMEOUT = 10

# this is not the entire spectrum, merely the channels that are supported in the testbed
channel_frequencies = {1:2412, 2:2417, 3:2422, 4:2427, 5:2432, 6:2437, 7:2442, 8:2447, 9:2452, 10:2457, 11:2462, 12:2467, 13:2472, 14:2484,
                        36:5180, 40:5200, 44:5220, 48:5240, 52:5260, 56:5280, 60:5300, 64:5320, 
                        100:5500, 104:5520,108:5540, 112:5560, 116:5580, 120:5600, 124:5620, 128:5640, 132:5660, 136:5680, 140:5700}
class DGA:

    def __init__(self, default_interface, default_channel, interfaces_2ghz, interfaces_5ghz, channels_2ghz, channels_5ghz, delta_2ghz, delta_5ghz, interferenceModel, port):
        """Constructor. 
        default_interface::string - name of the interface that shall be used as default interface. 
        default_channel::int - channel that the default_interface shall be tuned to.
        interfaces_2ghz::[string] - interfaces that shall be assigned by the algorithm in the 2.4 GHz band (without the default interface). 
        interfaces_5ghz::[string] - interfaces that shall be assigned by the algorithm in the 5 GHz band (without the default interface). 
        channels_2ghz::[int] - channels in the 2.4 GHz band the algorithm is allowed to choose from. 
        channels_5ghz::[int] - channels in the 5 GHz band the algorithm is allowed to choose from. 
        delta_2ghz::int - tuning parameter of the cost function applyied to 2.4 GHz band.
        delta_5ghz::int - tuning parameter of the cost function applyied to 5 GHz band.
        interferenceModel::function - name of the interference model (function of this module).
        port::int - port for communication.
        
        """
        self.default_interface = default_interface
        self.default_channel = default_channel
        self.interfaces_2ghz = interfaces_2ghz
        self.interfaces_5ghz = interfaces_5ghz
        self.channels_2ghz = set(channels_2ghz)
        self.channels_5ghz = set(channels_5ghz)
        self.delta_2ghz = delta_2ghz
        self.delta_5ghz = delta_5ghz
        self.assignment = dict() # { interface:channel }
        self.interferenceSet = dict() # {node: [channel]}
        self.interferenceModel = interferenceModel
        self.port = port
        self.neighbours = set() #1 hop communication partners
        self.hostname = hostname
        
    
    def applyChannelToInterface(self, interface, channel):
        """Tunes the given interface to the given channel.

        """
        if not util.is_interface_up(interface):
                util.set_up_interface(interface)
        util.set_channel(interface, channel)
    
    
    def start(self):
        """Sets up the environment of the instance.

        """
        try:
            self.channels_2ghz.remove(self.default_channel)
            self.channels_5ghz.remove(self.default_channel)
        except:
            pass
        
        log.channels("2.4GHz", self.channels_2ghz)
        log.channels("5GHz", self.channels_5ghz)
            
        # choose random channels for remaining interfaces but do not set those interfaces up yet
        channels_to_assign = random.sample(self.channels_2ghz, len(self.interfaces_2ghz))
        for interface in self.interfaces_2ghz:
            self.assignment[interface] = channels_to_assign.pop()
            
        channels_to_assign = random.sample(self.channels_5ghz, len(self.interfaces_5ghz))
        for interface in self.interfaces_5ghz:
            self.assignment[interface] = channels_to_assign.pop()
            self.applyChannelToInterface(interface, self.assignment[interface])
        
        try: #fugly hack for incomplete /etc/hostfiles
            self.applyChannelToInterface(self.default_interface, self.default_channel)
        except:
            util.shut_down_interface(self.default_interface)
            log.error("INVALID /etc/hosts")
            sys.exit(2)
        
        util.busy_wait(INTERFACE_SETUP_TIMEOUT)
        
        log.assignment(self.assignment)
        reactor.callWhenRunning(self.getNeighbourhood)
        reactor.run()
        
        
    def getNeighbourhood(self):
        """Retrieves the network's topology from the ETX daemon.

        """
        subprocess.call("/etc/init.d/etxd restart", shell=True)
        
        util.busy_wait(ETX_TIMEOUT)
        
        deferred = etx.get_network_graph()
        deferred.addCallback(self.prepareInterferenceSet)
        deferred.addErrback(self.onError)

        
    def prepareInterferenceSet(self, network_graph):
        """Sets up all the internal topology related data structures.

        """
        # direct neighbours
        self.neighbours.update(network_graph.get_neighbors(hostname))
        
        # apply interference model to the topology
        interferers = self.interferenceModel(network_graph)
        
        # remove the node itself
        if hostname in interferers:
            interferers.remove(hostname)
        
        # fill the interference set
        for interferer in interferers:
            self.interferenceSet[interferer] = set()
        
        #log.neighbours(interferers)
        log.neighbours(network_graph.get_neighbors(hostname))
        self.startProtocol()
        

    def onError(self, error=None):
        """Simple error handling to print the trace.

        """
        print "error: %s" % (error.getErrorMessage())
        error.printTraceback()
        reactor.stop()
        
    def startProtocol(self):
        """Starts the message protocol for DGA.

        """
        # give control to the protocol
        log.interferenceSet(self.interferenceSet)
        self.protocol = dmp.DMP(self, self.port)
        self.protocol.start()    
        
    def findNewAssignment(self):
        """Finds a new channel assignment for one interface that leads to 
        highest reduction of interference in the interference set.

        """
        if len(self.interfaces_2ghz) > 0:
            assignment_2 = self._findNewAssignment(self.interfaces_2ghz, self.channels_2ghz)
        else:
            assignment_2 = Request(self, hostname, 'wlanx', 0, 0, -1)
            assignment_2.invalidate()

        ### we can also shuffle the available channels here leading to a higher spectral diversity
        #allowed_chans = list(self.channels_5ghz)
        #random.shuffle(allowed_chans)
        #assignment_5 = self._findNewAssignment(self.interfaces_5ghz, allowed_chans)
        assignment_5 = self._findNewAssignment(self.interfaces_5ghz, self.channels_5ghz)

        if assignment_2.valid:
            
            if assignment_5.valid:
                
                if assignment_2.reduction > assignment_5.reduction:
                    return assignment_2
                else:
                    return assignment_5

            else:
                return assignment_2
                
        else:
            return assignment_5
        
    def removeNode(self,node):
        """Removes a node from the neighbor and interference set.

        """
        del self.interferenceSet[node]
        try:
            self.neighbours.remove(node)
        except:
            pass
        
    def cleanInterferenceSet(self):
        """Cleans incomplete information from the interference set.

        """

        for node in self.interferenceSet.keys():
            if len(self.interferenceSet[node]) == 0:
                self.removeNode(node)
            
    def _findNewAssignment(self, interfaces, allowed_channels):
        """Calculates the new assignment(::Request) that would result in the maximum decrease in interference.
        Only network interfaces in interfaces and channels in allower_channels will be considered. 
        If no further change will do so, an invalid request will be returned.

        """

        # get all channels in interference set, but consinder only allowed ones
        channels_interferenceset = list()
        for channels in self.interferenceSet.itervalues():
            channels_interferenceset.extend(filter(lambda x: x in allowed_channels, channels))
                 
        channels_assigned = set(filter(lambda x: x in allowed_channels, self.assignment.values()))
        
        # calculate the cost function sums for each channel used in the interference set and own channels
        F = dict() # {channel, sum(f)}
        for channel in set(channels_interferenceset).union(channels_assigned): # only calculate the sum once for each channel
            sum = 0

            for other_channel in channels_interferenceset:
                sum += self.f(channel, other_channel)

            F[channel] = sum
            
        # look for the own assignment with maximum cost
        interface_max = interfaces[0]
        channel_max = self.assignment[interface_max]
        cost_max = F[channel_max]
        
        interface_unused_max = None
        channel_unused_max = None
        cost_unused_max = None
        
        for interface in interfaces:
            channel = self.assignment[interface]
            c = F[channel]
            
            if c > cost_max:
                interface_max = interface
                channel_max = channel
                cost_max = c
                
            if channel not in channels_interferenceset:
                if cost_unused_max is None or c > cost_unused_max:
                    interface_unused_max = interface
                    channel_unused_max = channel
                    cost_unused_max = c
                    
        # get the channel with the minimum interference
        # remove channels that we already in use from candidates
        # remove the channels not used by direct neighbours from candidates
        channelsNeighbourhood=set()
        for neighbour in self.neighbours:
            if neighbour in self.interferenceSet:
                channelsNeighbourhood.update(self.interferenceSet[neighbour])
            
        for channel in channels_assigned.union(set(channels_interferenceset) - channelsNeighbourhood):
                del(F[channel])
        
        if len(F) > 0:
        
            channel_min = F.keys()[0]
            cost_min = F[channel_min]
            
            for channel, cost in F.iteritems():
                
                if cost < cost_min:
                    channel_min = channel
                    cost_min = cost
                    
        else: # make the request invalid
            channel_min = channel_max
            cost_min = cost_max + 1
        
        request = Request(self, hostname, interface_max, channel_max, channel_min, cost_max - cost_min)
        
        # no gain -> invalidate the request    
        if cost_max <= cost_min:
            # now check if there is a unassigned interface
            if interface_unused_max is not None:
                request = Request(self, hostname, interface_unused_max, channel_unused_max, channel_min, cost_unused_max - cost_min)
            else:
                request.invalidate()
        
        return request

    def updateInterferenceSet(self, request):
        """Updates the current interference set with the new information. 
        request::Request

        """
        node = request.node
        old_channel = request.channel
        new_channel = request.new_channel
        
        if node in self.interferenceSet:
            assignment = self.interferenceSet[node]
            if old_channel in assignment:
                assignment.remove(old_channel)
        else:
            assignment = list()
            
        assignment.append(new_channel)
        
        self.interferenceSet[node] = assignment

    def f(self, a, b):
        """Returns the costs between two channels according to the interference cost function.
        a::int
        b::int
        delta::int

        """
        if a > 14 or b > 14:
            delta = self.delta_5ghz
        else:
            delta = self.delta_2ghz
            
        f_a = channel_frequencies[a]
        f_b = channel_frequencies[b]
            
        return max(0, delta - abs(f_a - f_b))
            
    def isAssignmentUpToDate(self, assignment):
        """Checks if the given assignment is up to date
        assignment:[Int]

        """
        own_channels = self.assignment.values()
        return set(own_channels) == set(assignment)
    
    def finish(self):
        print "[TERMINATED] [%s]" % (time.strftime("%H:%M:%S"))
        try:
            reactor.stop()
        except:
            pass

        log.info("Assignment is now complete.")
        log.assignment(self.assignment)
        log.interferenceSet(self.interferenceSet)
            

def twoHop(topology):
    """Returns a set of interfering nodes according to the the two-hop interference model.

    """
    oneHop = topology.get_neighbors(hostname)
    interferers = set()
    interferers.update(oneHop) #1hop
    for interferer in oneHop: # 2hop
        interferers.update(topology.get_neighbors(interferer))
    
    return interferers
    
    
def threeHopCO(topology):
    """Returns a set of interfering nodes according to the CO-3-hop interference model.

    """
    twohops = twoHop(topology)
    threeHop = set()
    for node in twohops: # 3hop
        threeHop.update(topology.get_neighbors(node))
        
    return filter(lambda v: co.get_interference_by_node(v,hostname) > 0, threeHop)        
 

class Request:
    """Represents a request to change a channel to interface assignment

    """

    def __init__(self, dga, node, interface, old_channel, new_channel, reduction):
        """dga::DGA - instance of the dga algorithm.
        node::string - the name of the node issueing this request.
        interface::string - the interface this request shall be applied to.
        old_channel::int - the current channel of the interface.
        new_channel::int - the new channel of the interface.
        reduction::int - the level of interference reduction caused by this assignment.

        """
        self.dga = dga
        self.node = node
        self.interface = interface
        self.channel = old_channel
        self.new_channel = new_channel
        self.reduction = reduction
        self.valid = True

    def validate(self):
        """Validates this request.

        """
        self.valid = True

    def invalidate(self):
        """Invalidates the request.

        """
        self.valid = False

    def conflicts(self, request):
        """Determines if this Request conflicts with the given request. 
        request::Request
        
        """
        conflicts = False
        
        if self.valid:
        
            if self.dga.f(request.channel, self.channel) > 0:
                conflicts = True
    
            elif self.dga.f(request.channel, self.new_channel) > 0:
                conflicts = True
    
            elif self.dga.f(request.new_channel, self.channel) > 0:
                conflicts = True
    
            elif self.dga.f(request.new_channel, self.new_channel) > 0:
                conflicts = True

        return conflicts


    def wins(self, request):
        """Determines if this request wins against a competing request.
        Returns True if the reduction level of the node of the calling Request is higher.
        If both reduction levels are equals, the decision is based according to the lexicographic ordering of the nodes' names. 
        request::Request
        
        """
        if self.reduction > request.reduction:
            return True
        if self.reduction < request.reduction:
            return False
        if self.reduction == request.reduction:
            return self.node > request.node

    def commit(self):
        """Commits the new channel assignment to own interfaces.
        Afterwards the request will be invalidated.
        
        """
        self.dga.assignment[self.interface] = self.new_channel
        self.dga.applyChannelToInterface(self.interface,self.new_channel)
    

def usage():
    print "dga.py <configfile>"

        
if __name__=="__main__":
    try:
        config = ConfigParser.ConfigParser()
        config.read(sys.argv[1])
        
        port = config.getint("General","port")
        delta_2 = config.getint("General", "delta2")
        delta_5 = config.getint("General", "delta5")
        
        default_interface = config.get("Default Channel","interface")
        default_channel = config.getint("Default Channel", "channel")

        
        interfaces_2 = config.get("2GHz Band","interfaces").split(",")
        try:
            channels_2 = map(int,config.get("2GHz Band","channels").split(","))
        except ValueError:
            interfaces_2 = []
            channels_2 = []

        interfaces_5 = config.get("5GHz Band","interfaces").split(",")
        try:
            channels_5 = map(int,config.get("5GHz Band","channels").split(","))
        except ValueError:
            interfaces_5 = []
            channels_5 = []
        
        
        # TODO: find a more elegant way to map config-strings to module functions
        interferencemodelStr = config.get("General","interferencemodel")
        interferencemodel = None
        if interferencemodelStr == "2hop":
            interferencemodel = twoHop
            
        if interferencemodelStr == "3hopco":
            interferencemodel = threeHopCO
        
        dga = DGA(default_interface, default_channel, interfaces_2, interfaces_5, channels_2, channels_5, delta_2, delta_5, interferencemodel, port)
        dga.start()
        
    except Exception as e:
        usage()
        print e
        sys.exit(1)
