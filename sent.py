#!/usr/bin/env python3
"""
Smart Campus — dummy telemetry sender.  RUN THIS ON YOUR LAPTOP.

Pretends to be all 31 Arduino nodes at once, publishing exactly what
arduino/smart-campus-node.ino publishes:

  · topic     v1/devices/<TOKEN>/telemetry
  · auth      username = the node's token, password = its own password
  · client id the token (per-node, so the boxes don't evict each other)
  · payload   ONE combined JSON object per cycle with all 32 keys
              (F G H I J K L M N O P Q S T U V W X Y Z
               A1 B1 C1 D1 E1 F1 G1 H1 I1 J1 K1 L1)
  · cadence   one publish per node every 5-8 s

Values are generated the way the sketch derives them — the MQ gas
sensors compute voltage from a 10-bit analogRead, then RS from that
voltage, then Rs/R0 from RS — so the numbers are internally consistent
rather than three unrelated random values.

────────────────────────────────────────────────────────────────
SETUP (once, on your laptop)

  pip install paho-mqtt

  # copy the credentials down from the VM
  scp smcapp@mcssmcapp01.cf.ac.uk:~/Smart-Campus-VM/arduino/node_credentials.json .

────────────────────────────────────────────────────────────────
RUN

  # simplest: tunnel the broker over SSH, then point at localhost
  ssh -L 1883:localhost:1883 c21054458@mcssmcapp01.cf.ac.uk      # leave open
  python send_test_telemetry.py

  # or straight at the VM, if port 1883 is reachable from your network
  python send_test_telemetry.py --host mcssmcapp01.cf.ac.uk --port 1883

  # or the public MQTTS endpoint, once the load balancer forwards properly
  python send_test_telemetry.py --host smart-campus.cs.cf.ac.uk --port 8883 --tls

────────────────────────────────────────────────────────────────
FROM A JUPYTER NOTEBOOK

  import send_test_telemetry as t
  t.run(duration=300)                       # 5 minutes, all 31 nodes
  t.run(host="mcssmcapp01.cf.ac.uk", nodes=5, duration=60)

  Do NOT paste the file's contents into a cell — `__file__` does not
  exist there and argparse will choke on the kernel's own arguments.
  Import it, or run it as a script. (Both are handled if you do paste
  it, but importing is cleaner.)

────────────────────────────────────────────────────────────────
  # a few useful variants
  python send_test_telemetry.py --nodes 5            # only the first 5
  python send_test_telemetry.py --duration 300       # stop after 5 minutes
  python send_test_telemetry.py --five-packets       # the OLD split-packet firmware
  python send_test_telemetry.py --broken-json        # the firmware's unquoted-string bug
"""

import argparse
import json
import math
import pathlib
import random
import signal
import ssl
import sys
import threading
import time
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    raise SystemExit("Missing dependency.  Run:  pip install paho-mqtt")

# __file__ exists only when Python runs a .py FILE. In a Jupyter or
# IPython cell it is undefined, so fall back to the working directory.
try:
    HERE = pathlib.Path(__file__).resolve().parent
except NameError:
    HERE = pathlib.Path.cwd()
DEFAULT_CREDS = HERE / "node_credentials.json"

POLLUTION = ["FreshAir", "Low", "Medium", "High"]

# R0 values the sketch divides by, per MQ sensor (see getdata4/getdata5).
R0 = {"mq2": 0.10, "mq3": 0.02, "mq5": 0.15, "mq9": 0.15}

_stop = threading.Event()
_stats = {
    "sent": 0,
    "failed": 0,
    "connected": 0,
    "refused": 0,
    "errors": {},
    "lock": threading.Lock(),
}


# ── value generation, mirroring the sketch's own arithmetic ──────
def _mq(which):
    """analogRead -> voltage -> RS -> Rs/R0, exactly as the sketch does."""
    raw = random.randint(120, 900)  # 10-bit ADC
    volt = raw / 1024.0 * 5.0
    rs = (5.0 - volt) / volt if volt > 0 else 0.0
    return round(volt, 2), round(rs, 2), round(rs / R0[which], 2)


