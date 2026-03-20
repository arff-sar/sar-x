import argparse
import json
import os

from app import create_app
from scheduler import run_daily_maintenance_job


def run_maintenance_once():
    app = create_app(os.getenv("APP_ENV", "production"))
    result = run_daily_maintenance_job(app)
    print(json.dumps({"job": "daily-maintenance", "result": result}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="SAR-X background job runner")
    parser.add_argument(
        "job",
        choices=["daily-maintenance"],
        help="Çalıştırılacak job ismi",
    )
    args = parser.parse_args()

    if args.job == "daily-maintenance":
        run_maintenance_once()


if __name__ == "__main__":
    main()
