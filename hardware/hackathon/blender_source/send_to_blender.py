"""Send a command to the running Blender through the "MCP for Blender" add-on socket (localhost:9876).

Run with any Python (Blender's bundled one works):
  python send_to_blender.py ping
  python send_to_blender.py run <script.py>      run a script file inside the open Blender session
  python send_to_blender.py code "<python>"      run one snippet
The add-on must be enabled and its server started (N panel > MCP for Blender > Start MCP Server).
"""
import json
import socket
import sys

HOST, PORT = "localhost", 9876


def send(cmd, timeout=600):
    with socket.create_connection((HOST, PORT), timeout=10) as s:
        s.settimeout(timeout)
        s.sendall(json.dumps(cmd).encode("utf-8"))
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                return json.loads(buf.decode("utf-8"))
            except ValueError:
                continue
    return json.loads(buf.decode("utf-8"))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "ping"
    if mode == "ping":
        cmd = {"type": "ping", "params": {}}
    elif mode == "run":
        path = sys.argv[2].replace("\\", "/")
        code = "exec(compile(open(%r, encoding='utf-8').read(), %r, 'exec'), {'__name__': '__main__'})" % (path, path)
        cmd = {"type": "execute_code", "params": {"code": code}}
    else:
        cmd = {"type": "execute_code", "params": {"code": sys.argv[2]}}
    try:
        res = send(cmd)
    except OSError as e:
        print("NOT CONNECTED: %s" % e)
        sys.exit(2)
    if res.get("status") == "success":
        r = res.get("result")
        print(r.get("result", r) if isinstance(r, dict) else r)
    else:
        print("ERROR:", res.get("message"))
        sys.exit(1)


if __name__ == "__main__":
    main()
