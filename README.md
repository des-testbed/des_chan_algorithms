des_chan_algorithms
===================

This repository comprises the implementation candidates of channel assignment algorithms based on [the DES-Chan framework](https://github.com/des-testbed/des_chan). The algorithms have been developed and evaluated on the [DES-Testbed](http://des-testbed.net). The evaluation results have been published in [1].

Currently available algorithms:

1. RAND (randomized channel assignment)

  This algorithm is more like a proof of concept for the DES-Chan framework. One wireless interface face per node is tuned to a common global channel to ensure basic connectivity, while the remaining interfaces are set to randomly selected channels from the set of all available channels.

2. DGA (distributed greedy algorithm)

  DGA has been first proposed in [2]. DGA assigns channels to network nodes, or more precisely, to network interfaces. Intuitively, each node tries to minimize the interference by assigning the least used channels in its interference set. The interference set of a node n consists of all nodes and their channel assignment whose transmissions affect sending and receiving at node n. To preserve the network connectivity, one interface is tuned to a global common channel and not used for channel assignment.
  
2. MICA (minimum interference channel assignment)

  MICA assigns channels to links instead of interfaces and is therefore topology preserving [3]. In other words, all links in the single channel network, also exist in the multi channel network after the channel assignment procedure.
This way, the approach is independent of the overlaying routing algorithm. This implementation comprises the distributed algorithm, which is based on a greedy approximation algorithm for the Max K-cut problem.
  
Installation from git
---------------------
1. Clone the repository:
    
        git clone git://github.com/des-testbed/des_chan_algorithms.git
    
2. Please make sure you have [the DES-Chan framework](https://github.com/des-testbed/des_chan) downloaded in your home folder.

3. Start the algorithm with sudo since super user privileges are required to change the network interface settings.

    Starting the RAND algorithm works like this:

        sudo python rand.py

[1] F.Juraschek, S. Seif, and M. Günes, Distributed Channel Assignment in Large-Scale Wireless Mesh Networks: A Performance Analysis, IEEE International Conference on Communications (ICC), 2013.

[2] B.-J. Ko, V. Misra, J. Padhye, and D. Rubenstein, Distributed channel assignment in multi-radio 802.11 mesh networks, in Wireless Communications and Networking Conference (WCNC), 2007.

[3] A.P. Subramanian, H. Gupta, and S.R. Das, Minimum interference channel assignment in multi-radio wireless mesh networks, in Sensor, Mesh and Ad Hoc Communications and Networks (SECON), 2007.
