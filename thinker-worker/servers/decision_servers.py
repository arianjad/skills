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
MARKERS = {"kev": "kev.serve", "laya": "laya_serve.py"}  # live command line must contain this for stop() to kill


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


def proc_info(pid):
    """(creation time, command line) of the live process `pid`, or None if there is none."""
    if os.name == "nt":
        ps = (f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; if ($p) "
              "{ @{c = $p.CreationDate.ToUniversalTime().ToString('o'); l = $p.CommandLine} | ConvertTo-Json -Compress }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
        if not out:
            return None
        d = json.loads(out)
        return d["c"], d["l"] or ""
    proc = Path(f"/proc/{int(pid)}")
    if proc.exists():
        try:
            start = (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]  # field 22: starttime
            return start, (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            return None
    r = subprocess.run(["ps", "-p", str(int(pid)), "-o", "lstart=", "-o", "args="], capture_output=True, text=True)
    line = r.stdout.strip()
    return (line[:24], line[24:].strip()) if r.returncode == 0 and line else None


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
        created, cmdline = proc_info(p.pid) or (None, None)
        rec[name] = {"pid": p.pid, "port": port, "created": created, "cmdline": cmdline}
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
    """Kill a recorded tree only if the live PID is still the process start() launched."""
    rec, failed = load(), False
    for name, r in list(rec.items()):
        live = proc_info(r["pid"])
        marker = MARKERS.get(name)
        if live is None or "created" not in r or live != (r["created"], r["cmdline"]) or not marker or marker not in live[1]:
            print(f"{name}: stale record, not killed (pid {r['pid']})")
            del rec[name]
            continue
        # ponytail: tiny race between the identity check and taskkill; PID reuse inside it is not guarded
        kill = ["taskkill", "/PID", str(r["pid"]), "/T", "/F"] if os.name == "nt" else ["kill", "-9", str(r["pid"])]
        res = subprocess.run(kill, capture_output=True, text=True)
        if res.returncode:
            print(f"{name}: kill of pid {r['pid']} failed (exit {res.returncode}): {(res.stderr or res.stdout).strip()}")
            failed = True
            continue
        print(f"{name}: stopped pid {r['pid']}")
        del rec[name]
    if rec:
        REC.write_text(json.dumps(rec, indent=1))
    else:
        REC.unlink(missing_ok=True)
    if failed:
        sys.exit(1)


def selftest():
    """No real servers. Mocked cases plus one real sleeper this test launches and kills itself."""
    import tempfile
    from unittest import mock
    me = sys.modules[__name__]
    KEV = SERVERS["kev"]["cmd"]
    kev_line = subprocess.list2cmdline(KEV)
    real_run = subprocess.run

    def run_stop(rec, live, taskkill_rc=0):
        """rec: record dict; live: pid -> (created, cmdline) or missing. Returns (taskkills, exit, rec after)."""
        kills = []

        def fake_run(args, **kw):
            if args[0] == "taskkill":
                kills.append(args)
                return subprocess.CompletedProcess(args, taskkill_rc, "", "ERROR: Access denied." if taskkill_rc else "")
            return real_run(args, **kw)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "servers.json"
            path.write_text(json.dumps(rec))
            with mock.patch.object(me, "REC", path), mock.patch.object(me.subprocess, "run", fake_run), \
                    mock.patch.object(me, "proc_info", lambda pid: live.get(pid)):
                code = 0
                try:
                    stop()
                except SystemExit as e:
                    code = e.code or 0
                after = json.loads(path.read_text()) if path.exists() else {}
        return kills, code, after

    good = {"kev": {"pid": 4242, "port": 8766, "created": "T0", "cmdline": kev_line}}
    # 1. matching record -> exactly one taskkill, record cleared
    k, code, after = run_stop(good, {4242: ("T0", kev_line)})
    assert k == [["taskkill", "/PID", "4242", "/T", "/F"]] and code == 0 and after == {}, (k, code, after)
    # 2. Astra finding 1: stale record, PID now another process -> zero taskkill, entry dropped
    for live in ({4242: ("T1", kev_line)},                       # same cmdline, different creation time
                 {4242: ("T0", "C:\\Windows\\notepad.exe")},     # same creation string, different cmdline
                 {}):                                            # process gone
        k, code, after = run_stop(good, live)
        assert k == [] and code == 0 and after == {}, (live, k, code, after)
    # 2b. record from before this fix (no identity fields) -> not killed
    k, code, after = run_stop({"kev": {"pid": 4242, "port": 8766}}, {4242: ("T0", kev_line)})
    assert k == [] and after == {}, (k, after)
    # 2c. identity matches but command line lacks the server marker -> not killed
    k, code, after = run_stop({"kev": {"pid": 4242, "port": 8766, "created": "T0", "cmdline": "python x.py"}},
                              {4242: ("T0", "python x.py")})
    assert k == [] and after == {}, (k, after)
    # 3. taskkill fails -> entry kept, nonzero exit; the other (stale) entry still dropped
    two = {**good, "laya": {"pid": 5151, "port": 8767, "created": "T9", "cmdline": "python laya_serve.py"}}
    k, code, after = run_stop(two, {4242: ("T0", kev_line)}, taskkill_rc=1)
    assert len(k) == 1 and code != 0 and after == {"kev": good["kev"]}, (k, code, after)
    # 4. start() records identity (Popen/network mocked; no server launched)
    fake_p = mock.Mock(pid=4242, poll=lambda: None)
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "servers.json"
        with mock.patch.object(me, "REC", path), mock.patch.object(me.subprocess, "Popen", return_value=fake_p), \
                mock.patch.object(me, "models", side_effect=lambda port: None if not path.exists() else [{}]), \
                mock.patch.object(me, "listeners", return_value=set()), \
                mock.patch.object(me, "SERVERS", {"kev": SERVERS["kev"]}), \
                mock.patch.object(me, "proc_info", lambda pid: ("T0", kev_line)):
            start()
            r = json.loads(path.read_text())["kev"]
    assert r == {"pid": 4242, "port": 8766, "created": "T0", "cmdline": kev_line}, r
    # 5. real process launched here: a python sleeper holding a recorded PID is not killed
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        info = proc_info(sleeper.pid)
        assert info and "time.sleep(60)" in info[1] and proc_info(sleeper.pid) == info, info  # stable identity
        for rec in ({"kev": {"pid": sleeper.pid, "port": 8766, "created": info[0], "cmdline": info[1]}},  # no marker
                    {"kev": {"pid": sleeper.pid, "port": 8766, "created": "stale", "cmdline": kev_line}}):  # reused PID
            kills = []

            def guard_run(args, **kw):
                if args[0] == "taskkill":
                    kills.append(args)
                    return subprocess.CompletedProcess(args, 0, "", "")
                return real_run(args, **kw)

            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "servers.json"
                path.write_text(json.dumps(rec))
                with mock.patch.object(me, "REC", path), mock.patch.object(me.subprocess, "run", guard_run):
                    stop()
            assert kills == [] and sleeper.poll() is None, (kills, sleeper.poll())
    finally:
        sleeper.kill()
        sleeper.wait()
    print("selftest PASS: match->1 taskkill; reused/missing/legacy/no-marker->0; failed taskkill kept+nonzero; "
          "start records identity; real sleeper untouched")


if __name__ == "__main__":
    {"start": start, "stop": stop, "status": status, "--selftest": selftest}[sys.argv[1] if len(sys.argv) > 1 else "status"]()
