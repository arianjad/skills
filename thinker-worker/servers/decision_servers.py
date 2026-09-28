"""Start/stop/status for the CPU decision servers (Kev 8766, Laya 8767). Usage: decision_servers.py start|stop|status"""
import json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = Path.home() / "Code"
REC = Path.home() / ".thinker-worker" / "servers.json"
THREADS = "6"
ENV = {"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": THREADS, "MKL_NUM_THREADS": THREADS,
       "HF_HUB_OFFLINE": "1", "PYTHONUTF8": "1"}
SERVERS = {
    "kev": {"port": 8766, "cwd": CODE / "kev",
            "cmd": [str(CODE / "Local-Agent/local_decisions/.venv-kev/Scripts/python.exe"), "-m", "kev.serve",
                    "--run", "jaredpalmer/kev-0.8b", "--port", "8766"]},
    "laya": {"port": 8767, "cwd": HERE,
             "cmd": [str(CODE / "Local-Agent/local_decisions/.venv/Scripts/python.exe"), str(HERE / "laya_serve.py"),
                     "--port", "8767", "--threads", THREADS]},
}


def models(port):
    try:
        return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2))["models"]
    except Exception:
        return None


def listeners(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    return {int(l.split()[-1]) for l in out.splitlines()
            if "LISTENING" in l and len(l.split()) >= 5 and l.split()[1].endswith(f":{port}")}


def tree_pids(root):
    """root plus all descendants (venv launchers spawn a child python)."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ParentProcessId) $($_.ProcessId)\" }"],
                         capture_output=True, text=True).stdout
    kids = {}
    for l in out.splitlines():
        p = l.split()
        if len(p) == 2:
            kids.setdefault(int(p[0]), []).append(int(p[1]))
    seen, todo = set(), [root]
    while todo:
        x = todo.pop()
        if x not in seen:
            seen.add(x)
            todo += kids.get(x, [])
    return seen


def load():
    return json.loads(REC.read_text()) if REC.exists() else {}


def start():
    rec = load()
    for name, s in SERVERS.items():
        port = s["port"]
        if name in rec and models(port):
            print(f"{name}: already up on {port} (pid {rec[name]['pid']})")
            continue
        taken = listeners(port)
        if taken and not (name in rec and taken <= tree_pids(rec[name]["pid"])):
            sys.exit(f"{name}: port {port} held by pid(s) {sorted(taken)} not in the record; refusing")
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        p = subprocess.Popen(s["cmd"], cwd=s["cwd"], env={**os.environ, **ENV}, creationflags=flags,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rec[name] = {"pid": p.pid, "port": port}
        REC.parent.mkdir(parents=True, exist_ok=True)
        REC.write_text(json.dumps(rec, indent=1))
        t0 = time.time()
        while not models(port):
            if p.poll() is not None or time.time() - t0 > 180:
                sys.exit(f"{name}: did not come up (exit {p.poll()}); run `stop` to clean up")
            time.sleep(1)
        print(f"{name}: up on {port} (pid {p.pid}) in {time.time() - t0:.1f} s")


def status():
    rec = load()
    for name, s in SERVERS.items():
        m = models(s["port"])
        print(f"{name}: {'up' if m else 'down'} port {s['port']} pid {rec.get(name, {}).get('pid')} "
              f"device {m[0].get('device') if m else '-'}")


def stop():
    for name, r in load().items():
        subprocess.run(["taskkill", "/PID", str(r["pid"]), "/T", "/F"], capture_output=True)
        print(f"{name}: stopped pid {r['pid']}")
    REC.unlink(missing_ok=True)


if __name__ == "__main__":
    {"start": start, "stop": stop, "status": status}[sys.argv[1] if len(sys.argv) > 1 else "status"]()
