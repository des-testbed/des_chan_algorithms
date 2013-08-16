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


import sys
import random
import subprocess
from syslog  import *

from twisted.internet import reactor

# insert path to des_chan framework
p = subprocess.Popen('logname', stdout=subprocess.PIPE,stderr=subprocess.PIPE)
logname, errors = p.communicate()
sys.path.insert(0, '/home/' + logname.strip())

from des_chan import util, des_db
from des_chan.graph import Graph, ConflictGraph
from des_chan.interference import two_hop_frac
from des_chan.interference import co
from des_chan.topology import etx
from des_chan.error import CHANError

import messaging
from error import MICAError

from datetime import datetime


class Mica:

    def __init__(self, INTERFACES, CHANNELS, PORT, IFMODEL, DEBUG=False,
                 experiment_id=None):
        # configure instance
        self.INTERFACES = INTERFACES
        self.CHANNELS = CHANNELS
        if IFMODEL == '2hop':
            self.IFMODEL = two_hop_frac
        elif IFMODEL == '3hopco':
            self.IFMODEL = co
        self.DEBUG = DEBUG
        self.experiment_id = experiment_id
        messaging.DEBUG = DEBUG
        # init data structures
        self.node_name = util.resolve_node_name("localhost")
        self._allocated_interfaces = {}
        self._already_started = False
        # start with an empty conflict graph
        self.conflict_graph = ConflictGraph(Graph(), self.IFMODEL)
        # initialize the messaging object
        self.messaging = messaging.Messaging(self, PORT) 
        self.lock = Lock()
        self._iteration = 0
        self._if_ids = {}


    def start(self):
        """This method starts the algorithm by retrieving the network graph and
        starting the twisted event loop.

        """
        if not self._already_started:
            # write status file
            statfile = open("/tmp/mica.status", "w")
            statfile.write("%s %s\n" % (self.node_name, util.red("running")))
            statfile.close()
            # make etx read the network graph from file
            self._already_started = True
            reactor.callWhenRunning(self.new_iteration)
            # start the twisted event loop
            reactor.run()
        else:
            raise MICAError("Reactor can only be started once!")


    def stop(self):
        """This method stops the algorithm and the twisted event loop.

        """
        # write status file
        statfile = open("/tmp/mica.status", "w")
        statfile.write("%s %s\n" % (self.node_name, util.green("finished")))
        statfile.close()
        # do not stop the reactor because wwe have to wait for messages from
        # other mica instances
        #reactor.stop()


    def new_iteration(self):
        """Starts a new iteration of the algorithm. This is the only method that
        is started via the reactor and thus can be interrupted by incoming
        channel requests.

        """
        syslog(LOG_DEBUG, "new_iteration: %s" % util.bold("starting new iteration"))
        self._iteration += 1
        # ask the etx daemon only in the first iteration and rely on channel
        # update messages afterwards
        if self._iteration == 1:
            # get the current network graph from the etx daemon
            deferred = etx.get_network_graph()
            # callbacks
            deferred.addCallback(self._init_network_graph)
            # errbacks
            deferred.addErrback(self._handle_error)
            syslog(LOG_DEBUG, "finished getting the network graph")
        else:
            reactor.callWhenRunning(self._find_minimum)

    
    def request_choice(self, u, k, retries):
        """Checks if a request is valid and acts accordingly.

        """
        # check the interface constraint
        if self.obeys_interface_constraint(u, k):
            # either the channel can be changed without affecting other
            # links, or we have an unused interface left
            self.messaging.send_channel_request(u, k, retries)
        else:
            # we need an unused interface to implement this assignment, but
            # no interfaces are left, therefore abandon this choice
            self.abandon_choice(u, k)
            # and start a new iteration
            reactor.callWhenRunning(self.new_iteration)


    def apply_choice(self, u, k, peer_if_name=None):
        """Applys the given combination of conflict graph vertex and channel by
        tuning the network interface and updating the data strucutures.

        """
        if_name = self._get_allocated_interface(u, k)
        if not if_name:
            # We did not allocate an unused interface for this combination
            # although it is needed. In theory, we should never end up here!
            # Therefore, something must have gone completely wrong.  This is a
            # critical point in the program flow, since the neighbor has
            # probably already changed its channel and is therefore unreachable.
            raise MICAError("No unused interface was allocated for (%s, %d). "\
                            "This should never happpen!" % (u, k))

        # check we need to set up a new interface with the channel
        if not util.is_interface_up(if_name):
            util.set_up_interface(if_name)
            setup_new_interface = True
        else:
            setup_new_interface = False
        # remember old channel for being able to revert changes
        old_channel = u.get_channel()
        util.set_channel(if_name, k)
        # do not try this (u,k) combination again
        try:
            u.channels.remove(k)
            syslog(LOG_DEBUG, str(datetime.now()) + " apply_choice: removed combination (%s %d)" % (u, k))
        except KeyError:
            syslog(LOG_DEBUG, str(datetime.now()) + " apply_choice: unable to remove combination (%s %d)" % (u, k))
        # wait some time for the new assignment to take effect
        neighbor_node = u.get_nw_graph_neighbor(self.node_name)
        neighbor_ip = util.get_node_ip(neighbor_node, k)
        for tries in range(3, 0, -1):
            syslog(LOG_DEBUG, str(datetime.now()) + " apply_choice: waiting for the new channel assignment to take effect")
            util.busy_wait(5)
            
            # establishing the link takes too long, therefore skip it
            link_established = True
            break

            if util.is_available(neighbor_ip):
                link_established = True
                break
            elif tries == 1:
                link_established = False

        if link_established:
            # change the channel in the local conflict graph
            u.set_channel(k)
            # make sure to listen for channel requests on all interfaces that are
            # currently used
            self.messaging.start_servers()
            # insert link data into the database if we own this link
            # (peer_if_name is only sent in channel reply messages)
            if peer_if_name:
                self._insert_link_data(u, if_name, peer_if_name)

            syslog(LOG_DEBUG, str(datetime.now()) + " %s" % str(self.conflict_graph.network_graph.get_adjacency_matrix()))

            # propagate update to 2hop neighbors
            self.messaging.send_channel_update(u)
        else:
            # the link could not be established, revert the changes
            syslog(LOG_DEBUG, str(datetime.now()) +  " apply_choice: link could %s, reverting changes" % util.bold("not be established"))
            if setup_new_interface:
                util.shut_down_interface(if_name)
            else:
                util.set_channel(if_name, old_channel)
            # unlock the mica instance 
            self.lock.free()


    def abandon_choice(self, u, k):
        """Update the data structures to not try the given combination of conflict
        graph vertex and channel again.

        """
        # free interface lock
        self._get_allocated_interface(u, k)
        # do not try this (u,k) combination again
        try:
            u.channels.remove(k)
            syslog(LOG_DEBUG, str(datetime.now()) + " abandon_choice: removed combination (%s %d)" % (u, k))
        except KeyError:
            syslog(LOG_DEBUG, str(datetime.now()) + " abandon_choice: unable to remove combination (%s %d)" % (u, k))
        # unlock the mica instance
        self.lock.free()

    
    def get_vertex(self, ip):
        """Returns the vertex in the conflict graph that corresponds to the link to
        the given IP.

        """
        neighbor_node = util.resolve_node_name(ip)
        vertex = self.conflict_graph.get_vertex(self.node_name, neighbor_node)
        if not vertex:
            raise MICAError("Unable to determine conflict graph vertex for the link to %s" % ip)
        else:
            return vertex


    def get_ip(self, vertex):
        """Returns the IP address of the interface that belongs to the neighbor
        and is tuned to the channel which correspond to the given conflict
        graph vertex.

        """
        # get the name of the neighbor
        neighbor_node = vertex.get_nw_graph_neighbor(self.node_name)
        try:
            # get the ip of the neighbor's interface that is tuned to the old channel 
            ip = util.get_node_ip(neighbor_node, vertex.get_channel())
        except CHANError:
            raise MICAError("Unable to determine the IP for neighbor %s on "
                            "channel %d" % (neighbor_node, vertex.get_channel()))
        else:
            return ip


    def obeys_interface_constraint(self, u, k):
        """Returns true, if the given combination of conflict graph vertex and
        channel obeys the interface constraint, false otherwise.
        The interface constraint states that a node can only use as many
        simultaneous channels as the number of network interfaces. Furthermore, if a
        node has only one neighbor on the given channel, it may also be changed
        without affecting others.
        Additionally, an interface is allocated for this combination.

        """
        # if an interface for this combination is already allocated, the
        # constraint is not violated and we do not need to allocate a new one
        if (u, k) in self._allocated_interfaces.values():
            syslog(LOG_DEBUG, str(datetime.now()) + " obeys_interface_constraint: interface for (%s, %d) already allocated" % (u, k))
            return True

        # if there is already an interface tuned to the requested channel, we
        # can use that one without changing anything
        try:
            if_name = util.get_if_name(k)
        except CHANError:
            pass
        else:
            syslog(LOG_DEBUG, str(datetime.now()) + " obeys_interface_constraint: %s is %s to channel %s" % (if_name, util.bold("already tuned"), k))
            self._allocate_interface(if_name, u, k)
            return True

        # if this is the only neighbor, the constraint is not violated
        if self._is_vertex_channel_unique(u):
            # allocate the interface
            try:
                if_name = util.get_if_name(u.get_channel())
            except CHANError:
                pass
            else:
                # check if the interface can do 5GHz if the channel is from that band
                if if_name == 'wlan0' and k > 14:
                    pass
                else:
                    self._allocate_interface(if_name, u, k)
                    return True

        # otherwise check if we have free interfaces left
        possible_interfaces = set(self.INTERFACES) -\
                              set(self._allocated_interfaces.keys())
        syslog(LOG_DEBUG, str(datetime.now()) + " obeys_interface_constraint: unallocated interfaces: %s" % str(possible_interfaces))
        try:
            if_name = util.get_free_if_name(possible_interfaces)
        except CHANError:
            # no interfaces left, we cannot implement this choice
            syslog(LOG_DEBUG, str(datetime.now()) + " obeys_interface_constraint: no free interfaces left! unable to implement (%s, %d)" % (u, k))
            return False
        else:
            # constraint is obeyed, we have an interface left, therefore
            # allocate it
            self._allocate_interface(if_name, u, k)
            return True


    def is_valid_channel(self, channel):
        """Returns True, if the given channel is part of the allowed channel set
        whith which the algorithm has been initialized.

        """
        return channel in self.CHANNELS


    ### Private methods

    def _init_network_graph(self, network_graph):
        """Updates the conflict graph with the information from the given
        network graph.

        """
        syslog(LOG_DEBUG, str(datetime.now()) + "init network graph")
        # remove possible duplicate links
        network_graph = Mica._make_plain(network_graph)
        # save old vertex set
        old_vertices = self.conflict_graph.get_vertices_for_node(self.node_name)
        # update conflict graph with new network graph
        self.conflict_graph.update(network_graph)
        # initialize new vertices
        for new_vertex in self.conflict_graph.get_vertices_for_node(self.node_name) - old_vertices:
            new_vertex.channels = set(self.CHANNELS)
        # make sure to listen for channel requests on all interfaces that are
        # currently used
        reactor.callWhenRunning(self.messaging.start_servers)
        # insert the initial network graph in the database
        for vertex in self._get_own_vertices():
            self._insert_link_data(vertex, self.INTERFACES[0],
                                   self.INTERFACES[0])
        # find the vertex channel combination that minimizes interference
        self._find_minimum()


    def _find_minimum(self):
        """Finds the combination of conflict graph vertex u and channel k that
        minimizes interference in the local neighborhood.

        """
        syslog(LOG_DEBUG, str(datetime.now()) + "starting find minimum")
        self.conflict_graph.write_to_file("/tmp/cg-%d.dot" % self._iteration, True)
        self.conflict_graph.network_graph.write_to_file("/tmp/ng-%d.dot" % self._iteration, True)
        syslog(LOG_DEBUG, str(datetime.now()) + " %s" % str(self.conflict_graph.network_graph.get_adjacency_matrix()))

        # u: vertex, k: channel
        min_u_k = None
        min_interference = self.conflict_graph.get_interference_sum()
        syslog(LOG_DEBUG, str(datetime.now()) + " own vertices: %d" % len(self._get_own_vertices()))
        for u in self._get_own_vertices():
            # save original channel
            orig_k = u.get_channel()
            channels_list = list(u.channels)
            random.shuffle(channels_list)
            for k in channels_list:
                syslog(LOG_DEBUG, str(datetime.now()) + " _find_minimum: trying (%s, %d)" % (u, k))
                # set the channel and see if interference is reduced
                u.set_channel(k)
                sum = self.conflict_graph.get_interference_sum()
                # did we find a minimum?
                if sum < min_interference:
                    syslog(LOG_DEBUG, str(datetime.now()) + " _find_minimum: %.3f < %.3f, found minimum: (%s, %d)" % (sum, min_interference, u, k))
                    min_u_k = (u, k)
                    min_interference = sum
            # reset original channel of this vertex
            u.set_channel(orig_k)
        # did we find a vertex-channel combination that further minimizes interference?
        if min_u_k:
            u, k = min_u_k
            self.request_choice(u, k, 5)
        else:
            syslog(LOG_DEBUG, str(datetime.now()) + " _find_minimum: no vertex-channel combination found that further minimizes interference")
            syslog(LOG_DEBUG, str(datetime.now()) + " %s" % str(self.conflict_graph.network_graph.get_adjacency_matrix()))
            self.stop()
        
        syslog(LOG_DEBUG, str(datetime.now()) + "stop find minimum")


    ### Helper methods

    def _insert_link_data(self, vertex, source_if, sink_if):
        """Inserts the link information into the database for visualization.

        """
        return
        source_node = self.node_name
        sink_node = vertex.get_nw_graph_neighbor(self.node_name)
        syslog(LOG_DEBUG, str(datetime.now()) + " _insert_link_data: inserting data for %s-%s, %s-%s" % (source_node, source_if, sink_node, sink_if))
        # get source interface id from cache or database
        try:
            source_id = self._if_ids[source_node][source_if]
        except KeyError:
            query = "SELECT i.id FROM \"NetworkInterface\" i JOIN \"Node\" n "\
                    "ON (n.id = i.node_id) WHERE i.name='%s' AND n.name='%s'" %\
                    (source_if, source_node)
            syslog(LOG_DEBUG, str(datetime.now()) + " _insert_link_data: %s" % query) 
            result = des_db._raw_query(query)
            source_id = result[0]["id"]
            if source_node not in self._if_ids.keys():
                self._if_ids[source_node] = {}
            self._if_ids[source_node][source_if] = source_id
        # get sink interface id from cache or database
        try:
            sink_id = self._if_ids[sink_node][sink_if]
        except KeyError:
            query = "SELECT i.id FROM \"NetworkInterface\" i JOIN \"Node\" n "\
                    "ON (n.id = i.node_id) WHERE i.name='%s' AND n.name='%s'" %\
                    (sink_if, sink_node)
            syslog(LOG_DEBUG, str(datetime.now()) + " _insert_link_data: %s" % query) 
            result = des_db._raw_query(query)
            sink_id = result[0]["id"]
            if sink_node not in self._if_ids.keys():
                self._if_ids[sink_node] = {}
            self._if_ids[sink_node][sink_if] = sink_id
        # get sample id
        query = "SELECT max(id) FROM \"RoutingSample\""
        if self.experiment_id:
            query += " WHERE experiment_id=%d" % self.experiment_id
        syslog(LOG_DEBUG, str(datetime.now()) + " _insert_link_data: %s" % query) 
        result = des_db._raw_query(query)
        sample_id = result[0]["max"]
        # create routing sample if there is none for this experiment
        if not sample_id:
            query = "INSERT INTO \"RoutingSample\" (experiment_id, timestamp) "\
                    "VALUES (%d, current_timestamp) RETURNING id" %\
                    self.experiment_id
            syslog(LOG_DEBUG, str(datetime.now()) + " _insert_link_data: %s" % query) 
            result = des_db._raw_query(query)
            sample_id = result[0]["id"]
        conn_data = {
            "sample_id": sample_id,
            "source_node": source_node,
            "source_id": source_id,
            "sink_node": sink_node,
            "sink_id": sink_id,
            "channel": vertex.get_channel()
        }
        query = des_db._insert("ChanConnections", conn_data)
        syslog(LOG_DEBUG, str(datetime.now()) + " _insert_link_data: %s" % query) 
        # update channel information
        for interface_id in (source_id, sink_id):
            chan_data = {"channel": vertex.get_channel()}
            chan_where = "sample_id=%d AND interface_id=%d" % (sample_id,
                                                               interface_id) 
            rowcount, query = des_db._update("ChannelInfo", chan_data, chan_where)
            syslog(LOG_DEBUG, str(datetime.now()) + " _insert_link_data: %s" % query) 
            if rowcount < 1:
                # insert if there was no channel information in the table
                chan_data["sample_id"] = sample_id
                chan_data["interface_id"] = interface_id
                query = des_db._insert("ChannelInfo", chan_data)
                syslog(LOG_DEBUG, str(datetime.now()) + " _insert_link_data: %s" % query) 



    def _get_own_vertices(self):
        """Returns a list containing all conflict graph vertices that are owned
        by this node. A node owns a vertex, if it is adjacent to the
        corresponding link and if its ID is higher than the beighbors' ID.

        """
        own_vertices = []
        for u in self.conflict_graph.get_vertices_for_node(self.node_name):
            neighbor_node = u.get_nw_graph_neighbor(self.node_name)
            # we own the vertex if our id is higher
            if self.node_name > neighbor_node:
                own_vertices.append(u)
        return own_vertices


    def _allocate_interface(self, if_name, u, k):
        """Allocates a lock for the given interface and vertex-channel
        combination, to make sure that it is not used to satisfy another channel
        request while we are waiting for the reply. 
        
        """
        syslog(LOG_DEBUG, str(datetime.now()) + " _allocate_interface: allocating %s for (%s, %d)" % (if_name, u, k))
        self._allocated_interfaces[if_name] = (u, k)


    def _get_allocated_interface(self, u, k, unlock=True):
        """Returns the name of the unused interface that has been allocated for
        the given vertex-channel combination and removes the lock. If no
        interface has been allocated, the method returns None.

        """
        syslog(LOG_DEBUG, str(datetime.now()) + " _get_allocated_interface: trying to get allocated interface for (%s, %d)" % (u, k))
        # did we allocate an interface for this combination?
        for interface, uk in self._allocated_interfaces.items():
            if uk == (u, k):
                # unlock  and return interface
                if unlock:
                    del self._allocated_interfaces[interface]
                return interface
        # no interface allocated
        return None


    def _is_vertex_channel_unique(self, u):
        """Returns true, if the link corresponding to the given vertex is the only
        one that uses the vertex's channel, i.e. if the channel of this vertex can
        be changed without affecting any other links.

        """
        k = u.get_channel()
        # is this the only neighbor on the channel?
        for vertex in self.conflict_graph.get_vertices_for_node(self.node_name) - set([u]):
            if vertex.get_channel() == k:
                return False
        return True


    @staticmethod
    def _make_plain(g):
        """The original algorithm is designed to support only one link between
        two nodes. However, it may occur that two nodes are connected
        unintentionally by multiple links. For example:
        A ---(40)--- B ---(36)--- C ---(40)--- D
        In that case, B and C are connected via channel 36, but both have
        another interface tuned to channel 40 in order to communicate with
        their other neighbors. Therefore also an implicit link on channel 40
        exists between B and C. If the network graph contains multiple links,
        the link on the best channel is chosen.

        """
        plain_g = g.copy()
        edges = []
        channels = []
        for edge, value in plain_g.get_edges().items():
            #print "%s = %s" % (edge, value)
            if isinstance(value, set):
                if len(value) > 1:
                    edges.append(edge)
                    channels.append(list(value))
                plain_g.set_edge_value(edge, list(value)[0])
        # if we did not find multiple links, we are finished
        if not channels:
            syslog(LOG_DEBUG, str(datetime.now()) + " _make_plain: no edges with multiple channels found")
            return plain_g
        # otherwise find the combination that minimizes interference and take that
        # as basis for the actual ca algorithm
        cg = ConflictGraph(plain_g, self.IFMODEL)
        min_interference = cg.get_interference_sum()
        # create a copy that is returned if the minimum is already found
        plain_g = cg.network_graph.copy()
        # permute over all channel combinations
        for combination in Mica._cartesian_product(channels):
            syslog(LOG_DEBUG, str(datetime.now()) + " _make_plain: %s" % str(combination))
            for e in edges:
                vertex = cg.get_vertex(e[0], e[1])
                channel = combination[edges.index(e)]
                # set the alternative channel
                vertex.set_channel(channel)
            # get the interference sum for this assignment
            interference = cg.get_interference_sum()
            if interference < min_interference:
                syslog(LOG_DEBUG, str(datetime.now()) + " _make_plain: %d < %d found minimum" % (interference, min_interference))
                min_interference = interference
                plain_g = cg.network_graph.copy()
        return plain_g


    @staticmethod
    def _cartesian_product(arg_list):
        pools = map(tuple, arg_list)
        result = [[]]
        for pool in pools:
            result = [x+[y] for x in result for y in pool]
        for prod in result:
            yield tuple(prod)


    def _handle_error(self, error):
        """Method for printing error messages.

        """
        syslog(LOG_DEBUG, str(datetime.now()) + " Error: %s" % (error.getErrorMessage()))
        error.printTraceback()
        reactor.stop()


class Lock:
    """Simple lock implementation to avoid competition among multiple
    requests.

    """

    def __init__(self):
        self._locked = False
        self._tokens = set()


    def lock(self, tokens=None):
        """Lock the instance.

        """
        if self._locked:
            syslog(LOG_DEBUG, str(datetime.now()) + " Lock:lock: instance already locked")
        else:
            syslog(LOG_DEBUG, str(datetime.now()) + " Lock:lock: %s instance" % util.red("locking"))
            self._locked = True
        if tokens:
            self._tokens.update(tokens)


    def free(self, token=None):
        """Free the instance.

        """
        if not self._locked:
            syslog(LOG_DEBUG, str(datetime.now()) + " Lock:free: instance was not locked")
        else:
            if token:
                syslog(LOG_DEBUG, str(datetime.now()) + " Lock:free: unlocking token:", token)
            self._tokens.discard(token)
            self._locked = (len(self._tokens) != 0)
            if not self._locked:
                syslog(LOG_DEBUG, str(datetime.now()) + " Lock:free: %s instance" % util.green("unlocking"))


    def is_locked(self):
        """Return the lock status.

        """
        return self._locked


