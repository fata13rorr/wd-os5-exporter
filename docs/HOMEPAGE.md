# Homepage Integration

WD OS5 Exporter was originally created to expose WD My Cloud OS 5 monitoring
information to Homepage.

## Custom API Widget

The `/status` endpoint includes several preformatted fields intended to make
Homepage configuration simple.

Useful fields include:

| Field | Example |
| --- | --- |
| `health_display` | `RAID1 • Healthy` |
| `storage_display` | `3.09 TB / 3.89 TB` |
| `storage_percent_display` | `79%` |
| `free_display` | `802 GB` |
| `temperature_display` | `45° / 46°` |
| `disk1_display` | `45°C` |
| `disk2_display` | `46°C` |
| `smart_display` | `Pass` |
| `raid_display` | `RAID1 • Clean` |
| `cpu_display` | `12%` |
| `ram_display` | `63%` |

Example:

```yaml
- Storage:
    - WD My Cloud:
        icon: wd.png
        description: NAS Health
        widget:
          type: customapi
          url: http://192.168.1.100:8085/status
          mappings:
            - field: health_display
              label: Health
            - field: storage_percent_display
              label: Storage
            - field: temperature_display
              label: Disks
            - field: smart_display
              label: SMART
```

The exporter also exposes raw values so more advanced Homepage configurations
do not need to parse formatted strings.

## Resources Widget

Homepage's Resources widget can monitor a filesystem mounted inside the
Homepage container.

That is separate from WD OS5 Exporter.

The exporter obtains its primary storage information directly from the
My Cloud's `/vols` xmldbc tree and therefore does not require the NAS
filesystem to be mounted on the exporter host.
