#!/usr/bin/env python3
"""
netflow-relay: duplicates incoming UDP NetFlow/IPFIX datagrams to multiple
local collectors.

The UniFi Dream Router's NetFlow exporter only supports a single
destination IP:port. This relay lets two independent collectors both
receive the same flow stream:
  - goflow2 (native, listening on 127.0.0.1:2055)
  - netflow2ng (Docker, published on 127.0.0.1:2056 -> container :2055)

The router should be configured to export NetFlow to this relay's
listening port (see LISTEN_PORT below), not directly to 2055 or 2056.
"""
import socket

LISTEN_PORT = 2057
TARGETS = [("127.0.0.1", 2055), ("127.0.0.1", 2056)]


def main():
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.bind(("0.0.0.0", LISTEN_PORT))

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"netflow-relay: listening on 0.0.0.0:{LISTEN_PORT}, "
          f"forwarding to {TARGETS}", flush=True)

    while True:
        try:
            data, addr = recv_sock.recvfrom(65535)
        except OSError as e:
            print(f"netflow-relay: recv error: {e}", flush=True)
            continue

        for target in TARGETS:
            try:
                send_sock.sendto(data, target)
            except OSError as e:
                print(f"netflow-relay: forward to {target} failed: {e}",
                      flush=True)


if __name__ == "__main__":
    main()
