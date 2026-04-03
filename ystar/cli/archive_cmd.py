"""CIEU Archive Command - Permanent Data Preservation"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime
import click

@click.command()
@click.option('--experiment', help='Archive specific experiment (e.g., EXP_001)')
@click.option('--output-dir', default='data/cieu_archive', help='Archive directory')
@click.option('--db-path', default='.ystar_cieu.db', help='CIEU database path')
def archive_cieu(experiment, output_dir, db_path):
    """Archive CIEU database to JSONL format for permanent preservation."""

    db_path = Path(db_path)
    if not db_path.exists():
        click.echo(f"[✗] CIEU database not found: {db_path}")
        return 1

    # Create archive directory
    archive_dir = Path(output_dir)
    if experiment:
        # Experiment-specific archive
        archive_dir = Path('data/experiments')
        archive_file = archive_dir / f"{experiment}_cieu.jsonl"
    else:
        # Regular archive
        archive_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        archive_file = archive_dir / f"{today}.jsonl"

    archive_dir.mkdir(parents=True, exist_ok=True)

    # Read CIEU database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Export all events
    cursor.execute("SELECT * FROM cieu_events ORDER BY created_at")
    events = [dict(row) for row in cursor.fetchall()]

    # Write JSONL (one JSON object per line)
    with open(archive_file, 'w', encoding='utf-8') as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')

    conn.close()

    # Record archive metadata
    meta_file = archive_dir / '.archive_metadata.json'
    metadata = {
        'last_archive': datetime.now().isoformat(),
        'archive_file': str(archive_file),
        'event_count': len(events),
        'experiment': experiment,
    }

    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    click.echo(f"[✓] Archived {len(events)} CIEU events to {archive_file}")
    click.echo(f"[✓] Metadata saved to {meta_file}")

    return 0


def _cmd_archive_cieu(args: list) -> None:
    """
    CLI wrapper for archive_cieu command (for ystar._cli.py integration).
    """
    import sys

    # Parse args manually
    experiment = None
    output_dir = 'data/cieu_archive'
    db_path = '.ystar_cieu.db'

    i = 0
    while i < len(args):
        if args[i] == '--experiment' and i + 1 < len(args):
            experiment = args[i + 1]
            i += 2
        elif args[i] == '--output-dir' and i + 1 < len(args):
            output_dir = args[i + 1]
            i += 2
        elif args[i] == '--db-path' and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        else:
            i += 1

    # Call main function
    db_path_obj = Path(db_path)
    if not db_path_obj.exists():
        print(f"[✗] CIEU database not found: {db_path}")
        sys.exit(1)

    # Create archive directory
    archive_dir = Path(output_dir)
    if experiment:
        # Experiment-specific archive
        archive_dir = Path('data/experiments')
        archive_file = archive_dir / f"{experiment}_cieu.jsonl"
    else:
        # Regular archive
        archive_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        archive_file = archive_dir / f"{today}.jsonl"

    archive_dir.mkdir(parents=True, exist_ok=True)

    # Read CIEU database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Export all events
    cursor.execute("SELECT * FROM cieu_events ORDER BY created_at")
    events = [dict(row) for row in cursor.fetchall()]

    # Write JSONL (one JSON object per line)
    with open(archive_file, 'w', encoding='utf-8') as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')

    conn.close()

    # Record archive metadata
    meta_file = archive_dir / '.archive_metadata.json'
    metadata = {
        'last_archive': datetime.now().isoformat(),
        'archive_file': str(archive_file),
        'event_count': len(events),
        'experiment': experiment,
    }

    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"[✓] Archived {len(events)} CIEU events to {archive_file}")
    print(f"[✓] Metadata saved to {meta_file}")
    print()
