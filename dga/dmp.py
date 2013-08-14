#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""
DGA: Implementation of the Distributed Greedy Algorithm for channel assignment

The DMP class handles the control flow after the initialization of DGA. 


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


import dga
from dga import hostname
from twisted.internet import protocol, reactor
from twisted.protocols import basic
from logger import Logger
import random
import socket
import sys
import re
import os
import subprocess

# insert path to des_chan framework
p = subprocess.Popen('logname', stdout=subprocess.PIPE,stderr=subprocess.PIPE)
logname, errors = p.communicate()
sys.path.insert(0, '/home/' + logname.strip())

from des_chan import util


### CONSTANTS

# LOGGING
DEBUG = True
log = Logger(DEBUG)

# STATES
STATE_MOVING = 1
STATE_STALLED = 0

# MESSAGE HEADERS
MESSAGE_REQUEST = "REQUEST"
MESSAGE_ABORT = "ABORT"
MESSAGE_UPDATE = "UPDATE"
MESSAGE_ACCEPT = "ACCEPT"
MESSAGE_REJECT = "REJECT"
MESSAGE_QUERY = "QUERY"

# OTHER MESSAGE RELATED STUFF
DELIMITER = ";"

# TIMEOUT
STALLED_TIMEOUT = 15 # time between retrieving query and getting either abort or update
MOVING_TIMEOUT = 15 # timeout between sending request and getting accept/reject
GRACE_TIMEOUT = 5*60 # time between last "action" (except query) and shutdown
RETRY_DELAY = 2 # delay between two connection retries
MAX_RETRIES = 10 # max number of retries for each conncection
QUERY_TIMEOUT = 40 # max time allowed to query
CONNECTION_TIMEOUT = 5 # general connection timeout for any outgoing TCP connection

# time the protocol shall wait before issueing the own request
STALL_MOVE_TIMEOUT_LOWER_BOUND = 0
STALL_MOVE_TIMEOUT_UPPER_BOUND = 4
LAMBDA = 0.2 # lambda for the exponential distribution


### MESSAGE PROCESSING

def createAssignmentString(assignment):
    """Creates a textual representation of a list.

    """
    return repr(assignment)[1:-1].replace(" ","")

    
def parseAssignmentString(line):
    """Parses a textual representation of a list back to an integer array.

    """
    try:
        return map(lambda x:int(x),line.split(","))
    except:
        log.error("cannot parse assignment string:"+line)
        return list()


def parseRequest(line):
    """Parses a request message.
    Returns a quadruple containing old_channel,new_channel,reduction,assignment.
    
    """
    tokens = line.split(DELIMITER)
    old_channel = int(tokens[1])
    new_channel = int(tokens[2])
    reduction = int(tokens[3])
    assignment = parseAssignmentString(tokens[4])
    
    return old_channel, new_channel, reduction, assignment


def parseQuery(line):
    """Parses a query message. The assignment piggy bakced in the message is returned.

    """
    return parseReject(line) # both message formats are the same


def parseReject(line):
    """Parses a reject message. The assignment piggy backed in the message is returned.

    """
    tokens = line.split(DELIMITER)
    return parseAssignmentString(tokens[1])


def createRequest(request, assignment):
    """Creates a request message.
    Format: <REQUEST>;old_channel;new_channel;reduction;c1,...,cn
    
    """
    line = MESSAGE_REQUEST
    line += DELIMITER
    line += repr(request.channel)
    line += DELIMITER
    line += repr(request.new_channel)
    line += DELIMITER
    line += repr(request.reduction)
    line += DELIMITER
    line += createAssignmentString(assignment)
        
    return line


def createQuery(assignment):
    """Creates a query message piggy backing an assignment.
    Format: <Query>;c1,...,cn
    
    """
    assignmentString = createAssignmentString(assignment)
    
    return MESSAGE_QUERY + DELIMITER + assignmentString


