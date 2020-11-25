#!/bin/sh

# Set the ip address for the private interface, which will be used
private_interface=private
ip link set dev $private_interface up
ip addr add 10.42.0.1/24 dev $private_interface

# Start the container
docker-compose up
