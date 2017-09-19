import sys
import socket
import cv2
import numpy
from threading import Thread
import Queue

SERVER_ADDRESS = '192.168.43.218'
UDP_PORT = 10021
# import code; code.interact(local=dict(globals(), **locals()))

active_clients = []
encode_params = [int(cv2.IMWRITE_JPEG_QUALITY),30]

class UDPClient(Thread):
    def __init__(self, socket, client_address):
        Thread.__init__(self)
        self.mailbox = Queue.Queue()
        self.socket = socket
        self.address = client_address
        active_clients.append(self.mailbox)

    def run(self):
        while True:
            frame = self.mailbox.get()
            if isinstance(frame, basestring) and frame == 'shutdown':
                print self, 'shutting down'
                return
            self.socket.sendto(frame, self.address)

    def stop(self):
        active_clients.remove(self.mailbox)
        self.mailbox.put("shutdown")
        self.join()

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
                    for q in active_clients:
                        q.put(encoded_frame)

    def stop(self):
        self.join()

def server():
    udp_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )
    server_host = (SERVER_ADDRESS, UDP_PORT)
    print >>sys.stderr, 'Starting up on %s port %s\n' % server_host
    udp_socket.bind(server_host)

    caster = VideoCaster()
    caster.daemon = True
    caster.start()
    
    while True:
        print >>sys.stderr, 'Waiting to receive client request...\n'
        data, address = udp_socket.recvfrom(4096)

        print >>sys.stderr, 'Received a connection request from %s on port %s' % address
        print address
        new_client = UDPClient(udp_socket, address)
        new_client.daemon = True
        new_client.start()

if __name__ == "__main__":
    server()
