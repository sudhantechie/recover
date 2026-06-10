#!/usr/bin/env python3

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

def _supports_color():
    if not hasattr(sys.stdout, 'isatty'):
        return False
    if not sys.stdout.isatty():
        return False
    if sys.platform == 'win32':
        try:
            import colorama
            colorama.init()
            return True
        except ImportError:
            return False
    return True

USE_COLOR = _supports_color()

def _c(code, text):
    return '\033[%sm%s\033[0m' % (code, text) if USE_COLOR else text

def green(t):   return _c('92', t)
def yellow(t):  return _c('93', t)
def red(t):     return _c('91', t)
def cyan(t):    return _c('96', t)
def bold(t):    return _c('1',  t)
def dim(t):     return _c('2',  t)

BANNER = r"""
  ██████╗ ███████╗ ██████╗ ██████╗ ██╗   ██╗███████╗██████╗
  ██╔══██╗██╔════╝██╔════╝██╔═══██╗██║   ██║██╔════╝██╔══██╗
  ██████╔╝█████╗  ██║     ██║   ██║██║   ██║█████╗  ██████╔╝
  ██╔══██╗██╔══╝  ██║     ██║   ██║╚██╗ ██╔╝██╔══╝  ██╔══██╗
  ██║  ██║███████╗╚██████╗╚██████╔╝ ╚████╔╝ ███████╗██║  ██║
  ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═════╝   ╚═══╝  ╚══════╝╚═╝  ╚═╝
"""

TOOL_NAME    = 'Recover'
TOOL_VERSION = '1.0'
TOOL_AUTHOR  = 'https://github.com/sudhantechie'
TOOL_DESC    = 'Deleted file recovery from raw disk images via SleuthKit'

def print_banner():
    print(cyan(BANNER))
    w = 62
    print(cyan('  ┌' + '─' * w + ' ┐'))
    print(cyan('  │') + bold('  %-*s' % (w - 1, TOOL_NAME + '  v' + TOOL_VERSION)) +  cyan('│'))
    print(cyan('  │') + dim('  %-*s' % (w - 1, TOOL_DESC))                          + cyan('│'))
    print(cyan('  │') + dim('  %-*s' % (w - 1, TOOL_AUTHOR))                        + cyan('│'))
    print(cyan('  └' + '─' * w + ' ┘'))
    print()

TYPEDICT = {
    '-': 'unknown type',
    'r': 'regular file',
    'd': 'deleted file',
    'b': 'block device',
    'l': 'symbolic link',
    'p': 'named FIFO',
    's': 'shadow file',
    'w': 'whiteout file',
    'v': 'TSK virtual file',
}

_TC = ''.join(TYPEDICT.keys())
FLS_LINE_RE = re.compile(
    r'([' + re.escape(_TC) + r'])'
    r'/'
    r'([' + re.escape(_TC) + r'])'
    r'\s+\*\s+'
    r'(\d+(?:-\d+)?)'  # inode, optionally with dash offset
    r':\s+(.*)'
)

class PrettyFormatter(logging.Formatter):
    SYMBOLS = {
        logging.DEBUG:    dim('  ·  '),
        logging.INFO:     '     ',
        logging.WARNING:  yellow(' ⚠   '),
        logging.ERROR:    red('  ✖  '),
        logging.CRITICAL: red('  ✖  '),
    }

    def format(self, record):
        prefix = self.SYMBOLS.get(record.levelno, '     ')
        return prefix + record.getMessage()


class PlainFormatter(logging.Formatter):
    LABELS = {
        logging.DEBUG:    'DEBUG  ',
        logging.INFO:     'INFO   ',
        logging.WARNING:  'WARN   ',
        logging.ERROR:    'ERROR  ',
        logging.CRITICAL: 'FATAL  ',
    }

    def format(self, record):
        ts     = datetime.now().strftime('%H:%M:%S')
        label  = self.LABELS.get(record.levelno, '       ')
        return '%s  %s  %s' % (ts, label, record.getMessage())


def setup_logging(verbose=False, log_file=None):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(PrettyFormatter())
    root.addHandler(console)

    if log_file:
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(PlainFormatter())
        root.addHandler(fh)

def dependency_ok(tool):
    return shutil.which(tool) is not None


def md5_of_file(path, chunk_size=65536):
    """Compute the MD5 hash of a file.  Returns hex string or None on error."""
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(chunk_size), b''):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None