def createReject(assignment):
    """Creates a reject message piggy backing an assignment.
    Format: <Reject>;c1,...,cn
    
    """
    assignmentString = createAssignmentString(assignment)
        
    return MESSAGE_REJECT + DELIMITER + assignmentString


def createAbort():
    """Creates an aboort message.

    """
    return MESSAGE_ABORT


def createAccept():
    """Creates an accept message.

    """
    return MESSAGE_ACCEPT


def createUpdate():
    """Creates an update message.

    """
    return MESSAGE_UPDATE


### STALLED STATE

class StalledFactory(protocol.Factory):
    """Factory for the Stalled Protocol.
    Handels incoming foreign requests.
    
    """ 
    
    def __init__(self, dmp):
        self.dmp = dmp
        self.protocol = Stalled
    
        
    def notifyRequest(self, protocol, request, assignment):
        """Callback for the protocol instances.
        Will drop the latter of two concurrent requests.
        Determines if the request can be approved or not.
        
        """
        self.dmp.cancelGraceTimeOut()
        if self.dmp.state != STATE_STALLED:
            log.warn("Incoming request from " + protocol.node + ", but I am moving.")
            # remember the request so that the abort message will not cause confusion
            self.dmp.foreignRequests[protocol.node] = request
            protocol.sendReject()

        else:
            self.dmp.foreignRequests[protocol.node] = request
            if self.dmp.dga.isAssignmentUpToDate(assignment): # it's valid
                
                # possible that we've lost a node...but now got req from it, so put it again in our interference set
                if protocol.node not in self.dmp.dga.interferenceSet:
                    log.error("Got request from node that is not in interference set..."+repr(protocol.node))
                    self.dmp.dga.interferenceSet[protocol.node]=list()
                    reactor.callLater(1,self.dmp.move) # in any case (apply/abort) something changed -> check for new possible assignment        
                    
                if self.dmp.request is not None and self.dmp.request.conflicts(request): # we've got something on our own
                        
                    if self.dmp.request.wins(request): # and i win
                        log.debug("Incoming request from node " + protocol.node + " is losing.")
                        protocol.sendReject()
                            
                    else: # but i loose
                        log.debug("Incoming request from node " + protocol.node + " is winning.")
                        protocol.sendAccept()
                        self.dmp.request.invalidate()
                        
                else: # not conflicting and up to date
                    log.debug("Incoming request from node " + protocol.node + " is not conflicting.")
                    protocol.sendAccept()
                    
            else: # out of date
                log.warn("Incoming request from node " + protocol.node + " is out of date.")
                protocol.sendReject()
            
        
    def notifyUpdate(self,client):
        """Callback for the protocol instances.
        Will commit the foreign request.
        
        """
        request = self.dmp.foreignRequests.get(client.node)
        if request is not None:
            log.info("Appyling update from " + client.node)
            self.dmp.dga.updateInterferenceSet(request)
            del self.dmp.foreignRequests[client.node]
            if self.dmp.request is not None:
                self.dmp.request.invalidate()
            if len(self.dmp.foreignRequests)==0:    
                reactor.callLater(0,self.dmp.stall)
            
        else:
            log.error("Got Update for unknown request! From:"+(client.node))
        
        
    def notifyAbort(self,client):
        """Callback for the protocol instances.
        Will discard the foreign request.
        
        """
        request = self.dmp.foreignRequests.get(client.node)
        
        if request is not None:
            log.info("Aborting update from " + client.node)
            del self.dmp.foreignRequests[client.node]
            
            if self.dmp.request is not None:
                self.dmp.request.validate()
            if len(self.dmp.foreignRequests)==0:    
                reactor.callLater(0,self.dmp.stall)
            
        else:
            log.error("Got Abort for unknown request! From:"+(client.node))
        
        
