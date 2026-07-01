#!/usr/bin/env python3
"""Audit GPS Solutions submission readiness for the current manuscript draft."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a GPS Solutions submission-readiness audit.")
    parser.add_argument("--paper", default="paper/main.tex")
    parser.add_argument("--pdf", default="paper/build/main.pdf")
    parser.add_argument("--docx", default="paper/submission/main.docx")
    parser.add_argument("--metrics-tex", default="paper/generated_metrics.tex")
    parser.add_argument("--routes-config", default="datasets/routes.yaml")
    parser.add_argument("--adaptive-dir", default="build/paper_platform/adaptive_experiments")
    parser.add_argument("--time-split-dir", default="build/paper_platform/time_split_experiments")
    parser.add_argument("--output-json", default="build/paper_platform/submission_readiness.json")
    parser.add_argument("--output-md", default="docs/submission_readiness.md")
    return parser.parse_args()


def resolve(path: str | Path) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = PROJECT_ROOT / value
    return value


def strip_comments(text: str) -> str:
    output: list[str] = []
    for line in text.splitlines():
        keep: list[str] = []
        escaped = False
        for char in line:
            if char == "%" and not escaped:
                break
            keep.append(char)
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
        output.append("".join(keep))
    return "\n".join(output)


def latex_to_text(text: str) -> str:
    text = strip_comments(text)
    text = re.sub(r"\\begin\{(?:figure\*?|table\*?)\}.*?\\end\{(?:figure\*?|table\*?)\}", " ", text, flags=re.S)
    text = re.sub(r"\\bibliography\{[^}]*\}", " ", text)
    text = re.sub(r"\\bibliographystyle\{[^}]*\}", " ", text)
    text = re.sub(r"\$.*?\$", " ", text, flags=re.S)
    text = re.sub(r"\\\[(.*?)\\\]", r" \1 ", text, flags=re.S)
    text = re.sub(r"\\\((.*?)\\\)", r" \1 ", text, flags=re.S)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r" \1 ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}_^&]", " ", text)
    text = text.replace("--", " ")
    return re.sub(r"\s+", " ", text).strip()


def count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z0-9'-]*", latex_to_text(text)))


def extract_environment(tex: str, name: str) -> str:
    match = re.search(rf"\\begin\{{{re.escape(name)}\}}(.*?)\\end\{{{re.escape(name)}\}}", tex, flags=re.S)
    return match.group(1).strip() if match else ""


def find_sections(tex: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"\\section\*?\{([^{}]+)\}", tex)]


def read_macros(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    macros: dict[str, str] = {}
    for match in re.finditer(r"\\newcommand\{\\([^{}]+)\}\{([^{}]*)\}", path.read_text(encoding="utf-8")):
        macros[match.group(1)] = match.group(2)
    return macros


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        return list(csv.DictReader(handle))


def pdf_pages(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        result = subprocess.run(["pdfinfo", str(path)], check=True, text=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    return None


def referenced_figures(tex: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^{}]+)\}", tex)]


def figure_path(name: str) -> Path | None:
    candidates = []
    raw = Path(name)
    if raw.suffix:
        candidates.append(PROJECT_ROOT / "paper" / raw)
        candidates.append(PROJECT_ROOT / "paper" / "figures" / raw.name)
    else:
        for suffix in [".pdf", ".eps", ".tif", ".tiff", ".png"]:
            candidates.append(PROJECT_ROOT / "paper" / "figures" / f"{name}{suffix}")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def parse_routes(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"routes": [], "train": [], "test": []}
    routes: list[str] = []
    train: list[str] = []
    test: list[str] = []
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("routes:"):
            section = "routes"
        elif stripped.startswith("train:"):
            section = "train"
        elif stripped.startswith("test:"):
            section = "test"
        elif stripped.startswith("- name:"):
            routes.append(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("- ") and section in {"train", "test"}:
            value = stripped[2:].strip()
            if section == "train":
                train.append(value)
            else:
                test.append(value)
    return {"routes": routes, "train": train, "test": test}


def add_check(
    checks: list[dict[str, str]],
    status: str,
    topic: str,
    detail: str,
    evidence: str = "",
    action: str = "",
) -> None:
    checks.append(
        {
            "status": status,
            "topic": topic,
            "detail": detail,
            "evidence": evidence,
            "action": action,
        }
    )


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    paper_path = resolve(args.paper)
    pdf_path = resolve(args.pdf)
    docx_path = resolve(args.docx)
    metrics_path = resolve(args.metrics_tex)
    routes_path = resolve(args.routes_config)
    adaptive_dir = resolve(args.adaptive_dir)
    time_split_dir = resolve(args.time_split_dir)

    tex = paper_path.read_text(encoding="utf-8") if paper_path.exists() else ""
    macros = read_macros(metrics_path)
    sections = find_sections(tex)
    abstract = extract_environment(tex, "abstract")
    keywords = extract_environment(tex, "IEEEkeywords")
    keyword_items = [item.strip() for item in keywords.replace("\n", " ").split(",") if item.strip()]
    figure_names = referenced_figures(tex)
    resolved_figures = [figure_path(name) for name in figure_names]
    missing_figures = [name for name, path in zip(figure_names, resolved_figures) if path is None]
    figure_suffixes = sorted({path.suffix.lower() for path in resolved_figures if path is not None})
    bbl_path = PROJECT_ROOT / "paper" / "build" / "main.bbl"
    reference_count = 0
    if bbl_path.exists():
        reference_count = len(re.findall(r"\\bibitem", bbl_path.read_text(encoding="utf-8", errors="replace")))

    manuscript_word_count = count_words(tex)
    abstract_word_count = count_words(abstract)
    pages = pdf_pages(pdf_path)
    routes = parse_routes(routes_path)
    route_overlap = sorted(set(routes["train"]) & set(routes["test"]))

    detector_summary = read_csv_rows(adaptive_dir / "detector_summary.csv")
    time_split_summary = read_csv_rows(time_split_dir / "detector_summary.csv")
    time_split_meta = {}
    time_split_meta_path = time_split_dir / "time_split_summary.json"
    if time_split_meta_path.exists():
        time_split_meta = json.loads(time_split_meta_path.read_text(encoding="utf-8"))

    checks: list[dict[str, str]] = []
    if docx_path.exists():
        add_check(checks, "PASS", "Submission file format", "Word manuscript exists.", str(docx_path))
    else:
        add_check(
            checks,
            "BLOCK",
            "Submission file format",
            "GPS Solutions currently requests Word-format submissions; no DOCX manuscript is present.",
            str(docx_path),
            "Prepare paper/submission/main.docx from the accepted manuscript text before submission.",
        )

    document_class = re.search(r"\\documentclass(?:\[[^\]]*\])?\{([^{}]+)\}", tex)
    class_name = document_class.group(1) if document_class else "unknown"
    if class_name.lower().startswith("sn-") or "springer" in class_name.lower():
        add_check(checks, "PASS", "Publisher template", f"LaTeX class appears Springer-compatible: {class_name}.")
    else:
        add_check(
            checks,
            "WARN",
            "Publisher template",
            f"Current draft uses {class_name}; GPS Solutions submission should be converted to the journal Word/Springer format.",
            action="Use the current PDF as the technical draft, then create a Word submission version.",
        )

    if 150 <= abstract_word_count <= 250:
        add_check(checks, "PASS", "Abstract length", f"Abstract has {abstract_word_count} words.")
    else:
        add_check(
            checks,
            "WARN",
            "Abstract length",
            f"Abstract has {abstract_word_count} words; GPS Solutions asks for 150-250 words.",
            action="Shorten or expand the abstract before submission.",
        )

    if 3 <= len(keyword_items) <= 5:
        add_check(checks, "PASS", "Keywords", f"{len(keyword_items)} keywords are present.")
    else:
        add_check(checks, "WARN", "Keywords", f"{len(keyword_items)} keywords found.", action="Use 3-5 journal keywords.")

    if 5000 <= manuscript_word_count <= 5500:
        add_check(checks, "PASS", "Regular paper length", f"Approximate manuscript word count is {manuscript_word_count}.")
    else:
        add_check(
            checks,
            "WARN",
            "Regular paper length",
            f"Approximate manuscript word count is {manuscript_word_count}; journal guidance targets about 5000-5500 words.",
            action="Tune length after final Word conversion.",
        )

    if pages is not None:
        add_check(checks, "PASS", "PDF build", f"Compiled PDF exists with {pages} pages.", str(pdf_path))
    else:
        add_check(checks, "BLOCK", "PDF build", "Compiled PDF is missing or pdfinfo is unavailable.", str(pdf_path))

    required_sections = ["Introduction", "Related Work", "Method", "Experiments", "Discussion", "Limitations", "Conclusion"]
    missing_sections = [section for section in required_sections if section not in sections]
    if not missing_sections:
        add_check(checks, "PASS", "Core manuscript sections", "All core method-paper sections are present.")
    else:
        add_check(checks, "WARN", "Core manuscript sections", f"Missing sections: {', '.join(missing_sections)}.")

    declaration_terms = [
        "Funding",
        "Competing interests",
        "Author contributions",
        "Data availability",
        "Code availability",
        "Ethics approval",
        "Use of AI tools",
    ]
    missing_declarations = [term for term in declaration_terms if term.lower() not in tex.lower()]
    if not missing_declarations:
        add_check(checks, "PASS", "Statements and declarations", "Funding, competing interests, data/code availability, ethics, and AI-tool statements are present.")
    else:
        add_check(checks, "BLOCK", "Statements and declarations", f"Missing: {', '.join(missing_declarations)}.")

    if missing_figures:
        add_check(checks, "BLOCK", "Figure files", f"Missing referenced figures: {', '.join(missing_figures)}.")
    else:
        add_check(checks, "PASS", "Figure files", f"{len(figure_names)} referenced figures resolve on disk.")

    if figure_suffixes and set(figure_suffixes) <= {".png"}:
        add_check(
            checks,
            "WARN",
            "Final figure formats",
            f"All current figure sources are PNG ({len(figure_names)} figures).",
            action="Prepare EPS/PDF line art or high-resolution TIFF/PNG source files according to final production instructions.",
        )
    elif figure_suffixes:
        add_check(checks, "PASS", "Final figure formats", f"Figure suffixes present: {', '.join(figure_suffixes)}.")

    if reference_count >= 15:
        add_check(checks, "PASS", "Reference coverage", f"{reference_count} bibliography entries in the compiled draft.")
    else:
        add_check(checks, "WARN", "Reference coverage", f"Only {reference_count} bibliography entries detected.")

    if detector_summary:
        add_check(checks, "PASS", "Experiment matrix", f"Adaptive experiment matrix summary has {len(detector_summary)} detector rows.", str(adaptive_dir))
    else:
        add_check(checks, "BLOCK", "Experiment matrix", "Adaptive experiment matrix output is missing.", str(adaptive_dir))

    if time_split_summary and time_split_meta:
        split = time_split_meta.get("split", {})
        add_check(
            checks,
            "PASS",
            "Temporal held-out validation",
            f"Temporal split exists with {int(float(split.get('train_rows', 0)))} calibration rows and {int(float(split.get('test_rows', 0)))} held-out rows.",
            str(time_split_dir),
        )
    else:
        add_check(checks, "WARN", "Temporal held-out validation", "Temporal held-out results are missing.")

    if len(routes["routes"]) >= 2 and not route_overlap:
        add_check(checks, "PASS", "Route-held-out validation", f"Configured train/test routes are disjoint: train={routes['train']}, test={routes['test']}.")
    else:
        add_check(
            checks,
            "SCIENCE_GAP",
            "Route-held-out validation",
            f"Current configured routes are insufficient for independent route-held-out claims: routes={routes['routes']}, overlap={route_overlap}.",
            action="Collect at least one additional clean/degraded route and keep train/test route names disjoint.",
        )

    add_check(
        checks,
        "SCIENCE_GAP",
        "Real spoofing evidence",
        "The current attack evidence is synthetic/observation-level injection, not live RF or replay spoofing.",
        action="Add RF replay or public real-spoofing validation, or explicitly submit as synthetic-observation validation with strong limitations.",
    )

    if macros:
        add_check(
            checks,
            "PASS",
            "Generated metrics",
            f"Generated metrics are present; EA-SGLRT FA/min={macros.get('AdaptiveSeqFalseAlarm', 'n/a')}, temporal held-out FA/min={macros.get('TemporalHoldoutAdaptiveFalseAlarm', 'n/a')}.",
            str(metrics_path),
        )
    else:
        add_check(checks, "BLOCK", "Generated metrics", "paper/generated_metrics.tex is missing.")

    counts: dict[str, int] = {}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    if counts.get("BLOCK", 0):
        overall = "NOT_SUBMISSION_READY"
    elif counts.get("SCIENCE_GAP", 0):
        overall = "ENGINEERING_READY_WITH_SCIENTIFIC_GAPS"
    elif counts.get("WARN", 0):
        overall = "NEAR_READY_WITH_FORMAT_WARNINGS"
    else:
        overall = "READY_FOR_INTERNAL_SUBMISSION_REVIEW"

    return {
        "overall_status": overall,
        "guideline_snapshot": {
            "journal": "GPS Solutions",
            "official_submission_guidelines": "https://link.springer.com/journal/10291/submission-guidelines",
            "official_journal_page": "https://link.springer.com/journal/10291",
            "notes": [
                "The audit is a local readiness helper; journal instructions should be checked again immediately before upload.",
                "The current draft remains a technical PDF/LaTeX draft until a Word submission manuscript is prepared.",
            ],
        },
        "manuscript": {
            "paper": str(paper_path),
            "pdf": str(pdf_path),
            "docx": str(docx_path),
            "document_class": class_name,
            "abstract_words": abstract_word_count,
            "keyword_count": len(keyword_items),
            "approx_word_count": manuscript_word_count,
            "pdf_pages": pages,
            "figure_count": len(figure_names),
            "figure_suffixes": figure_suffixes,
            "reference_count": reference_count,
        },
        "routes": routes,
        "status_counts": counts,
        "checks": checks,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    manuscript = payload["manuscript"]
    lines = [
        "# GPS Solutions Submission Readiness",
        "",
        f"Overall status: `{payload['overall_status']}`",
        "",
        "Official pages to re-check before upload:",
        "",
        f"- GPS Solutions submission guidelines: {payload['guideline_snapshot']['official_submission_guidelines']}",
        f"- GPS Solutions journal page: {payload['guideline_snapshot']['official_journal_page']}",
        "",
        "## Manuscript Snapshot",
        "",
        f"- LaTeX class: `{manuscript['document_class']}`",
        f"- Approximate word count: {manuscript['approx_word_count']}",
        f"- Abstract words: {manuscript['abstract_words']}",
        f"- Keywords: {manuscript['keyword_count']}",
        f"- PDF pages: {manuscript['pdf_pages']}",
        f"- Referenced figures: {manuscript['figure_count']} ({', '.join(manuscript['figure_suffixes']) or 'n/a'})",
        f"- Compiled references: {manuscript['reference_count']}",
        "",
        "## Audit Checks",
        "",
        "| Status | Topic | Detail | Action |",
        "| --- | --- | --- | --- |",
    ]
    for check in payload["checks"]:
        action = check.get("action", "")
        detail = str(check["detail"]).replace("|", "\\|")
        action = action.replace("|", "\\|")
        lines.append(f"| {check['status']} | {check['topic']} | {detail} | {action} |")
    lines.extend(
        [
            "",
            "## Highest-Priority Remaining Work",
            "",
            "1. Prepare the Word-format submission manuscript and final publisher-style title page.",
            "2. Add at least one independent clean/degraded route for true route-held-out validation.",
            "3. Add real RF replay/spoofing evidence or explicitly position the contribution as observation-level synthetic validation.",
            "4. Prepare final production figures and confirm journal formatting immediately before upload.",
            "",
            "## Reproducibility Commands",
            "",
            "```bash",
            "cmake -S . -B build",
            "cmake --build build --target paper_pdf",
            "cmake --build build --target paper_submission_audit",
            "ctest --test-dir build --output-on-failure",
            "```",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    payload = build_audit(args)
    write_json(resolve(args.output_json), payload)
    write_markdown(resolve(args.output_md), payload)
    print("Submission readiness audit complete")
    print(f"  status: {payload['overall_status']}")
    print(f"  json: {resolve(args.output_json)}")
    print(f"  markdown: {resolve(args.output_md)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
