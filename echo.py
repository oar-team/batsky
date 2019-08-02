import os
import socket

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
l = os.listdir('/tmp/batsky')
l.sort()
print(l[-1])
sock.connect('/tmp/batsky/' + l[-1])
# sock.send("m".encode('utf-8'))
a = sock.recv(4)
print(int.from_bytes(a,byteorder='little'))

sec = sock.recv(8)
usec = sock.recv(8)

print("Real time: ", int.from_bytes(sec,byteorder='little'), int.from_bytes(usec,byteorder='little'))

#sock.send((1234).to_bytes(8,byteorder='little'))
#sock.send((1001001).to_bytes(8,byteorder='little'))
sock.send(sec)
sock.send(usec)

#sock.send(a.encode('utf-8'))
#a = sock.recv(1024)
#print(a.decode('utf-8'))