def build_reading(node_index):
    """One full set of sensor values — all 32 keys the sketch sends."""
    # ── packet 2: loudness, HCHO, air quality ──
    loudness = random.randint(20, 900)
    # The sketch's curve blows up for high ADC readings: ppm =
    # 10^((log10(Rs/34.28) - 0.0827)/-0.4807) with Rs = 1023/adc - 1.
    # ADC 400 already gives ~900 ppm, ADC 900 gives ~145,000. Indoor
    # HCHO is 0.01-0.5 ppm, which the curve reaches at ADC ~8-30.
    hcho_raw = random.randint(8, 30)
    hcho_rs = (1023.0 / hcho_raw) - 1
    # the sketch's curve: ppm = 10 ^ ((log10(Rs/R0) - 0.0827) / -0.4807)
    hcho_ppm = 10 ** ((math.log10(max(hcho_rs / 34.28, 1e-6)) - 0.0827) / -0.4807)

    # ── packet 3: light + particulates (PM rises with a lower index) ──
    lux = random.randint(0, 1800)
    pm1 = random.randint(0, 45)
    pm25 = pm1 + random.randint(0, 40)
    pm10 = pm25 + random.randint(0, 50)

    s2, t2, u2 = _mq("mq2")
    v3, w3, x3 = _mq("mq3")
    y5, z5, a1 = _mq("mq5")
    b1, c1, d1 = _mq("mq9")

    # ── packet 6: O2, multichannel gas, SCD4x ──
    # Slight per-node offsets so the 31 nodes are not identical.
    drift = (node_index % 7) * 0.4
    return {
        "F": loudness,
        "G": round(hcho_rs, 2),
        "H": round(hcho_ppm, 2),
        "I": random.randint(30, 520),
        "J": random.choice(POLLUTION),
        "K": lux,
        "L": pm1,
        "M": pm25,
        "N": pm10,
        "O": pm1 + random.randint(0, 5),
        "P": pm25 + random.randint(0, 5),
        "Q": pm10 + random.randint(0, 5),
        "S": s2,
        "T": t2,
        "U": u2,
        "V": v3,
        "W": w3,
        "X": x3,
        "Y": y5,
        "Z": z5,
        "A1": a1,
        "B1": b1,
        "C1": c1,
        "D1": d1,
        "E1": round(random.uniform(20.4, 21.2), 2),  # O2 %
        "F1": random.randint(0, 90),  # NO2
        "G1": random.randint(0, 120),  # C2H5OH
        "H1": random.randint(0, 150),  # VOC
        "I1": random.randint(0, 200),  # CO
        "J1": random.randint(420, 1600),  # CO2 ppm
        "K1": round(19.0 + drift + random.uniform(-1.5, 4.0), 2),  # temp
        "L1": round(42.0 + drift + random.uniform(-8.0, 18.0), 2),  # humidity
    }


# The sketch's five packets, for --five-packets.
GROUPS = [
    ["F", "G", "H", "I", "J"],
    ["K", "L", "M", "N", "O", "P", "Q"],
    ["S", "T", "U", "V", "W", "X"],
    ["Y", "Z", "A1", "B1", "C1", "D1"],
    ["E1", "F1", "G1", "H1", "I1", "J1", "K1", "L1"],
]


def encode(d, broken_json):
    """Serialise. --broken-json reproduces the firmware's unquoted strings."""
    if not broken_json:
        return json.dumps(d, separators=(",", ":"))
    parts = []
    for k, v in d.items():
        parts.append(f'"{k}":{v}' if not isinstance(v, str) else f'"{k}":{v}')
    return "{" + ",".join(parts) + "}"


def note(kind):
    with _stats["lock"]:
        _stats["errors"][kind] = _stats["errors"].get(kind, 0) + 1


def run_node(idx, token, password, args):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=token)
    client.username_pw_set(token, password)
    if args.tls:
        client.tls_set(cert_reqs=ssl.CERT_NONE if args.insecure else ssl.CERT_REQUIRED)
        if args.insecure:
            client.tls_insecure_set(True)

    def on_connect(c, u, flags, rc, props=None):
        if rc == 0:
            with _stats["lock"]:
                _stats["connected"] += 1
        else:
            with _stats["lock"]:
                _stats["refused"] += 1
            note(f"connect refused rc={rc}")

    client.on_connect = on_connect
    try:
        client.connect(args.host, args.port, keepalive=60)
    except Exception as exc:
        note(f"{type(exc).__name__}: {exc}")
        with _stats["lock"]:
            _stats["failed"] += 1
        return
    client.loop_start()

    topic = f"v1/devices/{token}/telemetry"
    # Stagger the starts so 31 nodes don't all fire on the same instant,
    # which is also how real boxes behave — they boot at different times.
    _stop.wait(random.uniform(0, args.max_interval))

    while not _stop.is_set():
        reading = build_reading(idx)
        payloads = (
            [encode({k: reading[k] for k in g}, args.broken_json) for g in GROUPS]
            if args.five_packets
            else [encode(reading, args.broken_json)]
        )
        for body in payloads:
            if _stop.is_set():
                break
            info = client.publish(topic, body, qos=args.qos)
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                with _stats["lock"]:
                    _stats["sent"] += 1
            else:
                with _stats["lock"]:
                    _stats["failed"] += 1
                note(f"publish rc={info.rc}")
            if args.five_packets:
                _stop.wait(1.5)  # the sketch's gap between packets
        _stop.wait(random.uniform(args.min_interval, args.max_interval))

    client.loop_stop()
    client.disconnect()


