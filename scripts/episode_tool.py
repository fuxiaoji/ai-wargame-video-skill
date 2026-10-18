#!/usr/bin/env python3
"""Offline artifact checks for AI wargame videos; not a game/rules verifier."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import struct
import sys
import zlib
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote

SHA = re.compile(r"[0-9a-f]{64}\Z")
STAGES = ("draft", "capture", "edit", "delivery")
STATUSES = {"planned", "running", "complete"}
EVIDENCE_KINDS = {"actual", "schematic", "history", "enactment"}


class AuditError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise AuditError(message)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_path(root, relative, *, must_exist=True):
    need(nonempty(relative), "File path must be a nonempty string")
    posix = PurePosixPath(relative)
    win = PureWindowsPath(relative)
    need(not posix.is_absolute() and not win.drive and "\\" not in relative
         and ".." not in posix.parts and ":" not in relative,
         f"Nonportable or escaping path: {relative}")
    path = (root / relative).resolve()
    need(path != root and path.is_relative_to(root),
         f"File escapes episode directory: {relative}")
    if must_exist:
        need(path.is_file(), f"Missing regular file: {relative}")
    return path


def file_ref(root, relative):
    path = local_path(root, relative)
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256(path)}


def png_size(path):
    # Validate the PNG signature and IHDR, not the entire pixel stream.
    with path.open("rb") as stream:
        header = stream.read(33)
    need(len(header) == 33 and header[:8] == b"\x89PNG\r\n\x1a\n"
         and header[8:12] == b"\x00\x00\x00\r" and header[12:16] == b"IHDR",
         f"Not a PNG header (possibly a Git LFS pointer): {path.name}")
    need(zlib.crc32(header[12:29]) & 0xffffffff == struct.unpack(">I", header[29:33])[0],
         f"Invalid PNG IHDR checksum: {path.name}")
    width, height = struct.unpack(">II", header[16:24])
    need(width > 0 and height > 0, f"Invalid PNG dimensions: {path.name}")
    return width, height


def unique_ids(items, label):
    need(isinstance(items, list), f"{label} must be a list")
    ids = []
    for item in items:
        need(isinstance(item, dict) and nonempty(item.get("id")),
             f"{label} item needs an id")
        ids.append(item["id"])
    need(len(ids) == len(set(ids)), f"Duplicate {label} id")
    return ids


def check_ref(root, value, cache):
    need(isinstance(value, dict) and "path" in value and "sha256" in value,
         "File reference needs path and sha256")
    need(isinstance(value["sha256"], str) and SHA.fullmatch(value["sha256"]),
         f"Invalid file SHA256: {value.get('path')}")
    path = local_path(root, value["path"])
    key = str(path)
    if key not in cache:
        cache[key] = sha256(path)
    need(cache[key] == value["sha256"], f"File SHA256 mismatch: {value['path']}")
    return path


def check_all_refs(root, value, cache):
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            check_ref(root, value, cache)
        for child in value.values():
            check_all_refs(root, child, cache)
    elif isinstance(value, list):
        for child in value:
            check_all_refs(root, child, cache)


def read_episode(root):
    need(root.is_dir(), "Episode directory does not exist")
    path = local_path(root, "episode.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    need(isinstance(data, dict), "episode.json must be an object")
    return data


def validate(root, stage="draft"):
    root = Path(root).resolve()
    data = read_episode(root)
    need(data.get("schema_version") == 1, "schema_version must be 1")
    need(nonempty(data.get("episode_id")), "episode_id is required")
    need(integer(data.get("fps"), 1), "fps must be a positive integer")
    fps = data["fps"]
    planned = data.get("planned_game_ids")
    need(isinstance(planned, list) and planned and all(nonempty(i) for i in planned),
         "planned_game_ids needs at least one id")
    need(len(planned) == len(set(planned)), "Duplicate planned_game_ids")
    actor_ids = unique_ids(data.get("actors"), "actors")
    need("director" not in actor_ids, "director is reserved for the spectator view")
    units = []
    for actor in data["actors"]:
        need(nonempty(actor.get("side")) and nonempty(actor.get("model")),
             f"Actor {actor['id']} needs side and actual model id")
        need(isinstance(actor.get("unit_ids"), list)
             and actor["unit_ids"] and all(nonempty(u) for u in actor["unit_ids"]),
             f"Actor {actor['id']} needs unit_ids")
        units.extend(actor["unit_ids"])
    need(len(units) == len(set(units)), "A unit is assigned to multiple actor slots")
    views = data.get("supervision_views")
    allowed_views = {"director", *actor_ids}
    need(isinstance(views, list) and all(isinstance(v, str) for v in views)
         and "director" in views and len(views) == len(set(views))
         and set(views) <= allowed_views, "Invalid supervision_views")
    game_ids = unique_ids(data.get("games"), "games")
    need(set(game_ids) == set(planned), "games must match planned_game_ids exactly")
    cache = {}
    check_all_refs(root, data, cache)
    game_by_id = {g["id"]: g for g in data["games"]}
    for game in data["games"]:
        gid = game["id"]
        need(game.get("status") in STATUSES, f"Invalid status for {gid}")
        turns = game.get("completed_turns")
        need(isinstance(turns, list) and all(integer(t) for t in turns)
             and len(turns) == len(set(turns)), f"Invalid completed_turns for {gid}")
        snapshots = game.get("snapshots")
        need(isinstance(snapshots, list), f"snapshots must be a list for {gid}")
        pairs = set()
        for snap in snapshots:
            need(isinstance(snap, dict) and integer(snap.get("turn"))
                 and snap.get("view") in allowed_views, f"Invalid snapshot for {gid}")
            pair = (snap["turn"], snap["view"])
            need(pair not in pairs, f"Duplicate snapshot {gid}/{pair}")
            pairs.add(pair)
            need(snap["turn"] in turns, f"Snapshot is not a completed turn: {gid}/{pair}")
            image = check_ref(root, snap.get("image"), cache)
            need(SHA.fullmatch(str(snap.get("state_sha256", ""))),
                 f"Missing original state SHA256: {gid}/{pair}")
            if stage != "draft":
                png_size(image)
        if game["status"] == "planned":
            need(not turns and not snapshots, f"Planned game has captured data: {gid}")
        if stage != "draft":
            if game["status"] in {"running", "complete"}:
                need(bool(turns), f"Started game needs T0: {gid}")
            if turns:
                need(sorted(turns) == list(range(max(turns) + 1)),
                     f"Completed turn sequence has a gap or lacks T0: {gid}")
                expected = {(turn, view) for turn in turns for view in views}
                missing = sorted(expected - pairs)
                need(not missing, f"Missing supervision snapshots for {gid}: {missing}")

    selected = data.get("selected_game_id")
    need(selected is None or selected in game_by_id, "Selected game is outside the batch")
    if selected is not None:
        need(game_by_id[selected]["status"] == "complete", "Selected game is incomplete")

    if stage in {"edit", "delivery"}:
        need(actor_ids, "Editing needs registered command actors")
        need(all(g["status"] == "complete" for g in data["games"]),
             "The agreed game batch is incomplete")
        need(selected is not None, "Select a completed game before editing")
        shot_ids = unique_ids(data.get("shots"), "shots")
        need(shot_ids, "Timeline has no shots")
        cursor = 0
        shots = {}
        for shot in data["shots"]:
            sid = shot["id"]
            need(integer(shot.get("start_frame")) and shot["start_frame"] == cursor,
                 f"Timeline gap/overlap at {sid}; expected start {cursor}")
            need(integer(shot.get("duration_frames"), 1), f"Invalid duration for {sid}")
            need(shot.get("view") in allowed_views, f"Unknown view in {sid}")
            need(shot.get("evidence_kind") in EVIDENCE_KINDS,
                 f"Missing evidence kind in {sid}")
            refs = shot.get("source_refs")
            need(isinstance(refs, list), f"source_refs must be a list in {sid}")
            need(shot["evidence_kind"] != "actual" or refs,
                 f"Actual footage needs source evidence in {sid}")
            for ref in refs:
                check_ref(root, ref, cache)
            shots[sid] = shot
            cursor += shot["duration_frames"]

        interactions = data.get("interactions")
        need(isinstance(interactions, list), "interactions must be a list")
        used_prompts = set()
        used_reveals = set()
        for interaction in interactions:
            need(isinstance(interaction, dict), "Invalid interaction")
            pid = interaction.get("prompt_shot_id")
            rid = interaction.get("reveal_shot_id")
            aid = interaction.get("actor_id")
            need(pid in shots and rid in shots and pid != rid,
                 "Interaction needs existing, distinct prompt and reveal shots")
            need(pid not in used_prompts and rid not in used_reveals,
                 "Repeated interaction prompt/reveal")
            used_prompts.add(pid)
            used_reveals.add(rid)
            need(aid in actor_ids, "Interaction needs an existing command actor")
            prompt, reveal = shots[pid], shots[rid]
            need(prompt["view"] == aid, f"Decision prompt must use actor view: {pid}")
            end_audio = interaction.get("prompt_audio_end_frame")
            start = interaction.get("countdown_start_frame")
            duration = interaction.get("countdown_frames")
            need(integer(end_audio) and integer(start) and integer(duration, 1),
                 f"Interaction times must be integer frames: {pid}")
            need(prompt["start_frame"] <= end_audio <= start,
                 f"Countdown starts before complete question audio: {pid}")
            need(duration == 3 * fps, f"Countdown is not exactly three seconds: {pid}")
            prompt_end = prompt["start_frame"] + prompt["duration_frames"]
            need(start + duration == prompt_end == reveal["start_frame"],
                 f"Reveal must immediately follow the countdown: {pid}")
            receipt = interaction.get("receipt")
            check_ref(root, receipt, cache)
            need(receipt in reveal["source_refs"],
                 f"Reveal is not bound to its accepted-decision receipt: {rid}")
        required = data.get("delivery_required")
        need(isinstance(required, list) and required and all(nonempty(k) for k in required)
             and len(required) == len(set(required)), "Invalid delivery_required")
        if stage == "delivery":
            delivery = data.get("delivery")
            need(isinstance(delivery, dict), "delivery must be an object")
            for key in required:
                path = check_ref(root, delivery.get(key), cache)
                need(path.stat().st_size > 0, f"Empty delivery artifact: {key}")

    return data, {"ok": True, "stage": stage, "episode_id": data["episode_id"],
                  "games": len(game_ids), "snapshots": sum(len(g["snapshots"]) for g in data["games"]),
                  "checked_files": len(cache),
                  "scope": "Artifact integrity/coverage/timing only; not rules, double-blind or media QA"}


def initialize(root, episode_id, games, fps):
    need(nonempty(episode_id), "episode_id is required")
    need(integer(games, 1) and integer(fps, 1), "games/fps must be positive integers")
    template = Path(__file__).resolve().parent.parent / "assets" / "episode.template.json"
    data = json.loads(template.read_text(encoding="utf-8"))
    data.update(episode_id=episode_id, fps=fps,
                planned_game_ids=[f"game-{i + 1}" for i in range(games)])
    data["games"] = [{"id": gid, "status": "planned", "completed_turns": [],
                      "snapshots": []} for gid in data["planned_game_ids"]]
    root.mkdir(parents=True, exist_ok=False)
    (root / "episode.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def supervision(root, *, overwrite=False):
    root = Path(root).resolve()
    data, report = validate(root, "capture")
    need(report["snapshots"] > 0, "No captured snapshots to show")
    output = local_path(root, "index.html", must_exist=False)
    need(not output.exists() or overwrite, "index.html exists; use --overwrite to replace")
    sections = []
    actors = {a["id"]: a for a in data["actors"]}
    for game in data["games"]:
        cards = []
        for turn in sorted(game["completed_turns"]):
            figures = []
            by_view = {s["view"]: s for s in game["snapshots"] if s["turn"] == turn}
            for view in data["supervision_views"]:
                snap = by_view[view]
                label = "Director / 全知监督" if view == "director" else (
                    f"{view} · {actors[view]['side']} · {actors[view]['model']}")
                relative = local_path(root, snap["image"]["path"]).relative_to(root).as_posix()
                url = html.escape(quote(relative, safe="/"), quote=True)
                figures.append(
                    f'<figure><a href="{url}"><img loading="lazy" src="{url}" '
                    f'alt="{html.escape(label, quote=True)}"></a>'
                    f'<figcaption>{html.escape(label)}<br>'
                    f'<small>image SHA: {snap["image"]["sha256"]}</small></figcaption></figure>')
            cards.append(f'<details open><summary>T{turn:02d}</summary>'
                         f'<div class="views">{"".join(figures)}</div></details>')
        sections.append(f'<section><h2>{html.escape(game["id"])} · '
                        f'{html.escape(game["status"])}</h2>{"".join(cards)}</section>')
    title = html.escape(data["episode_id"])
    page = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 逐回合监督</title>
<style>
body{{margin:0;background:#09141f;color:#e9eef1;font:16px system-ui,sans-serif}}
main{{max-width:1440px;margin:auto;padding:28px}}
h1{{font-size:26px}} h2{{color:#e4bd78}}
.notice{{background:#273346;border-left:4px solid #e4bd78;padding:14px;line-height:1.6}}
section{{margin:28px 0}} details{{margin:12px 0;background:#142333;border-radius:10px;padding:14px}}
summary{{cursor:pointer;font-weight:bold}} .views{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:16px}}
figure{{margin:16px 0 0;min-width:0}} img{{width:100%;height:auto;background:#050b10;border-radius:5px}}
figcaption{{line-height:1.6;padding:7px 0}} small{{overflow-wrap:anywhere;color:#98acbc;font-size:11px}}
</style><main><h1>{title} · 逐回合监督</h1>
<p class="notice">导演监督页，含全知图。仅供制片与用户检查，不作为指挥模型输入。图片来自登记文件；
哈希/覆盖检查不证明规则或双盲过滤正确。</p>
{"".join(sections)}</main></html>"""
    output.write_text(page, encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a new empty episode; never run games")
    init.add_argument("directory", type=Path)
    init.add_argument("--episode-id", required=True)
    init.add_argument("--games", type=int, default=5)
    init.add_argument("--fps", type=int, default=30)
    ref = commands.add_parser("ref", help="Hash one file inside the episode")
    ref.add_argument("directory", type=Path)
    ref.add_argument("relative_path")
    check = commands.add_parser("validate", help="Read-only artifact checks")
    check.add_argument("directory", type=Path)
    check.add_argument("--stage", choices=STAGES, default="draft")
    page = commands.add_parser("supervision", help="Create a director-only offline HTML index")
    page.add_argument("directory", type=Path)
    page.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.directory.resolve()
        if args.command == "init":
            initialize(root, args.episode_id, args.games, args.fps)
            result = {"ok": True, "created": str(root / "episode.json"), "games_started": 0}
        elif args.command == "ref":
            result = file_ref(root, args.relative_path)
        elif args.command == "validate":
            _, result = validate(root, args.stage)
        else:
            result = {"ok": True, "supervision": str(supervision(root, overwrite=args.overwrite))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (AuditError, OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
