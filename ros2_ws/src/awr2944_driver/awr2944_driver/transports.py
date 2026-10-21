"""Bounded UART reads and the PC TCP server required by TI DDM_ENET."""
import ipaddress
import socket
import time

import serial


class UARTStream:
    def __init__(self, path, baud):
        self.port = serial.Serial(port=None, baudrate=baud, timeout=0.1,
                                  write_timeout=1, exclusive=True)
        self.port.dtr, self.port.rts, self.port.port = True, False, path
        try:
            self.port.open()
            self.port.reset_input_buffer()
        except Exception:
            self.port.close()
            raise

    def read(self):
        return self.port.read(min(self.port.in_waiting or 1, 65536))

    def close(self):
        self.port.close()


class TCPServer:
    def __init__(self, host, port=7, radar_ip='192.168.1.200'):
        ipaddress.IPv4Address(host)
        if radar_ip:
            ipaddress.IPv4Address(radar_ip)
        self.peer_ip, self.connection = radar_ip, None
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind((host, port))
            self.listener.listen(2)
            self.listener.settimeout(0.1)
        except PermissionError as exc:
            self.listener.close()
            raise PermissionError('TI firmware uses TCP port 7. Run tools/run_ethernet.sh '
                                  'with its scoped CAP_NET_BIND_SERVICE service; see README.') from exc
        except Exception:
            self.listener.close()
            raise
        self.address = self.listener.getsockname()

    def accept(self, stop_event, timeout):
        deadline = time.monotonic() + timeout
        while not stop_event.is_set():
            if time.monotonic() >= deadline:
                raise TimeoutError('Radar did not connect: check Ethernet firmware, NIC IP, cable and TCP 7 firewall')
            try:
                connection, address = self.listener.accept()
            except socket.timeout:
                continue
            if self.peer_ip and address[0] != self.peer_ip:
                connection.close()
                continue
            self.connection = connection
            connection.settimeout(0.1)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            return True
        return False

    def read(self):
        try:
            chunk = self.connection.recv(65536)
        except socket.timeout:
            return b''
        if not chunk:
            raise ConnectionError('Radar TCP connection closed; TI demo requires a board reset before reconnecting')
        return chunk

    def close(self):
        if self.connection:
            self.connection.close()
        self.listener.close()
