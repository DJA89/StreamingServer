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
        self.mailbox.put(("shutdown", None))

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
    def __init__(self, is_camera, capture, major_ver):
        Thread.__init__(self)
        self.capture = capture
        self._stop_event = threading.Event()
        self.is_camera = is_camera
        self.old_encoded_frame = ''
        # Find OpenCV version
        self.major_ver = major_ver

        if self.major_ver  < 3 :
            if not self.is_camera:
                self.fps = self.capture.get(cv2.cv.CV_CAP_PROP_FPS)
                print "Frames per second: {0}".format(self.fps)

            width = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH)
            height = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT)
            self.capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, 640)
            self.capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, int(640*height/width))
        else :
            if not self.is_camera:
                self.fps = self.capture.get(cv2.CAP_PROP_FPS)
                print "Frames per second: {0}".format(self.fps)
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
        frame_counter = 0
        if not self.is_camera:
            if self.major_ver < 3 :
                frame_tope = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_COUNT) - 1
            else:
                frame_tope = self.capture.get(cv2.CAP_PROP_FRAME_COUNT) - 1
        while True:
            if self._stop_event.is_set():
                self.capture.release()
                break
            if not self.is_camera:
                time.sleep(1.0/self.fps)

            capture_success, frame = self.capture.read()
            frame_counter += 1
            if (not self.is_camera) and (frame_counter == frame_tope):
                frame_counter = 0
                if self.major_ver  < 3 :
                    self.capture.set(cv2.cv.CV_CAP_PROP_POS_FRAMES, 0)
                else:
                    self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            if capture_success:
                encode_success, encoded_frame = cv2.imencode('.jpg', frame, encode_params)
                if encode_success and not(self.is_camera and self.old_encoded_frame == encoded_frame.tostring()):
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
                        self.old_encoded_frame = encoded_frame.tostring()
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
                    active_udp_clients2 = active_udp_clients.copy()
                    for address, client in active_udp_clients2.iteritems():
                        client.stop()
                        client.join()
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
                    active_tcp_clients2 = active_tcp_clients.copy()
                    for address, client in active_tcp_clients2.iteritems():
                        client.stop()
                        client.join()
                    self.socket.close()
                    break

    def stop(self):
        self._stop_event.set()

def server():
    ip_address_regex = re.compile('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\Z')
    args = sys.argv
    server_address = '127.0.0.1'
    video_source = 0
    for k in args[1:]:
        if ip_address_regex.match(k):
            server_address = k
        else:
            video_source = k
    capture = cv2.VideoCapture(video_source)
    major_ver = int((cv2.__version__).split('.')[0])
    if major_ver  < 3 :
        width = capture.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH)
        if width == 0:
            print 'No se puede leer el origen del video. Por favor pruebe con otra fuente.'
            sys.exit(0)
    else :
        width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        if width == 0:
            print 'No se puede leer el origen del video. Por favor pruebe con otra fuente.'
            sys.exit(0)
    is_camera = video_source == 0
    udp_listener_thread = UDPListener((server_address, UDP_PORT))
    udp_listener_thread.start()
    tcp_listener_thread = TCPListener(TCP_HOST)
    tcp_listener_thread.start()

    caster = VideoCaster(is_camera, capture, major_ver)
    caster.start()

    def finish_it_up(a, b):
        udp_listener_thread.stop()
        tcp_listener_thread.stop()
        udp_listener_thread.join()
        tcp_listener_thread.join()
        caster.stop()
        caster.join()
        sys.exit(0)
    signal.signal(signal.SIGINT, finish_it_up)

    while True:
        time.sleep(0.5)

def log(message):
    print >> sys.stderr, '[%s] - %s' % (datetime.now().strftime('%H:%M:%S'), message)

if __name__ == "__main__":
    server()
