import sys
import socket
import cv2
import numpy
from threading import Thread
import Queue
from datetime import datetime, timedelta
import re
import signal
import threading
import time

SERVER_ADDRESS = '127.0.0.1'
UDP_PORT = 10021
TCP_HOST = ''
TCP_PORT = 2100
# import code; code.interact(local=dict(globals(), **locals()))
# sudo sysctl -w net.inet.udp.maxdgram=65535
active_udp_clients = dict()
active_tcp_clients = dict()
encode_params = [int(cv2.IMWRITE_JPEG_QUALITY),20]
mutexUDP = threading.Semaphore(1)
mutexTCP = threading.Semaphore(1)

class UDPClient(Thread):
    def __init__(self, socket, client_address):
        Thread.__init__(self)
        self.mailbox = Queue.Queue()
        self.socket = socket
        self.address = client_address
        self.last_req_time = datetime.now()
        mutexUDP.acquire()
        active_udp_clients[client_address] = self
        mutexUDP.release()

    def run(self):
        while True:
            if (datetime.now() - self.last_req_time > timedelta(seconds = 90)):
                # Check last req time for hanged connections
                break
            frame, sequence_number = self.mailbox.get()
            if isinstance(frame, basestring) and frame == 'shutdown':
                break
            self.socket.sendto(sequence_number + frame, self.address)
        log('Shutting down client on %s:%s' % self.address)
        mutexUDP.acquire()
        del active_udp_clients[self.address]
        mutexUDP.release()

    def feed_frame(self, frame, sequence_number):
        self.mailbox.put((frame, sequence_number))

    def set_last_req_time(self):
        self.last_req_time = datetime.now()

    def stop(self):
        self.mailbox.put("shutdown")

class TCPClient(Thread):
    def __init__(self, socket, client_address):
        Thread.__init__(self)
        self.mailbox = Queue.Queue()
        self.socket = socket
        self.socket.setblocking(1)
        self.address = client_address
        self._stop_event = threading.Event()
        mutexTCP.acquire()
        active_tcp_clients[client_address] = self
        mutexTCP.release()
        new_ender = TCPEnder(socket, self)
        new_ender.start()

    def run(self):
        while True:
            frame = self.mailbox.get()
            if (isinstance(frame, basestring) and frame == 'shutdown') or (self._stop_event.is_set()):
                break
            self.socket.send(frame);
        log('Shutting down client on %s:%s' % self.address)
        self.socket.shutdown(socket.SHUT_WR)
        self.socket.close()

    def feed_frame(self, frame):
        self.mailbox.put(frame)

    def stop(self):
        del active_tcp_clients[self.address]
        self.mailbox.put("shutdown")

    def lost_client(self):
        self._stop_event.set()

class VideoCaster(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.capture = cv2.VideoCapture(0)
        self._stop_event = threading.Event()
        width = self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(640*height/width))
        self.sequence_number = 1;

    def get_sequence_number(self):
        sequence_number = self.sequence_number
        self.sequence_number += 1
        return "%06d" % (sequence_number,)

    def run(self):
        while True:
            if self._stop_event.is_set():
                self.capture.release()
                break
            capture_success, frame = self.capture.read()
            if capture_success:
                encode_success, encoded_frame = cv2.imencode('.jpg', frame, encode_params)
                if encode_success:
                    mutexUDP.acquire()
                    sequence_number = self.get_sequence_number()
                    for address, client in active_udp_clients.iteritems():
                        client.feed_frame(encoded_frame.tostring(), sequence_number)
                    mutexUDP.release()
                    data = numpy.array(encoded_frame)
                    stringData = data.tostring()
                    stringData = re.sub('inicio', 'sustituyendo_palabra', stringData)
                    stringData += 'inicio'
                    mutexTCP.acquire()
                    for address, client in active_tcp_clients.iteritems():
                        client.feed_frame(stringData)
                    mutexTCP.release()

    def stop(self):
        self._stop_event.set()

class UDPListener(Thread):
    def __init__(self, host):
        Thread.__init__(self)
        log('Starting UDP on %s port %s\n' % host)
        self.socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )
        self.socket.bind(host)
        self.socket.settimeout(1)
        self._stop_event = threading.Event()

    def run(self):
        log('Waiting to receive UDP client request...')
        while True:
            try:
                data, address = self.socket.recvfrom(4096)
                if (active_udp_clients.has_key(address)):
                    log('Received a refresh request from %s on port %s' % address)
                    active_udp_clients[address].set_last_req_time()
                else:
                    log('Received a UDP connection request from %s on port %s' % address)
                    new_client = UDPClient(self.socket, address)
                    new_client.start()
            except:
                if self._stop_event.is_set():
                    not_empty = True
                    while not_empty:
                        mutexUDP.acquire()
                        not_empty = bool(active_udp_clients)
                        mutexUDP.release()
                    self.socket.close()
                    break

    def stop(self):
        self._stop_event.set()

class TCPEnder(Thread):
    def __init__(self, socket, client):
        Thread.__init__(self)
        self.socket = socket
        self.client = client

    def run(self):
        data = self.socket.recv(4096)
        if self.client:
            self.client.lost_client()


class TCPListener(Thread):
    def __init__(self, host):
        Thread.__init__(self)
        # log('Strating TCP on %s port %s\n' % host)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, TCP_PORT))
        self.socket.listen(10)
        self.socket.settimeout(1)
        self._stop_event = threading.Event()

    def run(self):
        log('Waiting to receive TCP client request...')
        while True:
            try:
                sc, addr = self.socket.accept()
                new_client = TCPClient(sc, addr)
                new_client.start()
            except:
                if self._stop_event.is_set():
                    not_empty = True
                    while not not_empty:
                        mutexTCP.acquire()
                        not_empty = bool(active_tcp_clients)
                        mutexTCP.release()
                    self.socket.close()
                    break

    def stop(self):
        self._stop_event.set()

def server():
    udp_listener_thread = UDPListener((SERVER_ADDRESS, UDP_PORT))
    udp_listener_thread.start()
    tcp_listener_thread = TCPListener(TCP_HOST)
    tcp_listener_thread.start()

    caster = VideoCaster()
    caster.daemon = True
    caster.start()

    def finish_it_up(a, b):
        udp_listener_thread.stop()
        tcp_listener_thread.stop()
        caster.stop()
        active_udp_clients2 = active_udp_clients.copy()
        for address, client in active_udp_clients2.iteritems():
            client.stop()
            client.join()
        active_tcp_clients2 = active_tcp_clients.copy()
        for address, client in active_tcp_clients2.iteritems():
            client.stop()
            client.join()
        udp_listener_thread.join()
        tcp_listener_thread.join()
        caster.join()
        sys.exit(0)
    signal.signal(signal.SIGINT, finish_it_up)

    while True:
        time.sleep(0.5)

def log(message):
    print >> sys.stderr, '[%s] - %s' % (datetime.now().strftime('%H:%M:%S'), message)

if __name__ == "__main__":
    server()