def human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024.0 or unit == 'TB':
            return '%.1f %s' % (n, unit)
        n /= 1024.0


def safe_makedirs(path):
    current = Path(path)
    missing = []
    while not current.exists():
        missing.insert(0, current)
        current = current.parent

    for part in missing:
        if part.exists() and not part.is_dir():
            part.unlink()

    os.makedirs(path, exist_ok=True)


def matches_extensions(filepath, extensions):
    if not extensions:
        return True
    suffix = Path(filepath).suffix.lstrip('.').lower()
    return suffix in {e.lstrip('.').lower() for e in extensions}

def list_deleted_files(imgpath):
    """
    Run fls recursively on the image and return every deleted entry as a
    list of (ftype, mtype, inode, relpath) tuples.
    """
    cmd = ['fls', '-i', 'raw', '-p', '-r', imgpath]
    logging.debug('Running: %s', ' '.join(cmd))

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if result.returncode != 0:
        msg = result.stderr.decode(errors='replace').strip()
        raise RuntimeError(msg or 'fls exited with code %d' % result.returncode)

    entries = []
    for line in result.stdout.decode(errors='replace').splitlines():
        m = FLS_LINE_RE.match(line.strip())
        if m:
            entries.append(m.groups())  # (ftype, mtype, inode, relpath)
    return entries

def extract_inode(imgpath, inode, dest_path):
    cmd = ['icat', '-i', 'raw', '-r', imgpath, str(inode)]
    logging.debug('Running: %s', ' '.join(cmd))

    try:
        with open(dest_path, 'wb') as outfile:
            result = subprocess.run(cmd, stdout=outfile, stderr=subprocess.PIPE)

        if result.returncode != 0:
            err = result.stderr.decode(errors='replace').strip()
            logging.debug('icat error (inode %s): %s', inode, err)
            return False

        return True

    except OSError as exc:
        logging.debug('Could not write to %s: %s', dest_path, exc)
        return False
    
