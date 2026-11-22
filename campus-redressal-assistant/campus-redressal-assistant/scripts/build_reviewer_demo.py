"""Compile the campus guidance and actual SQLite directory for public review."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.academic_intake import ISSUES, browser_intake
from src.academic_plan import SOURCE_REVIEW_DATE, academic_plan
from src.stores.campus_directory import browser_directory, load_campus


def export_plans(data: Path) -> dict:
    rules = json.loads((data / "campus_sources.json").read_text(encoding="utf-8"))
    tips = json.loads((data / "campus_senior_tips.json").read_text(encoding="utf-8"))
    plans = {}
    for tag in ISSUES:
        chosen_rules = [{"text": row["text"], "metadata": row} for row in rules if row["subcategory"] == tag]
        chosen_tips = [{"text": row["summary"]} for row in tips if row["subcategory"] == tag]
        for status in ("yes", "no", "unknown") if tag == "escalation" else ("",):
            plans[f"{tag}|{status}"] = academic_plan({
                "subcategory": tag,
                "formal_email_sent": None if status in {"", "unknown"} else status == "yes",
                "retrieved_rules": chosen_rules,
                "retrieved_senior_fundae": chosen_tips,
            })
    return plans


def build(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "app.js", "style.css", "conversation.js", "companion.js", "turn-engine.js", "plan-data.js"):
        shutil.copyfile(ROOT / "web" / name, output / name)
    for name in ("fonts", "assets"):
        shutil.copytree(ROOT / "web" / name, output / name, dirs_exist_ok=True)
    shutil.copytree(ROOT / "deployment" / "vendor", output / "vendor", dirs_exist_ok=True)
    transport = (ROOT / "deployment" / "reviewer_transport.mjs").read_text(encoding="utf-8")
    (output / "transport.js").write_text(transport.replace('"../web/', '"./'), encoding="utf-8")

    data = ROOT / "data"
    load_campus(data / "campus_directory.json", output / "campus-directory.sqlite")
    (output / "sources").mkdir(exist_ok=True)
    shutil.copyfile(data / "campus_senior_tips.json", output / "sources" / "senior-fundae.json")
    payload = {
        **browser_intake(),
        "fallback": academic_plan({}),
        "sourceReviewDate": SOURCE_REVIEW_DATE,
        "plans": export_plans(data),
        "directory": browser_directory(),
    }
    (output / "demo-data.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    build(parser.parse_args().output)