def load_credentials(path):
    p = pathlib.Path(path)
    if not p.exists():
        raise SystemExit(
            f"Credentials file not found: {p}\n\n"
            "Copy it down from the VM:\n"
            "  scp smcapp@mcssmcapp01.cf.ac.uk:"
            "~/Smart-Campus-VM/arduino/node_credentials.json .\n"
        )
    data = json.loads(p.read_text())
    nodes = data.get("nodes", data)
    pairs = [(t, v) for t, v in nodes.items() if not t.startswith("_")]
    if not pairs:
        raise SystemExit(f"No credentials in {p}")
    return pairs


def run(
    host="localhost",
    port=1883,
    tls=False,
    insecure=False,
    credentials=None,
    nodes=0,
    duration=0,
    min_interval=5.0,
    max_interval=8.0,
    qos=1,
    five_packets=False,
    broken_json=False,
):
    """
    Call this from a Jupyter notebook instead of the command line:

        import send_test_telemetry as t
        t.run(duration=300)                     # 5 minutes, all nodes
        t.run(host="mcssmcapp01.cf.ac.uk", nodes=5)

    Stop early with the notebook's interrupt button (Kernel > Interrupt).
    """
    return _main(
        argparse.Namespace(
            host=host,
            port=port,
            tls=tls,
            insecure=insecure,
            credentials=credentials or str(DEFAULT_CREDS),
            nodes=nodes,
            duration=duration,
            min_interval=min_interval,
            max_interval=max_interval,
            qos=qos,
            five_packets=five_packets,
            broken_json=broken_json,
        )
    )


def main():
    ap = argparse.ArgumentParser(
        description="Send dummy telemetry as all the Arduino nodes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--host",
        default="localhost",
        help="broker host (default localhost, for an SSH tunnel)",
    )
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--tls", action="store_true", help="use TLS (port 8883)")
    ap.add_argument(
        "--insecure", action="store_true", help="skip TLS certificate verification"
    )
    ap.add_argument("--credentials", default=str(DEFAULT_CREDS))
    ap.add_argument(
        "--nodes", type=int, default=0, help="only the first N nodes (default: all)"
    )
    ap.add_argument(
        "--duration",
        type=int,
        default=0,
        help="stop after N seconds (default: run until Ctrl+C)",
    )
    ap.add_argument("--min-interval", type=float, default=5.0)
    ap.add_argument("--max-interval", type=float, default=8.0)
    ap.add_argument("--qos", type=int, default=1, choices=[0, 1, 2])
    ap.add_argument(
        "--five-packets",
        action="store_true",
        help="split into 5 packets like the ORIGINAL firmware",
    )
    ap.add_argument(
        "--broken-json",
        action="store_true",
        help="unquoted string values, like the unpatched firmware",
    )
    # In a notebook sys.argv is the kernel's own arguments, which
    # argparse would reject. Detect that by looking for the ipykernel
    # module — NOT by pattern-matching argv, because a legitimate
    # "--credentials something.json" also ends in .json and would then
    # be silently discarded along with every other option.
    in_notebook = "ipykernel" in sys.modules
    args = ap.parse_args([] if in_notebook else None)
    return _main(args)


