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


from syslog import *
from datetime import datetime

import netifaces
from pythonwifi import iwlibs
from twisted.internet import reactor, defer
from twisted.internet.protocol import ServerFactory, ClientFactory
from twisted.protocols.basic import LineOnlyReceiver

from socket import SOL_SOCKET, SO_BROADCAST
from twisted.internet.protocol import DatagramProtocol

#import subprocess 

# insert path to des_chan framework
#p = subprocess.Popen('logname', stdout=subprocess.PIPE,stderr=subprocess.PIPE)
#logname, errors = p.communicate()
#sys.path.insert(0, '/home/' + logname.strip())

from des_chan import util

DEBUG = False

class Messaging:

    REQUEST_MSG = "RQST"
    REPLY_MSG = "RPLY"
    REJECT_MSG = "RJCT"
    UPDATE_MSG = "UPDT"
    # number of seconds to wait before assuming the connection has failed
    CONNECT_TIMEOUT = 10
    # number of retries if a connection fails (e.g. if the mica instance on the
    # neighbor node is not yet listening
    MAX_RETRIES = 5

    def __init__(self, mica, PORT=9159):
        self.mica = mica
        self.PORT = PORT
        self._msg_ports = {}
        self._upd_ports = {}


    def start_servers(self):
        """Starts the servers that listen for messages from neighboring nodes.
        If the IP of an interface has changed, the server is restarted to listen
        at the new IP. If interfaces have been shut down, servers are stopped.

        """
        for if_name in iwlibs.getWNICnames():
            if not util.is_interface_up(if_name):
                # interface is down
                if if_name in self._msg_ports.keys():
                    # stop listening for messages if we previously used it
                    syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:start_servers: %s: interface is down, stop listening for messages at %s:%s" % (if_name, self._msg_ports[if_name].getHost().host, self._msg_ports[if_name].getHost().port))
                    self._msg_ports[if_name].stopListening()
                    del self._msg_ports[if_name]
                # stop listening for updates if we previously used the interface
                if if_name in self._upd_ports.keys():
                    syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:start_servers: %s: interface is down, stop listening for updates at %s:%s" % (if_name, self._upd_ports[if_name][0].getHost().host, self._upd_ports[if_name][0].getHost().port))
                    self._upd_ports[if_name][0].stopListening()
                    del self._upd_ports[if_name]
            else:
                # interface is up, determine current ip and broadcast address
                try:
                    ip = netifaces.ifaddresses(if_name)[netifaces.AF_INET][0]['addr']
                    bcast = netifaces.ifaddresses(if_name)[netifaces.AF_INET][0]['broadcast']
                except KeyError:
                    syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:start_servers: %s: unable to determine IP address, although the interface seems to be up " % (if_name))
                    continue
                # check if IP has changed
                if if_name in self._msg_ports.keys() and \
                   ip != self._msg_ports[if_name].getHost().host:
                    syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:start_servers: %s: IP address has changed, stop listening at  %s:%s" % (if_name, self._msg_ports[if_name].getHost().host, self._msg_ports[if_name].getHost().port))
                    # ip has changed, stop listening at the old address
                    self._msg_ports[if_name].stopListening()
                    del self._msg_ports[if_name]
                # check if broadcast address has changed
                if if_name in self._upd_ports.keys() and \
                   bcast != self._upd_ports[if_name][0].getHost().host:
                    syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:start_servers: %s: broadcast address has changed, stop listening at  %s:%s" % (if_name, self._upd_ports[if_name][0].getHost().host, self._upd_ports[if_name][0].getHost().port))
                    # broadcast address has changed, stop listening at the old
                    # address
                    self._upd_ports[if_name][0].stopListening()
                    del self._upd_ports[if_name]
                # start listening for messages if necessary
                if if_name not in self._msg_ports.keys():
                    # listen at the new address
                    factory = MessageServerFactory(self.mica)
                    self._msg_ports[if_name] = reactor.listenTCP(self.PORT,
                                                                 factory, 20,
                                                                 ip)
                    syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:start_servers: %s: listening at %s:%s" % (if_name, ip, self.PORT))
                # start listening for updates if necessary
                if if_name not in self._upd_ports.keys():
                    # listen at the new address
                    protocol = UpdateProtocol(self.mica)
                    port = reactor.listenUDP(self.PORT, protocol, bcast)
                    self._upd_ports[if_name] = (port, protocol)
                    syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:start_servers: %s: listening at %s:%s" % (if_name, bcast, self.PORT))


    def send_channel_request(self, u, k, retries):
        """Sends a channel request message to the specified host. If a reply is
        not received within a certain time, a channel reject event is created
        automatically.

        """
        ip = self.mica.get_ip(u)
        syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:send_channel_request: %s %s %d --> %s" % (u, ip, u.get_channel(), k))
        # the factory store the context of this request
        factory = MessageClientFactory(self.mica, u, k, retries)
        # lock the mica instance
        self.mica.lock.lock()
        # connect to the neighbor
        reactor.connectTCP(ip, self.PORT, factory, Messaging.CONNECT_TIMEOUT)


    def send_channel_update(self, u):
        """Sends a channel update message.

        """
        # check if we just forward the message or if we are the originator
        if self.mica.node_name in u.nw_graph_edge:
            # we are originator
            syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:send_channel_update: sending channel update (%s %d)" % (u, u.get_channel()))
            # ask the recipients to forward the message
            forward = True
            self.mica.lock.free()
        else:
            # we forward the update message
            syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:send_channel_update: forwarding channel update (%s %d)" % (u, u.get_channel()))
            # do not forward the message any further
            forward = False
        # broadcast the message on all interfaces
        for if_name, (port, protocol) in self._upd_ports.items():
            syslog(LOG_DEBUG, str(datetime.now()) + " Messaging:send_channel_update: broadcasting on %s" % if_name)
            protocol.send_channel_update(u, forward)


