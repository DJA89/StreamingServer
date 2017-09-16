import sys
import socket
import cv2
import numpy

UDP_PORT = 10021
# import code; code.interact(local=dict(globals(), **locals()))

def server():
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY),50]
    udp_socket = socket.socket(socket.AF_INET,
    socket.SOCK_DGRAM)
    server_address = ('localhost', UDP_PORT)
    print >>sys.stderr, 'starting up on %s port %s' % server_address
    udp_socket.bind(server_address)
    cap = cv2.VideoCapture(0)
    while True:
        print >>sys.stderr, '\nwaiting to receive message'
        data, address = udp_socket.recvfrom(4096)

        print >>sys.stderr, 'received %s bytes from %s' % (len(data), address)
        print >>sys.stderr, data
        while True:
            ret, frame = cap.read()
            ret, jpeg = cv2.imencode('.jpg', frame, encode_params)
            data = numpy.fromstring(jpeg, dtype='uint8')
            decimg = cv2.imdecode(data, 1)
            if data.any():
                sent = udp_socket.sendto(jpeg, address)
                print >>sys.stderr, 'sent %s bytes back to %s' % (sent, address)

server()
