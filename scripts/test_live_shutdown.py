"""Test a wheel on disposable BDS: stop/restart, then failed-save/crash/recovery.

Requires Endstone, PyMySQL, a disposable MariaDB on loopback, and the scripted
gophertunnel client from endstone-paradox/native/tests/bedrock-client (v2.0.1).
The runner overwrites only a NEW scratch server copied from supplied BDS files.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from zipfile import ZipFile

import pymysql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bds", type=Path, required=True)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--db-port", type=int, required=True)
    args = parser.parse_args()
    server, output = args.server.resolve(), args.output.resolve()
    if "scratch" not in server.parts or server.exists() or output.exists():
        parser.error("Use NEW server and output directories, with the server below scratch")
    root = Path(__file__).resolve().parents[1]
    server.mkdir(parents=True)
    output.mkdir(parents=True)
    for source in args.bds.iterdir():
        if source.name in {"worlds", "plugins", "logs", ".sentry-native", "allowlist.json", "permissions.json"}:
            continue
        if source.is_dir():
            shutil.copytree(source, server / source.name)
        else:
            shutil.copy2(source, server / source.name)
    probe = output / "python"
    probe.mkdir()
    with ZipFile(args.wheel) as wheel:
        for info in wheel.infolist():
            if info.is_dir() or not info.filename.startswith("endstone_inventory_share_plugin/"):
                continue
            target = (probe / info.filename).resolve()
            if not target.is_relative_to(probe):
                raise ValueError("Unsafe wheel member")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wheel.read(info))
    shutil.copy2(root / "tests/live/shutdown_probe.py", probe / "probe_plugin.py")
    for dependency in ("pymysql", "tomlkit"):
        spec = importlib.util.find_spec(dependency)
        shutil.copytree(next(iter(spec.submodule_search_locations)), probe / dependency,
                        ignore=shutil.ignore_patterns("__pycache__"))
    dist = probe / "endstone_invshare_probe-1.0.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: endstone-invshare-probe\nVersion: 1.0.0\n")
    (dist / "entry_points.txt").write_text("[endstone]\ninvshare-probe = probe_plugin:Probe\n")
    (probe / "sitecustomize.py").write_text(
        'import os,sys\nsys.path[:]=[p for p in sys.path if "site-packages" not in p.lower() '
        'or p.lower().startswith(os.environ["INVSHARE_PROBE_PREFIX"].lower())]\n')
    # The client's explicit discovery filter requires these fixture labels.
    (server / "server.properties").write_text(
        "server-name=Paradox acceptance test\nlevel-name=paradox-acceptance\n"
        "server-port=39421\nserver-portv6=39422\nonline-mode=false\nallow-list=false\n"
        "allow-cheats=true\ngamemode=creative\ndifficulty=peaceful\nview-distance=4\n"
        "tick-distance=4\nenable-lan-visibility=true\nemit-server-telemetry=false\n"
        "client-side-chunk-generation-enabled=false\ntransport=nethernet\n")
    (server / "endstone.toml").write_text("[settings]\n")
    (server / "plugins").mkdir(exist_ok=True)
    if os.name != "nt":
        parser.error("This live runner currently supports the supplied Windows BDS fixture")
    from endstone.cli.windows import WindowsBootstrap, PopenWithDll
    boot = WindowsBootstrap(str(server), True, "", False)
    report = {"platform": sys.platform, "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(), "phases": []}
    for index, phase in enumerate(("seed", "restore", "crash", "restore")):
        phase_output = output / f"{index + 1}-{phase}"
        phase_output.mkdir()
        env = boot._endstone_runtime_env.copy()
        env.update(PYTHONPATH=str(probe) + os.pathsep + env["PYTHONPATH"],
                   INVSHARE_PROBE_PREFIX=sys.prefix, PYTHONNOUSERSITE="1",
                   INVSHARE_LIVE_DB_PORT=str(args.db_port), INVSHARE_LIVE_OUTPUT=str(phase_output),
                   INVSHARE_LIVE_PHASE=phase)
        process = PopenWithDll([str(boot.executable_path)], cwd=server, env=env,
                              dll_names=str(boot._endstone_runtime_path), creationflags=subprocess.CREATE_NO_WINDOW,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace")
        lines = []
        def reader():
            for line in process.stdout:
                lines.append(line)
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        client = None
        client_log = (phase_output / "client.log").open("w", encoding="utf-8")
        try:
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline and process.poll() is None:
                if client is None and any("Server started" in line for line in lines):
                    client = subprocess.Popen([str(args.client.resolve()), "-transport", "lan", "-address",
                                               "127.0.0.1:39421", "-names", "InventoryTest", "-duration", "120s"],
                                              stdout=client_log, stderr=subprocess.STDOUT,
                                              creationflags=subprocess.CREATE_NO_WINDOW)
                if (phase_output / "probe.json").exists():
                    break
                time.sleep(0.2)
            result = json.loads((phase_output / "probe.json").read_text())
            assert result["passed"], result
        finally:
            if process.poll() is None:
                if phase == "crash":
                    process.kill()
                else:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                try:
                    process.wait(timeout=40)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if client is not None:
                client.terminate()
                client.wait(timeout=10)
            client_log.close()
            thread.join(timeout=5)
            (phase_output / "server.log").write_text("".join(lines), encoding="utf-8")
        if phase != "crash":
            assert process.returncode == 0, process.returncode
            conn = pymysql.connect(host="127.0.0.1", port=args.db_port, user="root", database="invshare_live")
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT player_inv,player_enderchest,player_xp_level,is_logged_in,session_token FROM player_data")
                    rows = cursor.fetchall()
                expected = json.loads((output / "expected.json").read_text())
                assert len(rows) == 1
                inv, ec, xp, logged_in, token = rows[0]
                assert (json.loads(inv), json.loads(ec), xp) == (expected["inv_json"], expected["ec_json"], expected["xp_level"])
                assert (logged_in, token) == (0, None)
                result["shutdown_database_verified"] = True
            finally:
                conn.close()
        result["server_exit"] = process.returncode
        report["phases"].append(result)
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"Phase {index + 1} {phase}: PASS", flush=True)


if __name__ == "__main__":
    main()