class Stalled(basic.LineReceiver):
    """Protocol that is enabled during Stalled State.
    Events that do not need further interaction with this protocol cause a disconnect automatically.
    
    """
    
    def __init__(self):
        self.node = None
        self.timeOutActive = False
        reactor.callLater(STALLED_TIMEOUT, self.onTimeOut)
    

    def onTimeOut(self):
        """Callback for timeouts.

        """
        if self.timeOutActive:
            if self.node in self.factory.dmp.foreignRequests:
                log.warn("Foreign Request " + self.node + " timed out.")
                self.factory.notifyAbort(self)
                self.loseConnection()
        

    def lineReceived(self, line):
        """Handle incoming message.

        """
        self.node = socket.gethostbyaddr(self.transport.getPeer().host)[0]
        self.node = re.match("(.*)(-ch)",self.node).group(1)
        
        if line.startswith(MESSAGE_REQUEST):
            self.timeOutActive = True
            old_channel, new_channel, reduction, assignment = parseRequest(line)
            request = dga.Request(self.factory.dmp.dga, self.node, None, old_channel, new_channel, reduction)
            self.factory.notifyRequest(self, request, assignment)
            
        elif line.startswith(MESSAGE_ABORT):
            self.timeOutActive = False
            self.factory.notifyAbort(self)
            self.loseConnection()
            
        elif line.startswith(MESSAGE_UPDATE):
            self.timeOutActive = False
            self.factory.notifyUpdate(self)
            self.loseConnection()
            
        elif line.startswith(MESSAGE_QUERY):
            assignment = parseQuery(line)
            self.factory.dmp.dga.interferenceSet[self.node] = assignment
            
            asnwer = createQuery(self.factory.dmp.dga.assignment.values())
            self.sendLine(asnwer)
            
        else: # only allow above messages
            log.error("Received unexpected message from "+repr(self.node)+":"+line)
            self.loseConnection()
        
        
    def sendReject(self):
        """Sends a reject message to the destination.

        """
        log.message()
        msg = createReject(self.factory.dmp.dga.assignment.values())
        self.sendLine(msg)
        
        
    def sendAccept(self):
        """Sends an accept message.

        """
        log.message()
        msg = createAccept()
        self.sendLine(msg)
        
    def loseConnection(self):
        """ Shutdown connection.

        """
        self.transport.loseConnection()
        

### MOVING STATE 

class MovingFactory(protocol.ClientFactory):
    """Factory for the Moving Protocol.
    Keeps track of approval/disproval of an issued request.

    """
    
    def __init__(self, dmp, request):
        self.dmp = dmp
        self.issued_requests = set() # list of issued_requests (protocol objects) 
        self.answerCount = 0
        self.request = request
        self.protocol = Moving
        self.react_to_connection_failed = True
        self.gotRejected = False
        self.failingNodes=dict()
        
    def clientConnectionFailed(self, connector, reason):
        """Called when a connection has failed to connect.
        Will remove the unresponsive node from the interference set and abort the issued request.
        
        """
        if self.react_to_connection_failed:
            node = util.resolve_node_name(connector.getDestination().host)
            
            if node in self.failingNodes:
                self.failingNodes[node] = self.failingNodes[node] + 1
                
                if self.failingNodes[node] > MAX_RETRIES: # last chance over
                    log.error("[MOVING] Removing " + node+" from Interference set")
                    try:
                        self.dmp.dga.removeNode(node)
                    except:
                        log.error("moving:clientConnectionFailed: Wanted to remove "+node+" from interference set, but not found")
                        print self.dmp.foreignRequests.items()
                    log.interferenceSet(self.dmp.dga.interferenceSet)
                    self.answerCount += 1 # fugly hack
                    self.notifyReject()
                    return
                            
            else:
                self.failingNodes[node] = 1
                
            reactor.callLater(RETRY_DELAY,connector.connect)
            
            
    def clientConnectionLost(self, connector, reason):
        """Called when an established connection is lost.
        This is intended behaviour if the remote node calls transport.loseConnection()

        """
        pass
        

    def notifyReject(self):
        """Callback for protocol.
        Will abort the current request.
        
        """
        self.gotRejected = True
        self.answerCount = self.answerCount + 1
        self.react_to_connection_failed = False
        if self.answerCount >= len(self.issued_requests):
            self.abort()
            
        
    def notifyAccept(self):
        """Callback for protocol.

        """
        self.answerCount = self.answerCount + 1
        if self.answerCount >= len(self.issued_requests):
            self.react_to_connection_failed = False
            if self.gotRejected: # this is necessary due to late arrival of accept messages (after a reject message).
                self.abort()
            else:
                self.update()
            
    
    def update(self):
        """Sends update messages to all nodes in the interference set.
        Causes an immediate state transistion to STALLED.
        
        """
        for request in self.issued_requests:
                request.sendUpdate()
        self.issued_requests = set()
        self.request.commit()
        self.request.invalidate() # otherwise we are stuck
        log.debug("Request got accepted =)")
        reactor.callLater(0, self.dmp.stall)
        
        
    def abort(self):
        """Sends abort messages to all nodes in the interference set.
        Causses an immediuate state transistion to STALLED.
        
        """
        for request in self.issued_requests:
                request.sendAbort()
        self.issued_requests = set()
        self.request.invalidate() #otherwise this request will be retried over and over again
        log.debug("Own request got rejected =(")
        reactor.callLater(0, self.dmp.stall)

        
    def notifyTimedOut(self, node):
        """Callback for the protocols.
        A timeout is treated like a reject.
        
        """
        log.warn("[MOVING] Removing " + node + " from interference set due to timeout.")
        try:
            self.dmp.dga.removeNode(node)
        except:
            log.error("moving::notifytimedout:: cannot remove"+node+" from interference set")
            print self.dmp.foreignRequests.items()
        self.notifyReject()
    
                        
