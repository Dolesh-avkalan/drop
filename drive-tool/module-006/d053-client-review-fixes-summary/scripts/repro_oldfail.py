"""D053: reproduce the D051 primary finding against a given client tree.

Usage: python3 repro_oldfail.py <tree_root>

For each response-body transport failure it calls DriveClient.read() against a
tiny raw loopback server and reports the exception TYPE the client leaked.
On the OLD candidate this leaks raw TimeoutError / IncompleteRead / HTTPException
instead of a safe DriveClientError.
"""
import http.client
import socket
import sys
import threading
import time


def start_raw_server(handler):
    """Start a one-shot raw TCP server; handler(conn) writes the response."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def run():
        try:
            conn, _ = srv.accept()
            try:
                handler(conn)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        except OSError:
            pass
        finally:
            srv.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return port, t


def drain_request(conn):
    conn.settimeout(2.0)
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            if b"\r\n\r\n" in data:
                break
    except OSError:
        pass


def case_stall(conn):
    drain_request(conn)
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n")
    time.sleep(1.5)  # send no body; hold the socket open past the client timeout


def case_truncate(conn):
    drain_request(conn)
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n" + b"abc")


def case_bad_chunk(conn):
    drain_request(conn)
    conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nZZZ\r\n")


def main():
    tree = sys.argv[1]
    sys.path.insert(0, tree)
    from drive_tool.service_client import DriveClient, DriveClientError

    cases = [("stall_body_read", case_stall), ("truncated_body", case_truncate),
             ("malformed_chunk", case_bad_chunk)]
    token = "t" * 40
    for name, handler in cases:
        port, t = start_raw_server(handler)
        client = DriveClient(port=port, token=token, timeout=0.4)
        try:
            client.read("src", "p/a.bin", offset=0, length=262144)
            outcome = "NO-EXCEPTION (unexpected)"
        except DriveClientError as e:
            outcome = f"DriveClientError(code={e.code!r}, uncertain={e.outcome_uncertain}, retry_safe={e.retry_safe})"
        except BaseException as e:  # noqa: BLE001 - we are classifying the leak
            outcome = f"LEAKED {type(e).__module__}.{type(e).__name__}: {e}"
        print(f"{name}: {outcome}")
        t.join(timeout=2.0)


if __name__ == "__main__":
    main()