# recovery routine
def recover(
    imgpath,
    outpath,
    verbose     = False,
    dry_run     = False,
    wanted_ftypes = None,
    wanted_mtypes = None,
    extensions  = None,
    min_bytes   = 0,
    max_bytes   = None,
    checksum    = False,
    report_path = None,
    log_file    = None,
):
    print_banner()
    setup_logging(verbose, log_file)
    if not os.path.exists(imgpath):
        logging.error("Can't find the image file: %s", imgpath)
        logging.error('Double-check the path and try again.')
        return

    if not os.access(imgpath, os.R_OK):
        logging.error("No read permission on %s", imgpath)
        logging.error('Try running with sudo, or check the file permissions.')
        return
    
    for tool in ('fls', 'icat'):
        if not dependency_ok(tool):
            logging.error("'%s' wasn't found on your PATH.", tool)
            logging.error(
                'Install The Sleuth Kit:  https://www.sleuthkit.org/  '
                '(apt: sleuthkit / brew: sleuthkit)'
            )
            return
        
    if dry_run:
        logging.info(yellow('Dry-run mode — nothing will be written to disk.'))
    else:
        if os.path.isdir(outpath):
            if not os.access(outpath, os.W_OK):
                logging.error("Output directory isn't writable: %s", outpath)
                return
        else:
            try:
                os.makedirs(outpath)
                logging.info('Created output directory: %s', outpath)
            except OSError as exc:
                logging.error("Couldn't create output directory: %s", exc)
                return

    recover_ftypes = set(wanted_ftypes) if wanted_ftypes else {'r', 'd'}
    recover_mtypes = set(wanted_mtypes) if wanted_mtypes else {'r', 'd'}
    logging.info('Scanning image: %s', bold(imgpath))
    logging.info('Looking for deleted entries …')
    print()

    try:
        entries = list_deleted_files(imgpath)
    except RuntimeError as exc:
        logging.error('fls failed: %s', exc)
        logging.error(
            'Make sure the image is a valid raw disk image, not a compressed '
            'or partitioned container.  Try: file %s', imgpath
        )
        return

    total = len(entries)
    if total == 0:
        logging.info('No deleted entries found in this image.')
        return

    logging.info('Found %s deleted entries.  Starting recovery …', bold(str(total)))
    print()
    success = {}
    failure = {}
    skipped = {}
    start   = datetime.now()

    for ftype, mtype, inode, relpath in entries:
        relpath   = relpath.strip()
        dest_path = os.path.join(outpath, relpath)

        # Directories have no content to recover — skip entirely
        if os.path.isdir(dest_path):
            skipped[relpath] = {'reason': 'is a directory'}
            continue
        
        if ftype not in recover_ftypes or mtype not in recover_mtypes:
            reason = 'type filtered (%s / %s)' % (
                TYPEDICT.get(ftype, ftype), TYPEDICT.get(mtype, mtype))
            skipped[relpath] = {'reason': reason}
            logging.debug('[skip] %s  —  %s', relpath, reason)
            continue


        if not matches_extensions(relpath, extensions):
            skipped[relpath] = {'reason': 'extension not in filter'}
            logging.debug('[skip] %s  —  extension filtered', relpath)
            continue

        if dry_run:
            note = ''
            if ftype != mtype:
                note = yellow('  ⚠  type mismatch (%s vs %s)' % (
                    TYPEDICT.get(ftype), TYPEDICT.get(mtype)))
            logging.info('%s  inode %-8s  %s%s',
                         cyan('[would recover]'), inode, relpath, note)
            success[relpath] = {'inode': inode}
            continue

        dest_dir = os.path.dirname(dest_path)
        try:
            safe_makedirs(dest_dir)
        except OSError as exc:
            logging.warning('%s  %s  —  %s',
                            red('[failed]'), relpath, exc)
            failure[relpath] = {'inode': inode, 'error': str(exc)}
            continue

        ok = extract_inode(imgpath, inode, dest_path)

        if ok:
            file_size = os.path.getsize(dest_path)

            if file_size < min_bytes:
                os.remove(dest_path)
                skipped[relpath] = {
                    'reason': 'too small (%s)' % human_size(file_size)}
                logging.debug('[skip] %s  —  %s', relpath,
                              skipped[relpath]['reason'])
                continue

            if max_bytes is not None and file_size > max_bytes:
                os.remove(dest_path)
                skipped[relpath] = {
                    'reason': 'too large (%s)' % human_size(file_size)}
                logging.debug('[skip] %s  —  %s', relpath,
                              skipped[relpath]['reason'])
                continue

            entry = {'inode': inode, 'size_bytes': file_size}

            if checksum:
                entry['md5'] = md5_of_file(dest_path)

            if ftype != mtype:
                entry['warning'] = (
                    'filename type is %s but metadata says %s — '
                    'the inode may have been reallocated; treat the '
                    'content with caution' % (
                        TYPEDICT.get(ftype, ftype),
                        TYPEDICT.get(mtype, mtype))
                )
                logging.warning('%s  %s',
                                yellow('[type mismatch]'), relpath)
                logging.warning('    %s', dim(entry['warning']))

            success[relpath] = entry

            size_str = dim('(%s)' % human_size(file_size))
            md5_str  = ''
            if checksum:
                md5_str = dim('  md5: %s' % entry['md5'])

            logging.info('%s  inode %-8s  %s  %s%s',
                         green('[recovered]'), inode,
                         relpath, size_str, md5_str)

        else:
            failure[relpath] = {'inode': inode}
            logging.warning('%s  inode %-8s  %s',
                            red('[failed]'), inode, relpath)

    elapsed = (datetime.now() - start).total_seconds()
    divider = cyan('  ' + '═' * 60)
    n_ok    = len(success)
    n_fail  = len(failure)
    n_skip  = len(skipped)

    print()
    print(divider)
    print()
    print(bold('  Recovery complete') + dim('  (%.1f seconds)' % elapsed))
    print()
    print('  %s  %s recovered'  % (green('✔'), bold(str(n_ok))))
    print('  %s  %s skipped'    % (dim('–'),   dim(str(n_skip))))
    print('  %s  %s failed'     % (red('✖'),   bold(str(n_fail)) if n_fail else dim('0')))
    if not dry_run and n_ok:
        print()
        print(dim('  Saved to: ') + bold(outpath))
    print()
    print(divider)

    if n_fail:
        print()
        print(red('  Files that could not be recovered:'))
        for path, info in sorted(failure.items()):
            print('    %s %s  %s' % (red('✖'), path,
                                     dim('(inode %s)' % info.get('inode', '?'))))
        print()

    # JSON fmt
    if report_path:
        report = {
            'image'           : imgpath,
            'output'          : outpath,
            'timestamp'       : datetime.now().isoformat(),
            'elapsed_seconds' : round(elapsed, 2),
            'dry_run'         : dry_run,
            'summary': {
                'recovered' : n_ok,
                'skipped'   : n_skip,
                'failed'    : n_fail,
            },
            'recovered' : success,
            'failed'    : failure,
            'skipped'   : skipped,
        }
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            logging.info('JSON report saved to: %s', bold(report_path))
        except OSError as exc:
            logging.warning("Couldn't write the report file: %s", exc)

