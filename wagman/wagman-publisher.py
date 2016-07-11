#!/usr/bin/env python3

from serial import Serial
import zmq
import time
import sys
import os.path
import re


"""
The WagMan publisher is responsible for distributing output of the WagMan-serial line to subscribers. Subscribers may need to use a session ID.
"""

header_prefix = '<<<-'
footer_prefix = '->>>'
wagman_device = '/dev/waggle_sysmon'


debug=1

if __name__ == "__main__":

    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    #socket.bind('tcp://*:5555')
    socket.bind('ipc:///tmp/zeromq_wagman-pub')


    last_message=""
    
    symlink_not_found_msg="error: symlink %s not found" % (wagman_device)
    wagman_connected_msg = 'connected to %s!' % (wagman_device)

    while True:
        
        if not os.path.exists(wagman_device):
            if last_message != symlink_not_found_msg:
                last_message = symlink_not_found_msg
                print(symlink_not_found_msg)
            time.sleep(5)
            continue
        
        try:
            # connect to wagman
            with Serial(wagman_device, 115200, timeout=8, writeTimeout=8) as serial:
                last_message = wagman_connected_msg
                print(wagman_connected_msg)

                output = []
                incommand = False
                commandname = None
                
                session_id=''
                
                while True:
                    line = serial.readline().decode().strip()

                    
                    
                    if incommand:
                        if line.startswith(footer_prefix):
                            incommand = False
                            
                            if session_id:
                                header = '{} cmd.{}'.format(session_id, commandname)
                            else:
                                header = 'cmd.{}'.format(commandname)
                                
                            body = '\n'.join(output)
                            
                            
                            
                            if debug:
                                print(("sending header:", header))
                                print(("sending body:", body))
                            
                            
                            msg = '{}\n{}'.format(header, body)
                            
                            socket.send_string(msg)
                            output = []
                        else:
                            output.append(line)
                    elif line.startswith(header_prefix):
                        session_id=''
                        if debug:
                            print(("received header:", line))
                        matchObj = re.match( r'.*sid=(\S+)', line, re.M|re.I)
                        if matchObj:
                            session_id=matchObj.group(1).rstrip()
                        
                        if debug:
                            if session_id:
                                print(("detected session_id:", session_id))
                            else:
                                print("no session_id detected")
                        
                        fields = line.split()
                        if debug:
                            print(fields)
                        #if len(fields) <= 2:
                        #    commandname = '?'
                        #else:
                        #    commandname = fields[2]
                        commandname = fields[-1]

                        incommand = True
                    elif line.startswith('log:'):
                        print(line)
                        socket.send_string(line)

            
        except Exception as e:
            socket.send_string("error: not connected to wagman")
            if str(e) != last_message:
                print(e)
                previous_error = str(e)
        
        time.sleep(5)
    
    