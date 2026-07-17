# Print Report and Data Exports

The provisioned **AirMonitor Print Window** Grafana dashboard includes an
**Export Selected Print** link. It passes the selected Grafana `print_id` to:

```text
https://airmonitor.example.com/exports/print?print_id=<print-id>
```

The page is public and read-only, matching the appliance's anonymous Grafana Viewer
access. Generated files never communicate with sensor, printer, Bento, or Levoit hardware.
They read only the normalized SQLite database.

## Export formats

- Publication PNG: a 3840 by 2160 AirMonitor-branded report graphic
- PDF report: print summary, methodology, graphs, metrics, limitations, and provenance
- Excel workbook: Summary, SGX Samples, SPS30 Samples, Print Metadata, and Filter State
  when historical Levoit samples exist
- Raw CSV ZIP: print metadata, SGX samples, SPS30 samples, metrics, metadata JSON, and
  Levoit samples when present
- Complete experiment ZIP: PNG, PDF, workbook, raw-data ZIP, metadata, and README

The database currently records historical Levoit samples but only the current Bento and
resolved filter-control snapshot. Exports do not fabricate historical Bento state. The
current filter-control snapshot is labeled as generation-time metadata.

## Window and calculations

The export window matches the Print Window dashboard:

```text
start = prints.started_at - 30 minutes
end   = COALESCE(prints.ended_at, prints.last_seen_at) + 30 minutes
```

For an active print, AirMonitor freezes the report at its recorded last-seen time and
labels the result preliminary.

VOC and PM2.5 baselines are the median of valid samples in the 30-minute pre-print
portion. Median is used because it is less sensitive than the mean to short transient
spikes. Peaks are calculated only during the actual print interval. The report also
includes increase above baseline, time from print start to peak, and pre-print/in-print/
post-print sample counts.

If one sensor has no samples, the remaining artifacts are still generated and the missing
dataset is clearly labeled.

## Measurement interpretation

SGX VOC measurements are cross-sensitive total-VOC values intended for relative and
comparative analysis. They do not identify styrene or another individual compound and
must not be compared directly with compound-specific OSHA or NIOSH exposure limits.
AirMonitor is not a certified regulatory, medical, occupational-exposure, or life-safety
instrument.

## Resource and security controls

`airmonitor-export.service` runs separately from data collection and the status page.

- SQLite is opened with `mode=ro` and `PRAGMA query_only=ON`
- `print_id` must be a positive integer
- queries use bound parameters and a per-stream sample limit
- only one artifact is generated at a time
- temporary files use a private service temporary directory and are deleted after transfer
- generated filenames remove path separators and unsafe characters
- the database itself, raw printer JSON, and protocol frame payloads are not downloadable
- the systemd unit applies a memory limit and read-only data-directory access

The nginx download timeout is 180 seconds. A second simultaneous request receives HTTP
429 with a retry hint.

## Dependencies and updates

The Python package installs constrained releases of Matplotlib, openpyxl, and ReportLab.
`tools/update.sh` installs the package dependencies, installs the export systemd unit,
reloads nginx, and restarts the service along with the rest of the AirMonitor appliance.

## Troubleshooting

Check the service and recent logs:

```bash
sudo systemctl status airmonitor-export.service
sudo journalctl -u airmonitor-export.service -n 100 --no-pager
curl -fsS http://127.0.0.1:8081/healthz
```

An invalid or absent print returns a branded error page. An overly large dataset returns
HTTP 413. Concurrent generation returns HTTP 429. Other generation failures return HTTP
500 while sensor collection and automation continue running independently.

Exports are generated in private temporary directories and are removed after the HTTP
response completes. The implementation does not retain a permanent report cache, so disk
growth is limited to SQLite data and normal system logs.