USAGE_EXAMPLES = """
examples:
  Basic recovery (everything goes into ./recovered/)
    python recover.py disk.dd

  Send output somewhere specific and show every step
    python recover.py disk.dd -o /tmp/found -v

  Only grab images and PDFs, and verify each one with a checksum
    python recover.py disk.dd --ext jpg jpeg png pdf --checksum

  Preview what would be recovered without touching the disk
    python recover.py disk.dd --dry-run

  Skip tiny scratch files and save a full JSON report
    python recover.py disk.dd --min-size 4096 --report results.json

  Everything at once
    python recover.py disk.dd -o ./out -v --ext jpg png pdf \\
           --min-size 1024 --checksum --report run.json --log run.log
"""

TYPECODES_HELP = (
    'r = regular file  |  d = deleted  |  b = block device  |  '
    'l = symlink  |  p = FIFO  |  s = shadow  |  w = whiteout  |  v = TSK virtual'
)

def build_parser():
    parser = argparse.ArgumentParser(
        prog='recover.py',
        description=bold('recover.py') + '  —  ' + TOOL_DESC if USE_COLOR
                    else 'recover.py  —  ' + TOOL_DESC,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=USAGE_EXAMPLES,
        add_help=False,   # we add our own so it appears at the bottom
    )

    # path
    pos = parser.add_argument_group(cyan('  image') if USE_COLOR else '  image')
    pos.add_argument(
        'image',
        metavar='IMAGE',
        help='Path to the raw disk image  (e.g. disk.dd, dump.img)',
    )

    # output
    out = parser.add_argument_group(cyan('  output') if USE_COLOR else '  output')
    out.add_argument(
        '-o', '--output',
        metavar='DIR',
        default='recovered',
        help='Where to save recovered files  [default: ./recovered/]',
    )
    out.add_argument(
        '--report',
        metavar='FILE',
        default=None,
        help='Write a full JSON summary to this file when done',
    )
    out.add_argument(
        '--log',
        metavar='FILE',
        default=None,
        help='Also write all log output to this file',
    )

    # filetype
    flt = parser.add_argument_group(cyan('  filters') if USE_COLOR else '  filters')
    flt.add_argument(
        '--ext',
        nargs='+',
        metavar='EXT',
        default=None,
        help='Only recover files with these extensions  (e.g. jpg png pdf)',
    )
    flt.add_argument(
        '--min-size',
        metavar='BYTES',
        type=int,
        default=0,
        help='Skip files smaller than N bytes  [default: 0]',
    )
    flt.add_argument(
        '--max-size',
        metavar='BYTES',
        type=int,
        default=None,
        help='Skip files larger than N bytes  [default: no limit]',
    )
    flt.add_argument(
        '--types',
        nargs='+',
        metavar='CODE',
        default=None,
        help='Filter by filename type code  [default: r d]\n' + TYPECODES_HELP,
    )
    flt.add_argument(
        '--meta-types',
        nargs='+',
        metavar='CODE',
        default=None,
        help='Filter by metadata type code  [default: r d]',
    )

    # some useful flags
    flags = parser.add_argument_group(cyan('  options') if USE_COLOR else '  options')
    flags.add_argument(
        '-v', '--verbose',
        action='store_true',
        default=False,
        help='Print every skip and debug message',
    )
    flags.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help="Show what would be recovered without writing anything",
    )
    flags.add_argument(
        '--checksum',
        action='store_true',
        default=False,
        help='Compute and display an MD5 hash for each recovered file',
    )
    flags.add_argument(
        '-h', '--help',
        action='help',
        help='Show this help message and exit',
    )

    return parser


def main():
    parser = build_parser()
    args   = parser.parse_args()

    recover(
        imgpath       = args.image,
        outpath       = args.output,
        verbose       = args.verbose,
        dry_run       = args.dry_run,
        wanted_ftypes = args.types,
        wanted_mtypes = args.meta_types,
        extensions    = args.ext,
        min_bytes     = args.min_size,
        max_bytes     = args.max_size,
        checksum      = args.checksum,
        report_path   = args.report,
        log_file      = args.log,
    )


if __name__ == '__main__':
    main()