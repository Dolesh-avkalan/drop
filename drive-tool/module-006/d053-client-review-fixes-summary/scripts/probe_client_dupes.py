"""D053: probe the CLIENT's behavior on duplicate Content-Length/Content-Type.

Uses real raw servers and the client under test (tree passed as argv[1]) so we
can record whether duplicates are already rejected (disconfirmation) or leak.
"""
import socket
import sys
import threading


def serve_once(raw: bytes):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def run():
        try:
            conn, _ = srv.accept()
            conn.settimeout(2.0)
            try:
                buf = b""
                while b"\r\n\r\n" not in buf:
                    buf += conn.recv(4096)
            except OSError:
                pass
            conn.sendall(raw)
            try:
                conn.recv(4096)
            except OSError:
                pass
            conn.close()
        except OSError:
            pass
        finally:
            srv.close()

    threading.Thread(target=run, daemon=True).start()
    return port


READ_HEADERS = (
    b"X-Drive-Offset: 0\r\n"
    b"X-Drive-Observed-Size: 3\r\n"
    b"X-Drive-Observed-Mtime-Ns: 1\r\n"
    b"X-Drive-EOF-Observed: true\r\n"
)

CASES = {
    "dup_CL_2_then_5": b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                       + READ_HEADERS + b"Content-Length: 2\r\nContent-Length: 5\r\n\r\n{}xyz",
    "dup_CL_100_then_2": b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                         + READ_HEADERS + b"Content-Length: 100\r\nContent-Length: 2\r\n\r\n{}",
    "dup_CT_both_octet": b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                         b"Content-Type: application/octet-stream\r\n"
                         + READ_HEADERS + b"Content-Length: 3\r\n\r\nabc",
    "dup_CT_mixed": b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                    b"Content-Type: text/plain\r\n"
                    + READ_HEADERS + b"Content-Length: 3\r\n\r\nabc",
    "single_valid_control": b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                            + READ_HEADERS + b"Content-Length: 3\r\n\r\nabc",
}


def main():
    tree = sys.argv[1]
    sys.path.insert(0, tree)
    from drive_tool.service_client import DriveClient, DriveClientError

    for name, raw in CASES.items():
        port = serve_once(raw)
        client = DriveClient(port=port, token="t" * 40, timeout=1.5)
        try:
            reply = client.read("src", "p/a.bin", offset=0, length=262144)
            outcome = f"ACCEPTED ReadReply(data={reply.data!r}, eof={reply.eof_observed})"
        except DriveClientError as e:
            outcome = f"DriveClientError(code={e.code!r})"
        except BaseException as e:  # noqa: BLE001
            outcome = f"LEAKED {type(e).__module__}.{type(e).__name__}: {e}"
        print(f"{name}: {outcome}")


if __name__ == "__main__":
    main()
