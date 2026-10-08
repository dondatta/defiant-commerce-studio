#!/usr/bin/env python3
"""Create local Compose secrets with Python's standard library (3.10+)."""
import os
from pathlib import Path
import secrets
import sys

def main():
    root = Path(__file__).resolve().parents[1]
    path = root / '.env'
    if path.exists():
        print('.env already exists; left unchanged. See docs/DOCKER.md for the required Docker variables.')
        return
    contents = (root / '.env.docker.example').read_text()
    contents = contents.replace('GENERATE_DJANGO_SECRET', secrets.token_urlsafe(64))
    contents = contents.replace('GENERATE_DATABASE_PASSWORD', secrets.token_urlsafe(32))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print('.env already exists; left unchanged.')
        return
    with os.fdopen(fd, 'w') as file:
        file.write(contents)
    print('Created private .env for local Docker development. No credential values printed.')

if __name__ == '__main__':
    main()
