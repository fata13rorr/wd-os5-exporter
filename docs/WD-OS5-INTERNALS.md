# WD My Cloud OS 5 Internals

> These interfaces are undocumented by Western Digital and may change between
> firmware versions or differ between My Cloud models.

This document records the OS5 internals discovered while developing
WD OS5 Exporter.

The initial research was performed on a WD My Cloud EX2 Ultra running
My Cloud OS 5.

## xmldbc

My Cloud OS 5 maintains system information through an internal XML database
accessible using the `xmldbc` utility.

For the system-information database, `xmldbc` communicates with:

```text
/var/run/xmldb_sock_sysinfo
```

Several useful trees were identified:

```text
/disks
/raids
/vols
```

## Querying the Database

The general form used by OS5 is:

```sh
xmldbc -p <tree> <output-file> -S /var/run/xmldb_sock_sysinfo
```

For example:

```sh
xmldbc -p /disks /tmp/disks.xml -S /var/run/xmldb_sock_sysinfo
cat /tmp/disks.xml
```

The exporter performs these queries remotely over SSH and parses the
resulting XML.

## Disk Information

Query:

```sh
xmldbc -p /disks /tmp/disks.xml -S /var/run/xmldb_sock_sysinfo
```

The `/disks` tree has been observed to provide information including:

- disk identifier
- device path
- model
- serial number
- capacity
- temperature
- health state
- failed state
- over-temperature state
- sleep state
- SMART result

WD OS5 may include a timestamp as part of the SMART result.

## RAID Information

Query:

```sh
xmldbc -p /raids /tmp/raids.xml -S /var/run/xmldb_sock_sysinfo
```

The `/raids` tree has been observed to provide:

- RAID identifier
- md device
- RAID level
- state
- state detail
- array size
- total disk count
- working disk count
- failed disk count
- rebuilding disks
- dirty state

An EX2 Ultra can expose more than one md array. The exporter therefore parses
all RAID entries and selects the largest array when producing the simplified
RAID display.

## Volume Information

Query:

```sh
xmldbc -p /vols /tmp/volumes.xml -S /var/run/xmldb_sock_sysinfo
```

The `/vols` tree has been observed to provide:

- volume name
- mount point
- mounted state
- RAID level
- RAID state
- total capacity
- used capacity
- free capacity
- human-readable capacity values

This is the source WD OS5 Exporter uses for its primary storage-capacity
metrics.

## Web Interface Relationship

During investigation of the OS5 web interface, `raid_cgi.php` was found to
invoke `xmldbc` for disk information and return the resulting XML.

This discovery led to the exporter architecture: rather than emulating the
browser, maintaining a web session, or depending on CGI behavior, the exporter
connects to the NAS over SSH and queries the underlying system-information
database directly.

## Exporter Collection Flow

WD OS5 Exporter currently performs the following during a collection:

```text
SSH connection
    |
    +-- /proc/stat       -> CPU utilization
    |
    +-- /proc/meminfo    -> memory utilization
    |
    +-- xmldbc /disks    -> disks / SMART / temperatures
    |
    +-- xmldbc /raids    -> RAID state
    |
    +-- xmldbc /vols     -> volume capacity / state
```

All remote information is collected during a single SSH session.

Results are cached by the exporter to avoid opening a new SSH session for
every monitoring request.

## Why SSH?

Using SSH has several useful properties:

- no software needs to be installed on the My Cloud
- no WD browser session needs to be maintained
- no CGI authentication needs to be emulated
- key-based authentication can be used
- the exporter itself can run on another Docker host

The exporter is intentionally read-only with respect to NAS management.

## Undocumented Interface Warning

`xmldbc`, its XML schema, and `/var/run/xmldb_sock_sysinfo` are internal OS5
implementation details.

They should not be considered stable public APIs.

Different My Cloud models, OS5 releases, storage configurations, and RAID
configurations may expose different nodes or values.

Compatibility reports from additional OS5 devices are welcome.

When sharing XML for debugging, inspect it first for serial numbers, usernames,
network information, or other identifying information.

## Further Research

Only the trees required for the initial exporter have been documented so far.

Future investigation may reveal additional useful system-information nodes.
New nodes should be verified on real OS5 hardware before being documented as
supported.
