# VeSync rate limiting

AirMonitor uses the unofficial `pyvesync` client to control the Levoit purifier through the VeSync cloud. VeSync can temporarily rate-limit an account when a third-party client makes too many requests.

## Observed incident

The VeSync mobile app displayed a message similar to:

```text
Too many requests. Check third-party apps.
```

At the same time:

- the configured VeSync Home disappeared from the app;
- purifier control stopped working in the app;
- `airmonitor-levoit.service` logged `No VeSync devices found`;
- the old service behavior exited and systemd restarted it every ten seconds, increasing request volume.

## Current service behavior

`airmonitor-levoit.service` now runs through a supervisor that keeps the process alive and retries conservatively after VeSync login, discovery, or cloud failures.

Default retry schedule:

```text
60 seconds
120 seconds
300 seconds
900 seconds
3600 seconds
3600 seconds thereafter
```

The schedule can be changed in `/etc/airmonitor/levoit.env`:

```text
LEVOIT_RETRY_BACKOFF_SECONDS=60,120,300,900,3600
```

Values below 60 seconds are rejected to reduce the risk of another restart/request storm.

## Recovery procedure

1. Stop the Levoit service if the VeSync app reports rate limiting:

   ```bash
   sudo systemctl stop airmonitor-levoit.service
   ```

2. Wait for VeSync access to recover. A 24-hour wait is reasonable after an explicit rate-limit warning.
3. Confirm the VeSync mobile app again shows the Home and purifier.
4. Test one manual discovery request:

   ```bash
   sudo /opt/airmonitor/venv/bin/airmonitor-levoit discover
   ```

5. Start the supervised service:

   ```bash
   sudo systemctl start airmonitor-levoit.service
   sudo journalctl -u airmonitor-levoit.service -n 40 --no-pager
   ```

Do not repeatedly run discovery or restart the service while the account is still rate-limited.

## Isolation

A VeSync outage affects only `airmonitor-levoit.service`. SGX logging, SPS30 logging, printer MQTT normalization, Bento control, SQLite, and Grafana continue independently.
