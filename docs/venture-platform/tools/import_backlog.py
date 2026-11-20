#!/usr/bin/env python3
"""Import this reviewed programme into castlemilk/omega only.

Does not close issues, change assignees, touch runtime code, or enable a product.
Uses stable import markers, dependency order, exact asset hashes and readback.
On an ambiguous create, reconcile once and stop rather than blindly retry.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO = "castlemilk/omega"
BRANCH = "docs/omega-venture-backlog-2026-11-16"
ROOT = Path(__file__).resolve().parents[1]
API = f"https://api.github.com/repos/{REPO}"
SPACE = "https://chatgpt.com/space/"
ATLAS = SPACE + "page_bc328f44577081918e32b04b4daa5d61"
ARCHIVE = SPACE + "page_8242867176f48191938ce84c887d3f31"
INVENTORY = SPACE + "page_d93193af8304819193b45a81d9bd9223"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
MANAGED_START = "<!-- omega-venture-links:start -->"
MANAGED_END = "<!-- omega-venture-links:end -->"
PROGRAMME_MARKER = "<!-- omega-venture-import:programme:2026-11-16 -->"
ASSETS = [
    {"id": "VIS-04", "path": "vis-04-preview.webp", "blob": "478bab4432e78ac6f45afe691a1a74564d926fca", "sha256": "1bf40e6c0be0dee87f2d9f01cca062d11a2914c8e6c2c00e7df6fd8b6c38be23", "bytes": 11142, "width": 640, "height": 360, "original_sha256": "45e98a5df0149c82cd2046aaf5077c3b6e2d8f302e47366304718e1bd5ffe514", "original": "a_cinematic_dark_sci_fi_dashboard_ui_for_omega.png"},
    {"id": "VIS-15", "path": "vis-15-preview.webp", "blob": "f10071cd90aa4a8991f0c2a2e57e3ddf0fa81151", "sha256": "ee673f0954a16a61eba22a805a7e1b766f4a34a11479800c448de4c4d7ba9cc2", "bytes": 14896, "width": 640, "height": 427, "original_sha256": "31f2a0a665c0b5b90284188a0dca450b1e1b776a785a4a3357c5117215bf272e", "original": "a_detailed_sci_fi_themed_ui_dashboard_design_for.png", "transport_repair": ["RvueZ9vGGkg01", "RvueZ9vGkg01"]},
]
last_write = 0.0


def request(method: str, path: str, payload: object | None = None) -> object:
    global last_write
    if not path.startswith("/") or ".." in path:
        raise ValueError("Invalid repository API path")
    if method != "GET":
        time.sleep(max(0, 1.15 - (time.monotonic() - last_write)))
        last_write = time.monotonic()
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {TOKEN}", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "omega-reviewed-backlog-import"}
    data = None if payload is None else json.dumps(payload).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(API + path, data=data, headers=headers, method=method)
    # Writes are never automatically replayed.
    for attempt in range(3 if method == "GET" else 1):
        try:
            with urlopen(req, timeout=45) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            if method == "GET" and exc.code in (502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
        except (URLError, TimeoutError):
            if method == "GET" and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("Read attempts exhausted")


def collection(path: str) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, 51):
        sep = "&" if "?" in path else "?"
        batch = request("GET", f"{path}{sep}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise ValueError("Expected paginated list")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise RuntimeError("Pagination bound exceeded")


def issue_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for issue in collection("/issues?state=all&sort=created&direction=asc"):
        if "pull_request" in issue:
            continue
        matches = re.findall(r"<!-- omega-venture-import:((?:OME-\d{3})|(?:E\d{2})|(?:programme:2026-11-16)) -->", issue.get("body") or "")
        for key in matches:
            if key in index:
                raise RuntimeError(f"Duplicate import marker: {key}")
            index[key] = issue
    return index


def read_specs() -> tuple[dict[str, dict], dict[str, dict], list[str]]:
    epics: dict[str, dict] = {}
    features: dict[str, dict] = {}
    for path in sorted((ROOT / "backlog").glob("e[0-9][0-9]-*.md")):
        text = path.read_text(encoding="utf-8")
        heading = re.search(r"^# (E\d{2}) (.+)$", text, re.M)
        source = re.search(r"^Source: (https://chatgpt.com/space/\S+)$", text, re.M)
        if not heading or not source:
            raise ValueError(f"Missing epic identity/source: {path.name}")
        eid, title = heading.groups()
        if eid in epics:
            raise ValueError(f"Duplicate epic {eid}")
        epics[eid] = {"id": eid, "title": title, "source": source[1], "path": path.relative_to(ROOT.parent.parent).as_posix(), "features": []}
        starts = list(re.finditer(r"^## (OME-\d{3}) (.+)$", text, re.M))
        if len(starts) != 8:
            raise ValueError(f"Expected eight features in {eid}")
        for i, match in enumerate(starts):
            fid, name = match.groups()
            body = text[match.end():starts[i + 1].start() if i + 1 < len(starts) else len(text)].strip()
            body = body.split("\n### ", 1)[0].strip()
            meta = re.search(r"^\*\*(P[0-3][^\n]+)\*\*$", body, re.M)
            if not meta or not all(f"**{field}:**" in body for field in ("Acceptance", "Screens", "Evidence")):
                raise ValueError(f"Incomplete specification: {fid}")
            deps_part = meta[1].split("Dependencies:", 1)[-1]
            deps = re.findall(r"OME-\d{3}", deps_part)
            if fid in features:
                raise ValueError(f"Duplicate feature {fid}")
            features[fid] = {"id": fid, "title": name, "body": body, "priority": meta[1][:2], "deps": deps, "epic": eid, "path": epics[eid]["path"]}
            epics[eid]["features"].append(fid)
    if set(features) != {f"OME-{i:03d}" for i in range(1, 97)} or set(epics) != {f"E{i:02d}" for i in range(1, 13)}:
        raise ValueError("Expected exactly OME-001..096 and E01..E12")
    for fid, feature in features.items():
        if set(feature["deps"]) - set(features) or fid in feature["deps"]:
            raise ValueError(f"Invalid dependencies: {fid}")
    ordered: list[str] = []
    pending = set(features)
    while pending:
        ready = sorted(fid for fid in pending if set(features[fid]["deps"]).issubset(ordered))
        if not ready:
            raise ValueError("Source dependency cycle: " + ", ".join(sorted(pending)))
        ordered.extend(ready)
        pending.difference_update(ready)
    return epics, features, ordered


def put_document(path: str, content: bytes, message: str) -> str:
    if not path.startswith("docs/venture-platform/"):
        raise ValueError("Write outside documentation scope")
    endpoint = "/contents/" + quote(path, safe="/")
    existing = None
    try:
        existing = request("GET", endpoint + "?ref=" + quote(BRANCH, safe=""))
    except HTTPError as exc:
        if exc.code != 404:
            raise
    encoded = base64.b64encode(content).decode()
    if existing and base64.b64decode(existing["content"]) == content:
        return existing["sha"]
    payload = {"message": message, "content": encoded, "branch": BRANCH}
    if existing:
        payload["sha"] = existing["sha"]
    try:
        result = request("PUT", endpoint, payload)
    except (HTTPError, URLError, TimeoutError):
        check = request("GET", endpoint + "?ref=" + quote(BRANCH, safe=""))
        if base64.b64decode(check["content"]) != content:
            raise RuntimeError(f"Unconfirmed file write: {path}; stopping")
        return check["sha"]
    check = request("GET", endpoint + "?ref=" + quote(BRANCH, safe=""))
    if base64.b64decode(check["content"]) != content:
        raise RuntimeError(f"File readback mismatch: {path}")
    return result["content"]["sha"]


def install_assets() -> tuple[str, list[dict]]:
    manifest: list[dict] = []
    for asset in ASSETS:
        blob = request("GET", "/git/blobs/" + asset["blob"])
        transport = re.sub(r"\s", "", blob["content"])
        repair = asset.get("transport_repair")
        if repair:
            # Repair a precisely identified one-character transport transcription.
            # The expected source digest must match before any file is committed.
            if transport.count(repair[0]) != 1:
                raise ValueError("Unexpected asset transport; no repair applied")
            transport = transport.replace(repair[0], repair[1], 1).rstrip("=")
            transport += "=" * (-len(transport) % 4)
        data = base64.b64decode(transport, validate=True)
        if len(data) != asset["bytes"] or hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError(f"Asset digest mismatch: {asset['id']}")
        if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise ValueError("Unsupported asset signature")
        path = "docs/venture-platform/screenshots/" + asset["path"]
        sha = put_document(path, data, "docs(omega): preserve verified concept preview " + asset["id"])
        manifest.append({k: v for k, v in asset.items() if k not in ("blob", "transport_repair")} | {"git_blob_sha": sha, "repository_path": path, "role": "compressed concept reference, not acceptance screenshot"})
    put_document("docs/venture-platform/screenshots/manifest.json", (json.dumps(manifest, indent=2) + "\n").encode(), "docs(omega): record verified screenshot provenance")
    ref = request("GET", "/git/ref/heads/" + BRANCH)
    return ref["object"]["sha"], manifest


def create_once(key: str, title: str, body: str, labels: list[str], index: dict[str, dict]) -> dict:
    if key in index:
        return index[key]
    marker = "<!-- omega-venture-import:" + key + " -->"
    if marker not in body:
        raise ValueError("Missing idempotency marker")
    try:
        result = request("POST", "/issues", {"title": title, "body": body, "labels": labels})
    except (HTTPError, URLError, TimeoutError):
        # The request may have committed. Do not replay POST on uncertainty.
        time.sleep(3)
        reconciled = issue_index()
        if key not in reconciled:
            raise RuntimeError(f"Create not confirmed for {key}; safe rerun must rescan")
        result = reconciled[key]
    if marker not in (result.get("body") or ""):
        raise RuntimeError("Create receipt did not match marker")
    index[key] = result
    print(f"{key}: #{result['number']}", flush=True)
    return result


def patch_managed(issue: dict, section: str, labels: list[str] | None = None) -> None:
    fresh = request("GET", f"/issues/{issue['number']}")
    old = fresh.get("body") or ""
    if "<!-- omega-venture-import:" not in old:
        raise RuntimeError("Refusing unrelated issue")
    wrapped = MANAGED_START + "\n" + section.strip() + "\n" + MANAGED_END
    if MANAGED_START in old or MANAGED_END in old:
        pattern = re.escape(MANAGED_START) + r".*?" + re.escape(MANAGED_END)
        if len(re.findall(pattern, old, re.S)) != 1:
            raise RuntimeError("Ambiguous managed section")
        new = re.sub(pattern, lambda _: wrapped, old, count=1, flags=re.S)
    else:
        new = old.rstrip() + "\n\n" + wrapped
    if PROGRAMME_MARKER in old:
        new = new.replace("**Status:** backlog import in progress.", "**Status:** GitHub backlog import complete; feature implementation remains Proposed.")
    if new != old:
        request("PATCH", f"/issues/{issue['number']}", {"body": new})
    if labels:
        present = {x["name"] for x in fresh["labels"]}
        missing = [label for label in labels if label not in present]
        if missing:
            request("POST", f"/issues/{issue['number']}/labels", {"labels": missing})


def main() -> None:
    epics, features, order = read_specs()
    print(f"Validated {len(epics)} epics, {len(features)} features and acyclic dependencies", flush=True)
    if "--dry-run" in sys.argv:
        return
    if not TOKEN or os.environ.get("GITHUB_REPOSITORY") != REPO or os.environ.get("GITHUB_REF") != "refs/heads/" + BRANCH:
        raise RuntimeError("Requires explicit scoped repository and import-branch execution")
    index = issue_index()
    root = index.get("programme:2026-11-16")
    if not root or root["number"] != 8:
        raise RuntimeError("Expected existing reviewed programme #8")
    before_keys = set(index)
    label_specs = {"omega:venture-platform": "8A6A4A", "omega:epic": "725B91", "omega:feature": "A78B61", "status:proposed": "667078", "priority:P0": "B34E4E", "priority:P1": "B6813C", "priority:P2": "6F8B6A", "priority:P3": "7C7C7C"}
    present_labels = {label["name"] for label in collection("/labels")}
    for label, color in label_specs.items():
        if label not in present_labels:
            request("POST", "/labels", {"name": label, "color": color, "description": "Omega venture-platform backlog import"})
    asset_commit, manifest = install_assets()
    docs_base = f"https://github.com/{REPO}/blob/{asset_commit}/docs/venture-platform/"
    for eid, epic in epics.items():
        body = f"<!-- omega-venture-import:{eid} -->\nParent programme: #8. Feature work remains Proposed.\n\n[Complete specification]({docs_base}backlog/{Path(epic['path']).name}) · [Source epic]({epic['source']})\n\nThe managed feature checklist below is the delivery index."
        create_once(eid, f"[{eid}] Omega {epic['title']}", body, ["omega:venture-platform", "omega:epic", "status:proposed"], index)
    gallery = docs_base + "screenshots/README.md"

    def links(feature: dict) -> str:
        dep_links = ", ".join(f"{dep} #{index[dep]['number']}" for dep in feature["deps"]) or "None"
        visual = "vis-15-preview.webp" if feature["epic"] in ("E03", "E05", "E07", "E08", "E12") else "vis-04-preview.webp"
        image = f"https://raw.githubusercontent.com/{REPO}/{asset_commit}/docs/venture-platform/screenshots/{visual}"
        return f"## Backlog links\nEpic: #{index[feature['epic']]['number']} · Programme: #8\n\n**Dependencies:** {dep_links}\n\n[GitHub specification]({docs_base}backlog/{Path(feature['path']).name}) · [Source epic]({epics[feature['epic']]['source']}) · [UI atlas and prototype]({ATLAS}) · [Workflow inventory]({INVENTORY})\n\n## Visual reference\n![Omega concept reference]({image})\n\nThis is a compressed artistic reference, not a screen-specific acceptance capture or live business data. [GitHub screenshot gallery and provenance]({gallery}) · [All 20 original concept images and source packs]({ARCHIVE})."

    for fid in order:
        feature = features[fid]
        labels = ["omega:venture-platform", "omega:feature", "status:proposed", "priority:" + feature["priority"]]
        if fid in before_keys:
            patch_managed(index[fid], links(feature), labels)
            continue
        body = f"<!-- omega-venture-import:{fid} -->\nEpic: #{index[feature['epic']]['number']} · Programme: #8\n\n**Implementation status:** Proposed. Importing this specification does not enable the capability.\n\n{feature['body']}\n\n{MANAGED_START}\n{links(feature)}\n{MANAGED_END}"
        create_once(fid, f"[{fid}][{feature['priority']}] {feature['title']}", body, labels, index)
    for eid, epic in epics.items():
        checklist = "\n".join(f"- [{'x' if index[fid]['state'] == 'closed' else ' '}] #{index[fid]['number']} {fid} {features[fid]['title']}" for fid in epic["features"])
        section = f"## Feature delivery checklist\n{checklist}\n\n[Native specification]({docs_base}backlog/{Path(epic['path']).name}) · [UI atlas]({ATLAS}) · [Screenshot gallery]({gallery}) · [Original concepts]({ARCHIVE})\n\nCompletion requires the source acceptance evidence; importing a ticket does not complete it."
        patch_managed(index[eid], section, ["omega:venture-platform", "omega:epic", "status:proposed"])
    final = issue_index()
    wanted = set(features) | set(epics) | {"programme:2026-11-16"}
    if not wanted.issubset(final) or len({final[key]["number"] for key in wanted}) != 109:
        raise RuntimeError("Final issue count/identity verification failed")
    for fid in features:
        body = final[fid].get("body") or ""
        if "**Acceptance:" not in body and "## Acceptance criteria" not in body:
            raise RuntimeError(f"Missing acceptance in {fid}")
        if "raw.githubusercontent.com/" not in body or MANAGED_START not in body:
            raise RuntimeError(f"Missing screenshot/navigation in {fid}")
    table = "| Epic | Features | Issue |\n|---|---|---|\n" + "\n".join(f"| {eid} {epic['title']} | {epic['features'][0]}–{epic['features'][-1]} | #{final[eid]['number']} |" for eid, epic in epics.items())
    section = f"## Verified GitHub import\n**96 feature issues, 12 epic trackers and this programme tracker.** Original priorities and Proposed implementation states are preserved.\n\n{table}\n\n[GitHub documentation]({docs_base}README.md) · [Screen and workflow coverage]({docs_base}ui-coverage.md) · [Screenshots and provenance]({gallery}) · [Full-resolution concept archive]({ARCHIVE})\n\nTwo hash-verified compressed screenshots are embedded in the feature issues. The full 20-image archive and interactive prototype retain their existing Space access controls. No production code, runtime permissions, customer operations or existing unrelated issues were changed."
    patch_managed(root, section, ["omega:venture-platform"])
    report = {"repository": REPO, "branch": BRANCH, "source_revision": os.environ.get("GITHUB_SHA"), "asset_revision": asset_commit, "feature_count": 96, "epic_count": 12, "programme": 8, "new_issues": len(wanted - before_keys), "issues": {key: {"number": final[key]["number"], "url": final[key]["html_url"], "state": final[key]["state"]} for key in sorted(wanted)}, "screenshots": manifest, "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    put_document("docs/venture-platform/issue-map.json", (json.dumps(report, indent=2) + "\n").encode(), "docs(omega): record verified feature and epic issue links")
    report_md = "# Verified backlog import\n\n" + section + "\n\n## Feature index\n\n" + "\n".join(f"- [{fid}: {features[fid]['title']}]({final[fid]['html_url']})" for fid in sorted(features)) + "\n"
    put_document("docs/venture-platform/IMPORT-REPORT.md", report_md.encode(), "docs(omega): publish verified complete backlog index")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(report_md, encoding="utf-8")
    print("VERIFIED: 96 features, 12 epics, programme #8, 2 digest-checked screenshots", flush=True)


if __name__ == "__main__":
    main()