class Moving(basic.LineReceiver):
    """Protocol that is enabled during Moving State.
    Events that do not need further interaction with this protocol cause a disconnect automatically.
    
    """
    
    def __init__(self):
        self.node = None
        self.timeOutActive = True
        
    
    def connectionMade(self):
        """Callback for the reactor. Sends the line
        
        """
        reactor.callLater(MOVING_TIMEOUT, self.timedOut)
        self.factory.issued_requests.add(self)
        self.node = socket.gethostbyaddr(self.transport.getPeer().host)[0]
        self.node = re.match("(.*)(-ch)",self.node).group(1)
        self.sendRequest(self.factory.request)
    

    def timedOut(self):
        """Callback for timeout.

        """
        if self.timeOutActive:
            self.factory.notifyTimedOut(self.node)
    

    def lineReceived(self, line):
        """Callback for the reactor. Will be called, when a complete line (response to our initial message) is received.

        """
        self.timeOutActive = False
        if line.startswith(MESSAGE_ACCEPT):
            self.factory.notifyAccept()
            
        elif line.startswith(MESSAGE_REJECT):
            assignment = parseReject(line)
            self.factory.dmp.dga.interferenceSet[self.node] = assignment # in case due to bad info -> update the rejecter's assignment
            self.factory.notifyReject()
            
        else: # only allow above two messages right now
            log.error("Got unexpected line from node: " + self.node + " " + line)
            self.loseConnection()
            
    
    def sendRequest(self, request):
        """Sends a request message.

        """
        # node can be lost in meantime, so requery for assignment
        log.message()
        try:
            assignment = self.factory.dmp.dga.interferenceSet[self.node]
        except:
            assignment = [0,0]
        msg = createRequest(request, assignment)
        self.sendLine(msg)
         

    def sendUpdate(self):
        """Sends an update message.

        """
        log.message()
        msg = createUpdate()
        self.sendLine(msg)
        

    def sendAbort(self):
        """Sends an abort message.

        """
        log.message()
        msg = createAbort()
        self.sendLine(msg)
        

    def loseConnection(self):
        self.timeOutActive = False
        self.transport.loseConnection()
    

### QUERYING STATE

