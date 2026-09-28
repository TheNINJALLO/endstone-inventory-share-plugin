"""Real BDS equipment requests before/after inventory restore; new scratch dirs only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from zipfile import ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--expect-rejection", action="store_true", help="Reproduce the old wheel's stale-ID failure")
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or "scratch" not in out.parts:
        parser.error("Use a NEW directory under scratch")
    out.mkdir(parents=True)
    server, probe = out / "server", out / "python"
    server.mkdir()
    probe.mkdir()
    for entry in args.bds.resolve().iterdir():
        if entry.name in {"worlds", "plugins", "logs", ".sentry-native", "server.properties",
                          "endstone.toml", "permissions.json", "allowlist.json"}:
            continue
        target = server / entry.name
        if entry.is_dir():
            if os.name == "nt":
                subprocess.run(["powershell", "-NoProfile", "-Command",
                                "New-Item -ItemType Junction -Path $env:TEST_LINK -Target $env:TEST_TARGET | Out-Null"],
                               env=dict(os.environ, TEST_LINK=str(target), TEST_TARGET=str(entry)), check=True)
            else:
                target.symlink_to(entry, target_is_directory=True)
        else:
            shutil.copy2(entry, target)
    (server / "plugins").mkdir()
    (server / "server.properties").write_text(
        "server-name=Paradox acceptance test\nlevel-name=paradox-acceptance\n"
        "server-port=39431\nserver-portv6=39432\nonline-mode=false\nallow-cheats=true\n"
        "gamemode=survival\ndifficulty=peaceful\nlevel-type=FLAT\nview-distance=4\n"
        "tick-distance=4\nemit-server-telemetry=false\ntransport=nethernet\n")
    (server / "endstone.toml").write_text("[settings]\n")
    with ZipFile(args.wheel) as wheel:
        for info in wheel.infolist():
            if info.is_dir() or not info.filename.startswith("endstone_inventory_share_plugin/"):
                continue
            target = (probe / info.filename).resolve()
            if not target.is_relative_to(probe):
                raise ValueError("Unsafe wheel member")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wheel.read(info))
    root = Path(__file__).resolve().parents[1]
    shutil.copy2(root / "tests/live/equipment_probe.py", probe / "equipment_probe.py")
    dist = probe / "endstone_equipment_probe-1.0.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: endstone-equipment-probe\nVersion: 1.0.0\n")
    (dist / "entry_points.txt").write_text("[endstone]\nequipment-probe = equipment_probe:Probe\n")
    (probe / "sitecustomize.py").write_text(
        'import os,sys\nsys.path[:]=[p for p in sys.path if "site-packages" not in p.lower() '
        'or p.lower().startswith(os.environ["EQUIPMENT_PREFIX"].lower())]\n')
    (out / "control.json").write_text('{"id":0,"action":"wait"}')
    if os.name == "nt":
        from endstone.cli.windows import WindowsBootstrap as Bootstrap, PopenWithDll
        process_class = PopenWithDll
    else:
        from endstone.cli.linux import LinuxBootstrap as Bootstrap
        process_class = subprocess.Popen
    boot = Bootstrap(str(server), True, "", False)
    env = boot._endstone_runtime_env.copy()
    env.update(PYTHONPATH=str(probe) + os.pathsep + env["PYTHONPATH"], PYTHONNOUSERSITE="1",
               EQUIPMENT_PREFIX=sys.prefix, EQUIPMENT_PROBE_OUTPUT=str(out))
    options = {"dll_names": str(boot._endstone_runtime_path), "creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = process_class([str(boot.executable_path)], cwd=server, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", **options)
    lines, events = [], []

    def read_server():
        for line in process.stdout:
            lines.append(line)
    thread = threading.Thread(target=read_server, daemon=True)
    thread.start()
    client = None
    report = {"platform": sys.platform, "python": sys.version.split()[0],
              "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(), "checks": []}

    def snapshot():
        try:
            return json.loads((out / "snapshot.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def wait(predicate, label, timeout=30):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if (out / "error.txt").exists():
                raise AssertionError((out / "error.txt").read_text())
            if predicate():
                return
            if process.poll() is not None:
                break
            time.sleep(.1)
        raise AssertionError(f"Timed out: {label}; snapshot={snapshot()}; server={''.join(lines[-15:])}")

    def send(action, **kwargs):
        client.stdin.write(json.dumps(dict(name="InventoryTest", action=action, **kwargs)) + "\n")
        client.stdin.flush()

    def control(action):
        number = snapshot().get("id", 0) + 1
        temp = out / "control.tmp"
        temp.write_text(json.dumps({"id": number, "action": action}))
        temp.replace(out / "control.json")
        wait(lambda: snapshot().get("id") == number, action)
        time.sleep(.3)  # Let the native tick publish slot changes.

    def slots():
        result = {}
        for event in list(events):
            value, kind = event.get("value"), event.get("event")
            if kind in {"inventory_content", "inventory_slot"}:
                window = value["WindowID"]
                pairs = enumerate(value["Content"]) if kind == "inventory_content" else [(value["Slot"], value["NewItem"])]
                for slot, item in pairs:
                    key = (28 if slot < 9 else 29, slot) if window == 0 else (6, slot) if window == 120 else (34, 1) if window == 119 else None
                    if key:
                        result[key] = item["StackNetworkID"]
            elif kind == "stack_response":
                for response in value["Responses"]:
                    if response["Status"] == 0:
                        for container in response["ContainerInfo"] or []:
                            for slot in container["SlotInfo"]:
                                result[container["Container"]["ContainerID"], slot["Slot"]] = slot["StackNetworkID"]
        return result

    request_id = -1

    def move(source, target, expected=0):
        nonlocal request_id
        current = request_id
        request_id -= 2
        state = slots()
        def info(key):
            return {"Container": {"ContainerID": key[0]}, "Slot": key[1], "StackNetworkID": state.get(key, 0)}
        send("transfer", request_id=current, count=1, source=info(source), destination=info(target))
        def response():
            return next((r for e in list(events) if e.get("event") == "stack_response"
                         for r in e["value"]["Responses"] if r["RequestID"] == current), None)
        wait(lambda: response() is not None, f"request {current}")
        assert response()["Status"] == expected, (source, target, state, response())
        time.sleep(.15)
        return response()

    equipment = [((28, 0), (34, 1)), ((28, 1), (6, 0)), ((28, 3), (6, 1)),
                 ((28, 4), (6, 2)), ((28, 5), (6, 3))]

    def equip():
        for source, target in equipment:
            move(source, target)

    def unequip():
        for source, target in equipment:
            move(target, source)

    try:
        wait(lambda: any("Server started" in line for line in lines), "server start", 120)
        client = subprocess.Popen([str(args.client.resolve()), "-transport", "lan", "-address", "127.0.0.1:39431",
                                   "-names", "InventoryTest", "-duration", "240s"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace",
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        def read_client():
            with (out / "client.log").open("w", encoding="utf-8") as log:
                for line in client.stdout:
                    log.write(line)
                    log.flush()
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        threading.Thread(target=read_client, daemon=True).start()
        wait(lambda: "items" in snapshot() and abs(snapshot()["location"][1]) < 320, "in-world spawn")
        send("inventory_open", count=6)
        wait(lambda: any(e.get("event") == "container_open" for e in events), "native inventory screen")
        control("seed")
        equip()
        unequip()
        report["checks"].append("baseline: totem and all four armor slots equip/unequip with native IDs")
        control("save")
        expected_items = snapshot()["items"]
        control("restore")
        if args.expect_rejection:
            response = move((28, 0), (34, 1), expected=49)
            report["checks"].append(f"old restore reproduced offhand rejection: native status {response['Status']}")
        else:
            equip()
            unequip()
            move((28, 2), (34, 1))
            move((34, 1), (28, 2))
            assert snapshot()["items"] == expected_items
            report["checks"].append("identical restore: full inventory, totem, shield, four armor slots, names and lore preserved")
            equip()
            control("save")
            control("restore")
            unequip()
            equip()
            unequip()
            report["checks"].append("occupied equipment survives restore and remains movable")
            control("save")
            control("scramble")
            control("restore")
            equip()
            unequip()
            assert snapshot()["items"] == expected_items
            report["checks"].append("different local inventory replaced, native client updates allow all equipment actions")
            control("empty")
            assert not any(item.get("type") for item in snapshot()["items"])
            control("seed")
            equip()
            unequip()
            report["checks"].append("empty snapshot clears every slot and subsequent equipment works")
        assert not any(e.get("event") == "packet_violation" for e in events)
    finally:
        if process.poll() is None:
            process.stdin.write("stop\n")
            process.stdin.flush()
            try:
                process.wait(timeout=35)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if client and client.poll() is None:
            client.terminate()
            client.wait(timeout=10)
        thread.join(timeout=5)
        (out / "server.log").write_text("".join(lines), encoding="utf-8")
        report["server_exit"] = process.returncode
        (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    assert process.returncode == 0
    report["passed"] = True
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
