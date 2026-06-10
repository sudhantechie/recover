```
                         ██████╗ ███████╗ ██████╗ ██████╗ ██╗   ██╗███████╗██████╗
                         ██╔══██╗██╔════╝██╔════╝██╔═══██╗██║   ██║██╔════╝██╔══██╗
                         ██████╔╝█████╗  ██║     ██║   ██║██║   ██║█████╗  ██████╔╝
                         ██╔══██╗██╔══╝  ██║     ██║   ██║╚██╗ ██╔╝██╔══╝  ██╔══██╗
                         ██║  ██║███████╗╚██████╗╚██████╔╝ ╚████╔╝ ███████╗██║  ██║
                         ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═════╝   ╚═══╝  ╚══════╝╚═╝  ╚═╝
```

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0-0075ca?style=flat-square" />
  <img src="https://img.shields.io/badge/python-3.6+-0075ca?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/platform-linux%20%7C%20macOS-6f42c1?style=flat-square" />
  <img src="https://img.shields.io/badge/sleuthkit-required-2ea043?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-b08800?style=flat-square" />
</p>

<p align="center">
  <strong>Deleted file recovery from raw disk images via SleuthKit.</strong><br>
  No Python packages. No GUI. Just <code>fls</code>, <code>icat</code>, and a clean terminal.
</p>

---

## Overview

`recover.py` is a command-line forensic tool that scans raw disk images (`.dd`, `.img`) for deleted files and extracts them using [The Sleuth Kit](https://www.sleuthkit.org/). It wraps `fls` and `icat` with a polished interface — colored output, smart filters, dry-run mode, type-mismatch detection, MD5 checksums, and full JSON reports.

---

## Quick start

```bash
# 1. Install the dependency
sudo apt install sleuthkit        # Debian / Ubuntu
brew install sleuthkit            # macOS

# 2. Clone and run
git clone https://github.com/sudhantechie/recover
python recover.py disk.dd
```

---

## Usage examples

```bash
# Basic recovery — everything goes into ./recovered/
python recover.py disk.dd

# Send output somewhere specific and show every step
python recover.py disk.dd -o /tmp/found -v

# Only grab images and PDFs, verify each with a checksum
python recover.py disk.dd --ext jpg jpeg png pdf --checksum

# Preview what would be recovered without touching disk
python recover.py disk.dd --dry-run

# Skip tiny scratch files and save a full JSON report
python recover.py disk.dd --min-size 4096 --report results.json

# Full run
python recover.py disk.dd -o ./out -v --ext jpg png pdf --min-size 1024 --checksum --report run.json --log run.log
```

---

## All flags

| Flag | Description | Default |
|------|-------------|---------|
| `IMAGE` | Path to the raw disk image (e.g. `disk.dd`) | required |
| `-o, --output DIR` | Directory to save recovered files | `./recovered/` |
| `--ext EXT [EXT ...]` | Only recover files with these extensions | all |
| `--min-size BYTES` | Skip files smaller than N bytes | `0` |
| `--max-size BYTES` | Skip files larger than N bytes | none |
| `--types CODE [...]` | Filter by filename type code | `r d` |
| `--meta-types CODE [...]` | Filter by metadata type code | `r d` |
| `--checksum` | Compute MD5 hash for each recovered file | off |
| `--dry-run` | Preview without writing anything to disk | off |
| `--report FILE` | Write a full JSON summary to this file | none |
| `--log FILE` | Write all log output to a file | none |
| `-v, --verbose` | Print every skip and debug message | off |
| `-h, --help` | Show help and exit | — |

---

## Type codes

Used with `--types` and `--meta-types`:

| Code | Meaning |
|------|---------|
| `r` | regular file |
| `d` | deleted file |
| `b` | block device |
| `l` | symbolic link |
| `p` | named FIFO |
| `s` | shadow file |
| `w` | whiteout file |
| `v` | TSK virtual file |

---

## JSON report format

Pass `--report results.json` to get a structured summary of every file:

```json
{
  "image": "disk.dd",
  "output": "./recovered",
  "timestamp": "2025-06-10T14:22:03.441",
  "elapsed_seconds": 4.21,
  "dry_run": false,
  "summary": {
    "recovered": 47,
    "skipped": 12,
    "failed": 1
  },
  "recovered": {
    "documents/report.pdf": {
      "inode": "1024",
      "size_bytes": 145731,
      "md5": "a3f9b2c1d4e5f6a7b8c9d0e1f2a3b4c5"
    }
  },
  "failed": {
    "cache/tmp0.bin": { "inode": "1099" }
  },
  "skipped": {
    "thumbs.db": { "reason": "too small (128 B)" }
  }
}
```

---

## How it works

1. **`fls -r`** recursively walks the image and returns every entry (including deleted ones) with its inode, filename type, and metadata type.
2. Each deleted entry is matched against the active filters (type codes, extensions, size limits).
3. **`icat`** extracts the raw bytes at each matched inode to the output directory, preserving the original relative path.
4. Type mismatches (filename type ≠ metadata type) are flagged — they can indicate an inode was reallocated after deletion.

---

## Dependencies

**No Python packages required.** The only external dependency is The Sleuth Kit.

| Dependency | Provides | Install |
|------------|----------|---------|
| [sleuthkit](https://www.sleuthkit.org/) | `fls`, `icat` | `apt install sleuthkit` / `brew install sleuthkit` |
| Python 3.6+ | runtime | standard library only |