### Channel Updates

class UpdateProtocol(DatagramProtocol):

    def __init__(self, mica):
        self.mica = mica


    def startProtocol(self):
        """Starting point for the protocol.

        """
        # set broadcast socket option
        self.transport.socket.setsockopt(SOL_SOCKET, SO_BROADCAST, True)


    def datagramReceived(self, datagram, addr):
        """Handle received datagrams.

        """
        request = datagram.split(":")
        if len(request) == 5 and request[0].upper() == Messaging.UPDATE_MSG:
            # received channel update
            node1, node2, channel, forward = request[1:]
            channel = int(channel)
            forward = int(forward)
            syslog(LOG_DEBUG, str(datetime.now()) + " UpdateProtocol:datagramReceived: received channel update for (%s_%s, %d, %s)" % (node1, node2, channel, forward))
            # discard messages from ourselves
            if node1 == self.mica.node_name or node2 == self.mica.node_name:
                syslog(LOG_DEBUG, str(datetime.now()) + " UpdateProtocol:datagramReceived: node is part of the concerned vertex, discarding update message")
                return
            # get corresponding conflict graph vertex
            vertex = self.mica.conflict_graph.get_vertex(node1, node2)
            if vertex:
                # update channel in the conflict graph
                vertex.set_channel(channel)
                #print self.mica.conflict_graph.network_graph.get_adjacency_matrix()
                # forward the message if info is new and flag was set
                if forward:
                    syslog(LOG_DEBUG, str(datetime.now()) + " UpdateProtocol:datagramReceived: forward flag set")
                    reactor.callWhenRunning(self.mica.messaging.send_channel_update,
                                           vertex)
            else:
                syslog(LOG_DEBUG, str(datetime.now()) + " UpdateProtocol:datagramReceived: vertex %s_%s is not in the conflict graph" % (node1, node2))
        else:
            syslog(LOG_DEBUG, str(datetime.now()) + " UpdateProtocol:datagramReceived: received unknown message: %s" % datagram)


    def send_channel_update(self, vertex, forward):
        """Build datagram for channel update message and send it out.

        """
        datagram = "%s:%s:%s:%d:%d" % (Messaging.UPDATE_MSG,
                                       vertex.nw_graph_edge[0],
                                       vertex.nw_graph_edge[1],
                                       vertex.get_channel(),
                                       forward)
        self.transport.write(datagram, (self.transport.getHost().host,
                                        self.transport.getHost().port))


### Message Server

class MessageServerProtocol(LineOnlyReceiver):

    delimiter = '\n'
    ERR_SYNTAX = "INVALID SYNTAX"

    def connectionMade(self):
        """Log the successful connection.

        """
        syslog(LOG_DEBUG, str(datetime.now()) + " MessageServerProtocol:connectionMade: handling connection from %s:%s" % (self.transport.getPeer().host, self.transport.getPeer().port))

    def lineReceived(self, request):
        """Handle a received message.

        """
        syslog(LOG_DEBUG, str(datetime.now()) + " MessageServerProtocol:lineReceived: received message: %s" % request)
        # parse request
        request = request.split(":")

        if len(request) == 2 and request[0].upper() == Messaging.REQUEST_MSG:
            # received channel request, check if we can process it
            if self.factory.mica.lock.is_locked():
                # the mica instance is processing another request at the moment,
                # therefore lose the connection. the client will try again later
                syslog(LOG_DEBUG, str(datetime.now()) + " MessageServerProtocol:lineReceived: mica instance %s" % util.bold("is locked"))
            else:
                # channel request can be processed
                k = int(request[1])
                u = self.factory.mica.get_vertex(self.transport.getPeer().host)
                syslog(LOG_DEBUG, str(datetime.now()) + " MessageServerProtocol:lineReceived: received channel request for (%s, %d)" % (u, k))
                if self.factory.mica.is_valid_channel(k) and \
                   self.factory.mica.obeys_interface_constraint(u, k):
                    # lock the mica instance to prevent conflicting channel
                    # changes
                    self.factory.mica.lock.lock()
                    # interface constraint obeyed, send channel reply
                    syslog(LOG_DEBUG, str(datetime.now()) + " MessageServerProtocol:lineReceived: sending channel reply")
                    msg = "%s:%s" % (Messaging.REPLY_MSG,
                                     self.factory.mica._get_allocated_interface(u, k, False))
                    self.sendLine(msg)
                    # apply the requested assignment
                    # this has to be called later, otherwise the reply message
                    # is sent after the apply method has been executed
                    reactor.callLater(3, self.factory.mica.apply_choice, u, k)
                else:
                    # interface constraint violated, send channel reject
                    syslog(LOG_DEBUG, str(datetime.now()) + " MessageServerProtocol:lineReceived: sending channel reject")
                    self.sendLine(Messaging.REJECT_MSG)

        else:
            # invalid request, send error message
            self.sendLine(MessageServerProtocol.ERR_SYNTAX)
        # shut down the connection
        self.transport.loseConnection()


