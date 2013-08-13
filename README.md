des_chan_algorithms
===================

This repository comprises the implementation candidates of channel assignment algorithms based on [the DES-Chan framework](https://github.com/des-testbed/des_chan). The algorithms have been developed and evaluated on the [DES-Testbed](http://des-testbed.net).

Currently available algorithms:

1. RAND (randomized channel assignment)

  This algorithm is more like a proof of concept for the DES-Chan framework. One wireless interface face per node is tuned to a common global channel to ensure basic connectivity, while the remaining interfaces are set to randomly selected channels from the set of all available channels.

  
Installation from git
---------------------
1. Clone the repository:
    
        git clone git://github.com/des-testbed/des_chan_algorithms.git
    
2. Please make sure you have [the DES-Chan framework](https://github.com/des-testbed/des_chan) downloaded in your home folder.

3. Start the algorithm with sudo since super user privileges are required to change the network interface settings.

    Starting the RAND algorithm works like this:

        sudo python rand.py

