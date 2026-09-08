# WD OS5 Exporter

A lightweight monitoring API for Western Digital My Cloud OS 5 devices.

WD OS5 Exporter connects to a My Cloud over SSH, retrieves system, disk,
RAID, volume, SMART, and temperature information from WD's internal `xmldbc`
database, and exposes it through a simple JSON API.

It was originally created for monitoring a WD My Cloud from
[Homepage](https://gethomepage.dev/), but the API can be consumed by
Home Assistant, Grafana, scripts, or anything else that can read JSON.

## Features

- CPU utilization
- Memory utilization
- Storage usage and free space
- RAID level and state
- RAID failure and rebuild detection
- Overall health state
- Per-disk temperatures
- SMART status
- Disk model and serial information
- Failed-disk detection
- JSON `/status` endpoint
- Lightweight `/health` endpoint
- Built-in caching to reduce SSH polling
- Prebuilt Docker images
- Multi-architecture `linux/amd64` and `linux/arm64` images
- Homepage Custom API integration
- No additional software installed on the NAS
- No WD browser/API authentication required

## Supported Hardware

Initially developed and tested on:

- WD My Cloud EX2 Ultra
- My Cloud OS 5
- Two-disk RAID1 configuration

The underlying OS5 interfaces used by this project are undocumented and may
differ between models or firmware versions.

Reports from other My Cloud OS 5 devices are welcome.

## How It Works

My Cloud OS 5 maintains system information through an internal XML database
accessible with the `xmldbc` utility.

WD OS5 Exporter connects to the NAS over SSH and queries:

```text
/disks
/raids
/vols
```

through the OS5 system-information socket:

```text
/var/run/xmldb_sock_sysinfo
```

It also reads `/proc/stat` and `/proc/meminfo` for CPU and memory statistics.

```text
WD My Cloud OS 5
        |
        | SSH
        v
     xmldbc
        |
        +-- /disks  --> SMART / temperature / disk health
        +-- /raids  --> RAID level / state / rebuild status
        +-- /vols   --> capacity / usage / volume state
        |
        v
 WD OS5 Exporter
        |
        +-- /health
        +-- /status
        |
        +--> Homepage
        +--> Home Assistant
        +--> Grafana
        +--> scripts / other JSON consumers
```

No monitoring software is installed on the My Cloud itself.

## Quick Start

### Requirements

You need:

- a Western Digital My Cloud running OS 5
- SSH enabled on the My Cloud
- SSH key authentication
- Docker with Docker Compose on another machine

### 1. Clone the repository

```sh
git clone https://github.com/fata13rorr/wd-os5-exporter.git
cd wd-os5-exporter
```

### 2. Create your configuration

```sh
cp .env.example .env
```

Edit `.env` for your NAS:

```dotenv
NAS_HOST=192.168.1.100
NAS_PORT=22
NAS_USER=sshd

SSH_KEY=/run/secrets/nas_ssh_key
SSH_KEY_FILE=./id_ed25519

CACHE_SECONDS=15
EXPORTER_PORT=8085

TZ=Etc/UTC
```

`NAS_HOST` should be the IP address or hostname of your My Cloud.

`SSH_KEY_FILE` is the path on the Docker host to the private SSH key that can
log in to the NAS.

`SSH_KEY` is the corresponding path inside the exporter container and normally
does not need to be changed.

### 3. Provide the SSH key

For example, place the private key in the project directory:

```text
wd-os5-exporter/
├── docker-compose.yml
├── .env
└── id_ed25519
```

Make sure the private key has appropriate permissions:

```sh
chmod 600 id_ed25519
```

Never commit the private key to Git.

### 4. Start the exporter

Pull the prebuilt image:

```sh
docker compose pull
```

Start the service:

```sh
docker compose up -d
```

### 5. Test it

```sh
curl http://127.0.0.1:8085/health
```

Expected response:

```json
{
  "service": "wd-os5-exporter",
  "status": "ok"
}
```

Then query the NAS:

```sh
curl http://127.0.0.1:8085/status
```

For formatted output:

```sh
curl -sS http://127.0.0.1:8085/status | python3 -m json.tool
```

## Container Images

Prebuilt images are published to GitHub Container Registry:

```text
ghcr.io/fata13rorr/wd-os5-exporter
```

The default Compose configuration uses:

```text
ghcr.io/fata13rorr/wd-os5-exporter:latest
```

Images are built for:

```text
linux/amd64
linux/arm64
```

This allows the same image to run on typical x86-64 Docker hosts and ARM64
systems such as 64-bit Raspberry Pi installations.

### Version Pinning

For predictable deployments, you can replace `latest` in
`docker-compose.yml` with a specific release:

```yaml
image: ghcr.io/fata13rorr/wd-os5-exporter:0.1.1
```

Release images may also be published with major/minor aliases such as:

```text
0.1
0
```

## API

### `GET /health`

A lightweight exporter health check.

Example:

```json
{
  "service": "wd-os5-exporter",
  "status": "ok"
}
```

This verifies that the exporter web service is running. Use `/status` when you
also need to verify communication with the NAS.

### `GET /status`

Collects monitoring information from the My Cloud and returns JSON.

A shortened example:

```json
{
  "cpu": 12,
  "cpu_display": "12%",
  "ram": 63,
  "ram_display": "63%",
  "storage": 79,
  "storage_display": "3.09 TB / 3.89 TB",
  "storage_free": "802 GB",
  "raid": "RAID1 clean",
  "raid_display": "RAID1 • Clean",
  "health": "Healthy",
  "health_severity": "ok",
  "health_icon": "🟢",
  "health_display": "RAID1 • Healthy",
  "disk1_temp": 45,
  "disk2_temp": 46,
  "temperature_display": "45° / 46°",
  "smart_display": "Pass"
}
```

The full response also contains detailed disk, RAID, and volume structures.

## Health States

The exporter derives an overall health state from disk, SMART, RAID, and
volume information.

| Health | Severity | Meaning |
| --- | --- | --- |
| Healthy | `ok` | No detected disk, RAID, or volume problems |
| Rebuilding | `warning` | RAID rebuild activity detected |
| Attention | `warning` | A condition requires attention |
| Degraded | `critical` | RAID or disk failure detected |
| Offline | `unavailable` | NAS data could not be collected |

The API also supplies a display icon for each state.

## Homepage Integration

WD OS5 Exporter was originally developed for Homepage's Custom API widget.

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

More information is available in:

[`docs/HOMEPAGE.md`](docs/HOMEPAGE.md)

A standalone example is also provided:

[`examples/homepage.yaml`](examples/homepage.yaml)

## Configuration

The exporter reads its configuration from environment variables.

| Variable | Default | Description |
| --- | --- | --- |
| `NAS_HOST` | none | My Cloud hostname or IP address |
| `NAS_PORT` | `22` | SSH port |
| `NAS_USER` | `sshd` | SSH username |
| `SSH_KEY` | `/run/secrets/nas_ssh_key` | Private-key path inside the container |
| `SSH_KEY_FILE` | `./id_ed25519` | Private-key path on the Docker host |
| `CACHE_SECONDS` | `15` | Duration for which collected NAS data is cached |
| `EXPORTER_PORT` | `8085` | Host port for the exporter |
| `TZ` | `Etc/UTC` | Container timezone |

## Security

The `/status` response can contain potentially identifying information,
including disk models and serial numbers.

Do **not** expose WD OS5 Exporter directly to the public Internet.

For remote monitoring, use a VPN or an appropriately authenticated and secured
reverse proxy.

The exporter requires an SSH private key with access to the NAS. Protect this
key as you would any other SSH credential.

The included `.gitignore` excludes common SSH-key filenames and `.env`.

Before publishing logs, `/status` responses, or raw `xmldbc` XML, inspect them
for:

- disk serial numbers
- usernames
- IP addresses
- hostnames
- other identifying information

## Building From Source

Prebuilt GHCR images are recommended for normal use.

To build locally instead:

```sh
git clone https://github.com/fata13rorr/wd-os5-exporter.git
cd wd-os5-exporter

docker build -t wd-os5-exporter:local .
```

You can then run or reference the locally built image using your preferred
Docker configuration.

## Updating

When using `latest`:

```sh
git pull
docker compose pull
docker compose up -d
```

Docker Compose will recreate the container when necessary while retaining your
local `.env` and SSH key.

## WD OS5 Internals

The OS5 interfaces used by this exporter are undocumented.

Development uncovered useful information under the internal `xmldbc` trees:

```text
/disks
/raids
/vols
```

More information about the discovery and collection mechanism is documented
here:

[`docs/WD-OS5-INTERNALS.md`](docs/WD-OS5-INTERNALS.md)

## Troubleshooting

### `/health` works but `/status` fails

This generally means the exporter itself is running but it cannot successfully
collect information from the NAS.

Check:

- `NAS_HOST`
- `NAS_PORT`
- `NAS_USER`
- SSH-key permissions
- whether SSH is enabled on the My Cloud
- whether the Docker host can reach the NAS

Test SSH directly from the Docker host if necessary.

### `docker compose pull` returns `denied`

The GHCR package must be publicly accessible, or Docker must be authenticated
to GitHub Container Registry.

Official releases of this project are intended to use the public package.

### Connection refused on port 8085

Verify the container is running:

```sh
docker compose ps
```

Then inspect its logs:

```sh
docker compose logs wd-os5-exporter
```

## Project Documentation

- [Homepage integration](docs/HOMEPAGE.md)
- [WD My Cloud OS 5 internals](docs/WD-OS5-INTERNALS.md)
- [Homepage example](examples/homepage.yaml)

## Contributing

Compatibility reports for additional WD My Cloud OS 5 models are especially
welcome.

When reporting an issue, include the My Cloud model, OS5 firmware version,
storage configuration, and relevant exporter logs.

Please remove disk serial numbers, private IP addresses, usernames, and other
identifying information before posting diagnostic output.

## Disclaimer

WD OS5 Exporter is an independent open-source project and is not affiliated
with or endorsed by Western Digital.

Western Digital, WD, and My Cloud are trademarks of their respective owners.

The exporter relies on undocumented My Cloud OS 5 internals that may change
between firmware versions. Use at your own risk.

## License

MIT. See [LICENSE](LICENSE).
