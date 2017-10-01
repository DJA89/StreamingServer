import sys
import socket
import cv2
import numpy
from threading import Thread
import Queue
from datetime import datetime, timedelta
import re

SERVER_ADDRESS = 'localhost'
UDP_PORT = 10021
TCP_HOST = ''
TCP_PORT = 2100
# import code; code.interact(local=dict(globals(), **locals()))

active_udp_clients = dict()
active_tcp_clients = dict()
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

class TCPClient(Thread):
    def __init__(self, socket, client_address):
        Thread.__init__(self)
        self.mailbox = Queue.Queue()
        self.socket = socket
        self.address = client_address
        active_tcp_clients[client_address] = self

    def run(self):
        while True:
            frame = self.mailbox.get()
            if isinstance(frame, basestring) and frame == 'shutdown':
                socket.close()
                break

            self.socket.send(frame);
        log('Shutting down client on %s:%s' % self.address)
        self.stop()

    def feed_frame(self, frame):
        self.mailbox.put(frame)

    def stop(self):
        del active_tcp_clients[self.address]
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
                    data = numpy.array(encoded_frame)
                    stringData = data.tostring()
                    stringData = re.sub('inicio', 'sustituyendo_palabra', stringData)
                    stringData += 'inicio'
                    for address, client in active_tcp_clients.iteritems():
                        client.feed_frame(stringData)

    def stop(self):
        self.capture.release()
        self.join()

class UDPListener(Thread):
    def __init__(self, host):
        Thread.__init__(self)
        log('Starting UDP on %s port %s\n' % host)
        self.socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )
        self.socket.bind(host)

    def run(self):
        log('Waiting to receive UDP client request...\n')
        while True:
            data, address = self.socket.recvfrom(4096)

            if (active_udp_clients.has_key(address)):
                log('Received a refresh request from %s on port %s' % address)
                active_udp_clients[address].set_last_req_time()
            else:
                log('Received a UDP connection request from %s on port %s' % address)
                new_client = UDPClient(self.socket, address)
                new_client.daemon = True
                new_client.start()

class TCPListener(Thread):
    def __init__(self, host):
        Thread.__init__(self)
        # log('Strating TCP on %s port %s\n' % host)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((host, TCP_PORT))
        self.socket.listen(10)

    def run(self):
        log('Waiting to receive TCP client request...\n')
        while True:
            sc, addr = self.socket.accept()
            # log('Received a TCP connection request from %s on port %s' % addr, TCP_HOST)
            new_client = TCPClient(sc, addr)
            new_client.daemon = True
            new_client.start()


def server():
    udp_listener_thread = UDPListener((SERVER_ADDRESS, UDP_PORT))
    udp_listener_thread.start()
    tcp_listener_thread = TCPListener(TCP_HOST)
    tcp_listener_thread.start()

    caster = VideoCaster()
    caster.daemon = True
    caster.start()

def log(message):
    print >>sys.stderr, '[%s] - %s' % (datetime.now().strftime('%H:%M:%S'), message)

if __name__ == "__main__":
    server()
