"""Bootstrap: migra e popula o banco com resiliencia.

Roda automaticamente como entrypoint do container ou manualmente:
  uv run python scripts/bootstrap.py
"""
import subprocess
import sys
import time

MAX_RETRIES = 5
RETRY_DELAY = 3


def run(cmd: list[str]) -> bool:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"[bootstrap] ERRO: {' '.join(cmd)}")
        print(result.stderr.strip())
        return False
    print(f"[bootstrap] OK: {' '.join(cmd[:2])}")
    return True


def main() -> None:
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"[bootstrap] migration attempt {attempt}/{MAX_RETRIES}")
        if run(["uv", "run", "alembic", "upgrade", "head"]):
            break
        if attempt == MAX_RETRIES:
            print("[bootstrap] FATAL: migration failed after all retries")
            sys.exit(1)
        time.sleep(RETRY_DELAY)

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"[bootstrap] seed attempt {attempt}/{MAX_RETRIES}")
        if run(["uv", "run", "python", "-m", "app.seed"]):
            break
        if attempt == MAX_RETRIES:
            print("[bootstrap] FATAL: seed failed after all retries")
            sys.exit(1)
        time.sleep(RETRY_DELAY * 2)

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"[bootstrap] metadata flags attempt {attempt}/{MAX_RETRIES}")
        if run(["uv", "run", "python", "-c", "from app.seed import apply_metadata_flags; apply_metadata_flags()"]):
            break
        if attempt == MAX_RETRIES:
            print("[bootstrap] FATAL: apply_metadata_flags failed after all retries")
            sys.exit(1)
        time.sleep(RETRY_DELAY)

    print("[bootstrap] pronto — iniciando API")


if __name__ == "__main__":
    main()
