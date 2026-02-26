import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOT_FILE = ROOT / "Kosdaqpi_Bot_TR_best.py"
UPLOADER_FILE = ROOT / "dashboard_push_to_vercel.py"


def run_script(path: Path, title: str) -> int:
    print(f"[RUN] {title}: {path}")
    result = subprocess.run([sys.executable, str(path)], cwd=str(ROOT))
    print(f"[DONE] {title}: exit_code={result.returncode}")
    return result.returncode


def main() -> int:
    bot_rc = run_script(BOT_FILE, "Bot")
    if bot_rc != 0:
        print("[SKIP] Bot failed, uploader is not executed.")
        return bot_rc

    if not os.getenv("DASHBOARD_VERCEL_URL") or not os.getenv("DASHBOARD_INGEST_TOKEN"):
        print("[SKIP] DASHBOARD_VERCEL_URL or DASHBOARD_INGEST_TOKEN is not set.")
        return 0

    uploader_rc = run_script(UPLOADER_FILE, "DashboardUploader")
    return uploader_rc


if __name__ == "__main__":
    raise SystemExit(main())
