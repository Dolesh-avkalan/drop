"""D053: probe ACTUAL http.client behavior for duplicate Content-Length/Type.

Static counterexamples may be wrong because http.client/email.message may
combine or reject duplicate headers. This observes the real stdlib behavior.
"""
import http.client
import socket
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
                while b"\r\n\r\n" not in (conn.recv(4096) or b""):
                    pass
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


CASES = {
    "A_dup_CL_2_then_5": b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 5\r\n\r\n{}xyz",
    "B_dup_CL_100_then_2": b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nContent-Length: 2\r\n\r\n{}",
    "C_dup_ContentType": b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Type: text/plain\r\nContent-Length: 3\r\n\r\nabc",
    "D_CL_and_TE": b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nTransfer-Encoding: chunked\r\n\r\nabc",
    "E_dup_XDrive_Offset": b"HTTP/1.1 200 OK\r\nX-Drive-Offset: 0\r\nX-Drive-Offset: 5\r\nContent-Length: 3\r\n\r\nabc",
}

for name, raw in CASES.items():
    port = serve_once(raw)
    print(f"--- {name} ---")
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
        c.request("POST", "/v1/read", body=b"{}")
        r = c.getresponse()
        print("  status:", r.status)
        try:
            print("  getheader('Content-Length'):", repr(r.getheader("Content-Length")))
            print("  get_all('Content-Length'):", r.headers.get_all("Content-Length"))
            print("  getheader('Content-Type'):", repr(r.getheader("Content-Type")))
            print("  get_all('Content-Type'):", r.headers.get_all("Content-Type"))
            print("  get_all('X-Drive-Offset'):", r.headers.get_all("X-Drive-Offset"))
        except Exception as e:  # noqa: BLE001
            print("  header-access raised:", type(e).__name__, e)
        try:
            body = r.read(8)
            print("  read(8):", repr(body))
        except Exception as e:  # noqa: BLE001
            print("  read raised:", type(e).__module__ + "." + type(e).__name__, e)
        c.close()
    except Exception as e:  # noqa: BLE001
        print("  request/getresponse raised:", type(e).__module__ + "." + type(e).__name__, e)