def _main(args):
    # A notebook kernel keeps module state between calls; start clean.
    _stop.clear()
    with _stats["lock"]:
        _stats.update(sent=0, failed=0, connected=0, refused=0, errors={})

    creds = load_credentials(args.credentials)
    if args.nodes:
        creds = creds[: args.nodes]

    print(f"Smart Campus — dummy telemetry")
    print(f"  broker   {args.host}:{args.port} {'TLS' if args.tls else 'plain'}")
    print(f"  nodes    {len(creds)}")
    print(
        f"  cadence  every {args.min_interval:.0f}-{args.max_interval:.0f}s per node"
        f"   ({'5 packets' if args.five_packets else '1 combined packet'}, QoS {args.qos})"
    )
    print(
        f"  expected ~{len(creds)/((args.min_interval+args.max_interval)/2):.1f} msg/s"
    )
    if args.duration:
        print(f"  stopping after {args.duration}s")
    print("  Ctrl+C to stop\n")

    # ── Preflight: TCP first, then a single MQTT connect. This tells
    # you WHICH hop fails instead of watching a failure counter climb.
    import socket

    print("  checking connectivity…")
    try:
        with socket.create_connection((args.host, args.port), timeout=10):
            print(f"    ✓ TCP to {args.host}:{args.port} works")
    except Exception as exc:
        raise SystemExit(
            f"    ✗ cannot open TCP to {args.host}:{args.port} — {exc}\n\n"
            "    Nothing is listening, or a firewall is blocking you.\n"
            "    Try an SSH tunnel instead:\n"
            "      ssh -L 1883:localhost:1883 c21054458@mcssmcapp01.cf.ac.uk\n"
            "      python send_test_telemetry.py            # host defaults to localhost\n"
        )

    probe_tok, probe_pw = creds[0]
    probe = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"preflight-{probe_tok[:6]}"
    )
    probe.username_pw_set(probe_tok, probe_pw)
    if args.tls:
        probe.tls_set(cert_reqs=ssl.CERT_NONE if args.insecure else ssl.CERT_REQUIRED)
        if args.insecure:
            probe.tls_insecure_set(True)
    got = {"rc": None}
    probe.on_connect = lambda c, u, f, rc, props=None: got.__setitem__("rc", rc)
    try:
        probe.connect(args.host, args.port, keepalive=30)
        probe.loop_start()
        for _ in range(100):
            if got["rc"] is not None:
                break
            time.sleep(0.1)
        probe.loop_stop()
        probe.disconnect()
    except Exception as exc:
        raise SystemExit(f"    ✗ MQTT connect raised: {exc}")

    if got["rc"] is None:
        raise SystemExit(
            "    ✗ TCP connected, but the broker never answered the MQTT\n"
            "      handshake (no CONNACK within 10s).\n\n"
            "    The port accepts a connection but something is dropping or\n"
            "    resetting the data — a firewall or load balancer in between,\n"
            "    not the broker itself. Use the SSH tunnel:\n"
            "      ssh -L 1883:localhost:1883 c21054458@mcssmcapp01.cf.ac.uk\n"
            "      python send_test_telemetry.py\n"
        )
    if got["rc"] != 0:
        # paho 2.x hands back a ReasonCode object, not an int — it carries
        # .value and already stringifies to a readable reason.
        rc = got["rc"]
        code = getattr(rc, "value", rc)
        meaning = {
            1: "unacceptable protocol version",
            2: "client id rejected",
            3: "broker unavailable",
            4: "BAD USERNAME OR PASSWORD",
            5: "NOT AUTHORISED — wrong username or password",
        }.get(code, str(rc))
        raise SystemExit(
            f"    ✗ broker refused the connection: rc={code} ({meaning})\n\n"
            "    The network is fine — the broker answered and said no.\n"
            "    Check node_credentials.json matches the broker's users:\n"
            "      ssh c21054458@mcssmcapp01.cf.ac.uk\n"
            "      sudo -u smcapp -s && cd ~/Smart-Campus-VM\n"
            "      ./scripts/mqtt-users.sh list\n"
        )
    print("    ✓ MQTT handshake and authentication OK\n")

    # Only valid on the main thread of a real process; a notebook kernel
    # handles interrupts itself.
    try:
        signal.signal(signal.SIGINT, lambda *_: _stop.set())
    except ValueError:
        pass
    except ValueError:
        pass

    threads = [
        threading.Thread(target=run_node, args=(i, t, p, args), daemon=True)
        for i, (t, p) in enumerate(creds)
    ]
    for t in threads:
        t.start()

    started = time.monotonic()
    try:
        while not _stop.is_set():
            _stop.wait(10)
            with _stats["lock"]:
                sent, failed = _stats["sent"], _stats["failed"]
                conn, ref = _stats["connected"], _stats["refused"]
            el = time.monotonic() - started
            with _stats["lock"]:
                errs = dict(_stats["errors"])
            line = (
                f"  [{datetime.now():%H:%M:%S}] {sent:>6} sent  "
                f"{sent/max(el,1):5.1f} msg/s  "
                f"connected {conn}/{len(creds)}"
                + (f"  refused {ref}" if ref else "")
                + (f"  failed {failed}" if failed else "")
            )
            if errs:  # show the reason as it happens
                top = max(errs.items(), key=lambda x: x[1])
                line += f"   <- {top[0]}"
            print(line)
            if args.duration and el >= args.duration:
                _stop.set()
    except KeyboardInterrupt:
        _stop.set()

    _stop.set()
    for t in threads:
        t.join(timeout=5)

    el = time.monotonic() - started
    print(
        f"\n  Sent {_stats['sent']} message(s) from {len(creds)} node(s) "
        f"in {el:.0f}s ({_stats['sent']/max(el,1):.1f} msg/s)"
    )
    if _stats["errors"]:
        print("\n  Problems:")
        for k, v in sorted(_stats["errors"].items(), key=lambda x: -x[1])[:6]:
            print(f"    {v:>5} x  {k}")
        print("\n  'connect refused rc=5' means bad username/password —")
        print("  check node_credentials.json matches the broker's users.")
    print("\n  Now check the dashboard, or ask Claude to inspect the database.")


if __name__ == "__main__":
    main()