class QueryingFactory(protocol.ClientFactory):
    """Factory for the Querying Protocol.
    Keeps track of unresponsive nodes and creating a usable interference set.
    
    """
    
    def __init__(self, dmp):
        self.protocol = Querying
        self.dmp = dmp
        self.failingNodes = dict()
        reactor.callLater(QUERY_TIMEOUT,self.barrierStallCallback)
        
    def clientConnectionFailed(self, connector, reason):
        """Called when a connection has failed to connect.
        If called more than QUERY_MAX_RETRIES from the same node, the node is considered
        down and will be removed from the interference set.
        Otherwise the connection will be retried in QUERYING_RETRY_TIMEOUT.
        
        """
        node = connector.getDestination().host
        node = util.resolve_node_name(node)
        
        if node in self.failingNodes:
            self.failingNodes[node] = self.failingNodes[node] + 1
            
            if self.failingNodes[node] > MAX_RETRIES:
                log.error("Cannot connect to " + repr(node) + ". Removing from interference set!")
                try:
                    self.dmp.dga.removeNode(node)
                except:
                    log.error("Cannot remove "+repr(node)+" from interference set")
                    log.interferenceSet(self.dmp.dga.interferenceSet)
                return
            
        else:
            self.failingNodes[node] = 1
            
        reactor.callLater(RETRY_DELAY,connector.connect)
        
            
    def clientConnectionLost(self, connector, reason):
        """Called when an established connection is lost.
        Expected behaviour if remote host closes transport.

        """
        pass
    
    
    def onTimeout(self, protocol):
        """Called when a connection has been established but timed out.
        If called more than QUERY_MAX_RETRIES from the same node, the node is considered
        down and will be removed from the interference set.
        
        """
        if protocol.node in self.failingNodes:
            self.failingNodes[protocol.node] = self.failingNodes[protocol.node] + 1
            if self.failingNodes[protocol.node] > MAX_RETRIES:
                log.error("Connection to " + repr(protocol.node) + "timed out.")
                try:
                    self.dmp.dga.removeNode(protocol.node)
                except:
                    log.error("querying timeout cannot remove "+repr(protocol.node)+" from interferenceset")
                    log.interferenceSet(self.dmp.dga.interferenceSet)
                return
                
        else:
            self.failingNodes[protocol.node] = 1
            
        protocol.transport.loseConnection()
        reactor.connectTCP(protocol.node,self.dmp.port, self,CONNECTION_TIMEOUT)
        

    def barrierStallCallback(self):
        """Will be called after QUERY_TIMEOUT.
        Cleans up incomplete information in the interference set.
        Causes an immedieate transistion to STALLED.
        
        """
        self.dmp.dga.cleanInterferenceSet()
        log.info("Interferenceset is ready.")
                
        log.interferenceSet(self.dmp.dga.interferenceSet)
        reactor.callLater(0,self.dmp.stall)
            
        
class Querying(basic.LineReceiver):
    
    def __init__(self):
        self.node = None
        self.timeOutActive = True
    
    def connectionMade(self):
        """Callback for the reactor.
        Sends the query message.

        """
        reactor.callLater(QUERY_TIMEOUT, self.timedOut)
        self.node = socket.gethostbyaddr(self.transport.getPeer().host)[0]
        self.node= re.match("(.*)(-ch)",self.node).group(1)
        msg = createQuery(self.factory.dmp.dga.assignment.values())
        self.sendLine(msg)
        
    def lineReceived(self, line):
        """Callback for the reactor. Parses incoming messages (replies to our initial message).

        """
        if line.startswith(MESSAGE_QUERY):
            assignment = parseQuery(line)
            self.factory.dmp.dga.interferenceSet[self.node] = assignment
        
        else:
            log.error("Got unexpected line from " + repr(self.node) + " " + line)
        
        self.timeOutActive = False    
        self.transport.loseConnection()
        
    def timedOut(self):
        """Callback for timeouts.

        """
        if self.timeOutActive:
            self.factory.onTimeout(self)
            self.transport.loseConnection()
                