class MessageServerFactory(ServerFactory):

    protocol = MessageServerProtocol

    def __init__(self, mica):
        self.mica = mica


### Message Client

class MessageClientProtocol(LineOnlyReceiver):
    
    delimiter = '\n'

    def connectionMade(self):
        """Send the request after the connection has been made.

        """
        request = "%s:%d" % (Messaging.REQUEST_MSG, self.factory.k)
        syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientProtocol:connectionMade: sending %s" % request)
        # send channel request and wait for reply
        self.sendLine(request)
        # set timeout for reply
        self.factory.timeout = reactor.callLater(5,
                                                 self.transport.loseConnection)
    
    def lineReceived(self, reply):
        """Handle a received message.

        """
        # compare commands case-insensitive
        reply = reply.split(":")
        # shut down the connection
        self.transport.loseConnection()
        if len(reply) == 2 and reply[0].upper() == Messaging.REPLY_MSG:
            syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientProtocol:lineReceived: received channel reply")
            # cancel timeout
            self.factory.timeout.cancel()
            self.factory.received_answer = True
            # received channel reply, apply choice
            self.factory.mica.apply_choice(self.factory.u, self.factory.k,
                                           reply[1])
        elif reply[0].upper() == Messaging.REJECT_MSG:
            syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientProtocol:lineReceived: received channel reject")
            # cancel timeout
            self.factory.timeout.cancel()
            self.factory.received_answer = True
            # received channel reject, abandon choice
            self.factory.mica.abandon_choice(self.factory.u, self.factory.k)
        else:
            syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientProtocol:lineReceived: received unknown reply: %s" % reply)
            self.factory.mica.abandon_choice(self.factory.u, self.factory.k)
        # start a new iteration of the algorithm
        reactor.callWhenRunning(self.factory.mica.new_iteration)


class MessageClientFactory(ClientFactory):

    protocol = MessageClientProtocol

    def __init__(self, mica, u, k, retries):
        self.mica = mica
        self.u = u
        self.k = k
        self.retries = retries
        self.received_answer = False


    def startedConnecting(self, connector):
        """Log connection.

        """
        syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientFactory:startedConnecting connecting to %s" % (connector.getDestination().host))


    def clientConnectionFailed(self, connector, reason):
        """Log connection failed.

        """
        host = connector.getDestination().host
        port = connector.getDestination().port
        syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientFactory:clientConnectionFailed: connection to %s:%s failed: %s" % (host, port, reason.getErrorMessage()))
        self._retry()
    

    def clientConnectionLost(self, connector, reason):
        """Log lost connection and retry.

        """
        host = connector.getDestination().host
        port = connector.getDestination().port
        syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientFactory:clientConnectionLost: connection to %s:%s lost: %s" % (host, port, reason.getErrorMessage()))
        if not self.received_answer:
            syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientFactory:clientConnectionLost: did not receive an answer yet")
            self._retry()
    

    def _retry(self):
        """Retry an connection attempt.

        """
        # try again as long as maximum number of retries is not exceeded
        if self.retries > 0:
            syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientFactory:_retry: scheduling retry in 5 seconds") 
            reactor.callLater(5, self.mica.request_choice, self.u, self.k,
                              self.retries - 1)
            # free interface lock
            self.mica._get_allocated_interface(self.u, self.k)
            # unlock the mica instance
            self.mica.lock.free()
        else:
            syslog(LOG_DEBUG, str(datetime.now()) + " MessageClientFactory:_retry: maximum number of connection attempts exceeded, giving up")
            # give up and start a new iteration 
            self.mica.abandon_choice(self.u, self.k)
            # reactor.callWhenRunning does not seem to work here, therefore call
            # later
            reactor.callLater(1, self.mica.new_iteration)

