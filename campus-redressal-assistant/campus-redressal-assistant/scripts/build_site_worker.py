"""Package the public Worker from versioned application data and browser assets."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import shutil
import sqlite3
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from build_reviewer_demo import ROOT, export_plans

from src.academic_intake import browser_intake
from src.academic_plan import SOURCE_REVIEW_DATE, academic_plan
from src.chat_model import TurnInterpretation
from src.stores.campus_directory import browser_directory, load_campus


def build(output: Path, bundler: str) -> None:
    server = output / "server"
    server.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as working:
        build_root = Path(working)
        shutil.copytree(ROOT / "web", build_root / "web")
        deployment = build_root / "deployment"
        deployment.mkdir()
        shutil.copyfile(ROOT / "deployment" / "site-worker.js", deployment / "site-worker.js")
        data = ROOT / "data"
        database = build_root / "directory.sqlite"
        load_campus(data / "campus_directory.json", database)
        with sqlite3.connect(database) as connection:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute("SELECT * FROM campus_contacts ORDER BY sort_order")]
        intake = {
            **browser_intake(),
            "departments": [row["department"] for row in rows if row["kind"] == "department" and row["department"] != "General"],
            "fallback": academic_plan({}),
            "plans": export_plans(data),
            "directory": browser_directory(),
            "sourceReviewDate": SOURCE_REVIEW_DATE,
        }
        files = {
            path.relative_to(ROOT / "web").as_posix(): path
            for path in (ROOT / "web").rglob("*")
            if path.is_file() and path.suffix in {".css", ".html", ".woff2", ".webp", ".txt"}
        }
        files.update({name: ROOT / "web" / name for name in ("app.js", "transport.js")})
        files["sources/senior-fundae.json"] = data / "campus_senior_tips.json"
        assets = {
            f"/{name}": {
                "type": "text/javascript; charset=utf-8" if path.suffix == ".js" else mimetypes.guess_type(name)[0],
                "body": base64.b64encode(path.read_bytes()).decode(),
            }
            for name, path in files.items()
        }
        generated = {
            "assets": assets,
            "intake": intake,
            "directoryRows": rows,
            "directoryVersion": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16],
            "schema": TurnInterpretation.model_json_schema(),
        }
        (deployment / "generated-site-data.js").write_text(
            "\n".join(f"export const {key} = {json.dumps(value, ensure_ascii=False)};" for key, value in generated.items()),
            encoding="utf-8",
        )
        subprocess.run(
            [bundler, str(deployment / "site-worker.js"), "--bundle", "--format=esm", "--platform=browser",
             f"--outfile={server / 'index.js'}"],
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--esbuild", default="esbuild")
    args = parser.parse_args()
    build(args.output, args.esbuild)
