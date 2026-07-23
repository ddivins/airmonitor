"""Hot-plug SPS30 particulate logger."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time

from airmonitor.database import connect, init_db, start_sensor_session, end_sensor_session, upsert_sensor
from airmonitor.hardware import DEFAULT_REGISTRY, resolve_device
from airmonitor.health import _package_version
from airmonitor.sensors.sensirion.sps30 import BAUD_RATE, SPS30, SPS30Error

LOG = logging.getLogger("airmonitor.sps30")

SPS30_DDL = """
CREATE TABLE IF NOT EXISTS sps30_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sampled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    sensor_id TEXT NOT NULL REFERENCES sensors(sensor_id),
    session_id INTEGER REFERENCES sensor_sessions(id),
    sensor_port TEXT,
    mass_pm1_0 REAL,
    mass_pm2_5 REAL,
    mass_pm4_0 REAL,
    mass_pm10 REAL,
    number_pm0_5 REAL,
    number_pm1_0 REAL,
    number_pm2_5 REAL,
    number_pm4_0 REAL,
    number_pm10 REAL,
    typical_particle_size REAL,
    frame_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_sps30_samples_sampled_at ON sps30_samples(sampled_at);
CREATE INDEX IF NOT EXISTS idx_sps30_samples_sensor_time ON sps30_samples(sensor_id, sampled_at);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    init_db(conn)
    conn.executescript(SPS30_DDL)
    conn.commit()


def insert_sample(conn: sqlite3.Connection, *, sensor_id: str, session_id: int, port: str, measurement) -> None:
    values = measurement.as_dict()
    conn.execute(
        """
        INSERT INTO sps30_samples (
            sensor_id, session_id, sensor_port,
            mass_pm1_0, mass_pm2_5, mass_pm4_0, mass_pm10,
            number_pm0_5, number_pm1_0, number_pm2_5, number_pm4_0, number_pm10,
            typical_particle_size, frame_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sensor_id, session_id, port,
            values["mass_pm1_0"], values["mass_pm2_5"], values["mass_pm4_0"], values["mass_pm10"],
            values["number_pm0_5"], values["number_pm1_0"], values["number_pm2_5"],
            values["number_pm4_0"], values["number_pm10"], values["typical_particle_size"],
            json.dumps(values, sort_keys=True),
        ),
    )
    conn.commit()


def configured_port(args: argparse.Namespace) -> str:
    if args.port != "auto":
        return args.port
    return resolve_device(args.hardware_id, registry_path=args.registry)


def prepare_measurement(sensor: SPS30, warmup_seconds: float) -> None:
    """Put the SPS30 into a known measurement state.

    A service restart can leave the sensor measuring even though the old process
    has exited. Starting measurement again then returns state 0x43. Stop first,
    tolerate an already-stopped sensor, and then start a fresh measurement run.
    """

    try:
        sensor.stop_measurement()
        LOG.info("Stopped existing SPS30 measurement session")
        time.sleep(0.2)
    except SPS30Error as exc:
        LOG.debug("SPS30 was not in a stoppable measurement state: %s", exc)

    sensor.start_measurement()
    LOG.info("Started SPS30 measurement; warming up for %.1fs", warmup_seconds)
    time.sleep(warmup_seconds)


def run(args: argparse.Namespace) -> int:
    try:
        import serial
    except ImportError:
        print("pyserial is required", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    conn = connect(args.database)
    ensure_schema(conn)
    session_id: int | None = None
    sensor: SPS30 | None = None

    while True:
        try:
            port = configured_port(args)
            if not Path(port).exists():
                raise FileNotFoundError(port)
            with serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=args.timeout,
                write_timeout=args.timeout,
                exclusive=True,
            ) as serial_port:
                sensor = SPS30(serial_port)
                product_type = sensor.product_type()
                upsert_sensor(
                    conn,
                    sensor_id=args.sensor_id,
                    manufacturer="Sensirion",
                    product="SPS30",
                    model=product_type or "SPS30",
                    transport="usb-uart",
                    port=port,
                    serial=args.sensor_serial,
                    location=args.sensor_location,
                )
                session_id = start_sensor_session(
                    conn,
                    sensor_id=args.sensor_id,
                    software_version=_package_version(),
                    sensor_protocol="SHDLC",
                    sensor_port=port,
                )
                prepare_measurement(sensor, args.warmup_seconds)
                LOG.info("SPS30 connected: port=%s product_type=%s session_id=%s", port, product_type, session_id)

                while Path(port).exists():
                    try:
                        measurement = sensor.read_measurement()
                        insert_sample(
                            conn,
                            sensor_id=args.sensor_id,
                            session_id=session_id,
                            port=port,
                            measurement=measurement,
                        )
                        LOG.info(
                            "Logged SPS30 sample: PM1=%0.2f PM2.5=%0.2f PM4=%0.2f PM10=%0.2f ug/m3 size=%0.3f um",
                            measurement.mass_pm1_0,
                            measurement.mass_pm2_5,
                            measurement.mass_pm4_0,
                            measurement.mass_pm10,
                            measurement.typical_particle_size,
                        )
                    except SPS30Error as exc:
                        # Immediately after start the sensor can reject reads until
                        # the first sample is ready. Keep the connection and retry.
                        LOG.warning("SPS30 sample not ready or invalid: %s", exc)
                    time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            LOG.warning("SPS30 unavailable: %s; retrying in %ss", exc, args.retry_seconds)
            time.sleep(args.retry_seconds)
        finally:
            if sensor is not None:
                try:
                    sensor.stop_measurement()
                except Exception:
                    LOG.debug("Unable to stop SPS30 measurement during cleanup", exc_info=True)
                sensor = None
            if session_id is not None:
                try:
                    end_sensor_session(conn, session_id=session_id)
                except Exception:
                    LOG.debug("Unable to end SPS30 session", exc_info=True)
                session_id = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="airmonitor-sps30", description="Log Sensirion SPS30 particulate measurements")
    parser.add_argument("--port", default=os.environ.get("AIRMONITOR_SPS30_PORT", "auto"))
    parser.add_argument("--hardware-id", default=os.environ.get("AIRMONITOR_SPS30_HARDWARE_ID", "sps30-01"))
    parser.add_argument("--registry", default=os.environ.get("AIRMONITOR_HARDWARE_REGISTRY", DEFAULT_REGISTRY))
    parser.add_argument("--sensor-id", default=os.environ.get("AIRMONITOR_SPS30_SENSOR_ID", "sps30-01"))
    parser.add_argument("--sensor-serial", default=os.environ.get("AIRMONITOR_SPS30_SENSOR_SERIAL", "SPS30-01"))
    parser.add_argument("--sensor-location", default=os.environ.get("AIRMONITOR_SPS30_SENSOR_LOCATION") or None)
    parser.add_argument("--database", default=os.environ.get("AIRMONITOR_DATABASE", "/var/lib/airmonitor/airmonitor.sqlite3"))
    parser.add_argument("--interval", type=float, default=float(os.environ.get("AIRMONITOR_SPS30_INTERVAL", "10")))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("AIRMONITOR_SPS30_TIMEOUT", "2")))
    parser.add_argument("--warmup-seconds", type=float, default=float(os.environ.get("AIRMONITOR_SPS30_WARMUP_SECONDS", "2")))
    parser.add_argument("--retry-seconds", type=float, default=float(os.environ.get("AIRMONITOR_SPS30_RETRY_SECONDS", "5")))
    parser.add_argument("--log-level", default=os.environ.get("AIRMONITOR_LOG_LEVEL", "INFO"))
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
