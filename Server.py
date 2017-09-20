import sys
import socket
import cv2
import numpy
from threading import Thread
import Queue
from datetime import datetime, timedelta

SERVER_ADDRESS = 'localhost'
UDP_PORT = 10021
# import code; code.interact(local=dict(globals(), **locals()))

active_udp_clients = dict()
encode_params = [int(cv2.IMWRITE_JPEG_QUALITY),20]

class UDPClient(Thread):
    def __init__(self, socket, client_address):
        Thread.__init__(self)
        self.mailbox = Queue.Queue()
        self.socket = socket
        self.address = client_address
        self.last_req_time = datetime.now()
        active_udp_clients[client_address] = self

    def run(self):
        while True:
            if (datetime.now() - self.last_req_time > timedelta(seconds = 90)):
                # Check last req time for hanged connections
                break
            frame = self.mailbox.get()
            if isinstance(frame, basestring) and frame == 'shutdown':
                break
            self.socket.sendto(frame, self.address)
        log('Shutting down client on %s:%s' % self.address)
        self.stop()

    def feed_frame(self, frame):
        self.mailbox.put(frame)

    def set_last_req_time(self):
        self.last_req_time = datetime.now()

    def stop(self):
        del active_udp_clients[self.address]
        self.mailbox.put("shutdown")

class VideoCaster(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.capture = cv2.VideoCapture(0)

    def run(self):
        while True:
            capture_success, frame = self.capture.read()
            if capture_success:
                encode_success, encoded_frame = cv2.imencode('.jpg', frame, encode_params)
                if encode_success:
                    for address, client in active_udp_clients.iteritems():
                        client.feed_frame(encoded_frame)

    def stop(self):
        self.capture.release()
        self.join()

def server():
    udp_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )
    server_host = (SERVER_ADDRESS, UDP_PORT)
    log('Starting up on %s port %s\n' % server_host)
    udp_socket.bind(server_host)

    caster = VideoCaster()
    caster.daemon = True
    caster.start()
    
    log('Waiting to receive client request...\n')
    while True:
        data, address = udp_socket.recvfrom(4096)

        if (active_udp_clients.has_key(address)):
            log('Received a refresh request from %s on port %s' % address)
            active_udp_clients[address].set_last_req_time()
        else:
            log('Received a connection request from %s on port %s' % address)
            new_client = UDPClient(udp_socket, address)
            new_client.daemon = True
            new_client.start()

def log(message):
    print >>sys.stderr, '[%s] - %s' % (datetime.now().strftime('%H:%M:%S'), message)

if __name__ == "__main__":
    server()