### MAIN OBJECT

class DMP:
    
    def __init__(self, dga, port):
        self.dga = dga
        self.port = port
        self.request = None
        self.foreignRequests = dict() # {node:request}
        self.graceTimeoutCancelled = False # prevents premature shutdown
        self.moveCalled = False # this prevents "move" being called several times subsequently
        self.finishCalled=False
        self.state = STATE_STALLED
        

    def start(self):
        """Starts the protocol.
        This will give control to the reactor until the algorithm has terminated.

        """
        factory = StalledFactory(self)
        reactor.listenTCP(self.port, factory,50,self.dga.hostname+"-ch"+repr(self.dga.default_channel))
        reactor.callLater(0, self.query)


    def query(self):
        """Asks neighbours for their assignment.

        """
        log.info("Querying neighbours.")
        factory = QueryingFactory(self)
        for node, assignment in self.dga.interferenceSet.iteritems():
            if len(assignment) == 0:
                log.debug("Querying "+node)
                reactor.connectTCP(util.get_node_ip(node, self.dga.default_channel), self.port, factory,CONNECTION_TIMEOUT)
        # if no neighbours found, prevent deadlock        
        if len(self.dga.interferenceSet) == 0:
            reactor.callLater(QUERY_TIMEOUT,self.stall)
        
        
    def move(self):
        """Transfers the current state into moving state.

        """
        if len(self.foreignRequests)==0:
            self.moveCalled=False
            if self.request is None or not self.request.valid:
                
                if self.graceTimeoutCancelled: # apparently grace timeout has been cancelled, go back to stalling
                    self.state = STATE_STALLED
                    reactor.callLater(0, self.stall)
            
            else: # no pending foreign request and our's is valid.
                log.info("MOVING"+repr(self.request))
                if len(self.dga.interferenceSet) ==0:
                    self.dga.finish()
                self.state=STATE_MOVING
                self.sendRequests()
                
        else: # still a pending foreign request, retry later
            reactor.callLater(1, self.move)
            

    def sendRequests(self):
        """Send the request to all neighbors.

        """
        log.info("Requesting neighbours")
        factory = MovingFactory(self, self.request)
        print self.dga.interferenceSet.keys()
        for node in self.dga.interferenceSet.iterkeys():
            reactor.connectTCP(util.get_node_ip(node, self.dga.default_channel), self.port, factory, CONNECTION_TIMEOUT)
            
        if len(self.dga.interferenceSet) == 0:
            reactor.callLater(GRACE_TIMEOUT,self.finish)
            
    
    def finish(self):
        """Begin shutdown.

        """
        self.finishCalled=False
        if not self.graceTimeoutCancelled:
            self.dga.finish()    
        
    def stall(self):
        """Transfers the current state into stalled state.

        """
        log.info("STALLED")
        self.state = STATE_STALLED    
        
        if self.request is None or not self.request.valid: # so we dont overwrite our previously calculated (and still valid) request
            self.createRequest()
            
        if self.request.valid:
            self.graceTimeoutCancelled = True
            timeout = random.expovariate(LAMBDA)%STALL_MOVE_TIMEOUT_UPPER_BOUND
            if not self.moveCalled:
                self.moveCalled = True
                reactor.callLater(timeout, self.move)
        else:
            # cant find any better assignment, give grace time to other nodes
            log.debug("Giving grace time...")
            self.graceTimeoutCancelled = False
            if not self.finishCalled:
                self.finishCalled=True
                reactor.callLater(GRACE_TIMEOUT, self.finish)
                    
                    
    def createRequest(self):
        """Creates a new request.

        """
        log.debug("Creating new request...")
        self.request = self.dga.findNewAssignment()
        
        
    def cancelGraceTimeOut(self):
        """Cancels the ticking grace time out.

        """
        self.graceTimeoutCancelled = True
