FROM ubuntu:14.04

# git is installed for development purposes only, will remove later
RUN apt-get update ; apt-get install -y git

ADD . /usr/lib/waggle/nodecontroller/

RUN cd /usr/lib/waggle/nodecontroller/ && ./scripts/install_dependencies.sh

WORKDIR /usr/lib/waggle/nodecontroller/
