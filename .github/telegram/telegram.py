#!/usr/bin/env python3
"""Sends one Telegram Rich Message announcing a finished build.

Usage:
    telegram.py --product "OnePlus 11 5G" --release-type none \
        --lto thin --optimize-level O2 --kernel-uname 6.1.87-EmberHeart \
        --ksun-version v1.2.3 \
        --banner https://raw.githubusercontent.com/nullptr-t-oss/.../banner.png \
        --feat realtek --feat ath --feat can_slcan \
        --file /path/to/EmberHeart.zip --file /path/to/boot.img \
        --build-start 1757930400

Secrets (bot token / chat id / thread id) are read from environment
variables, not CLI args, so they never show up in a process listing or
a workflow's "Run <command>" log line:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_THREAD_ID
Which chat/thread to send to (test vs release) is decided by the
*caller* (the workflow step), not this script — this script just sends
to whatever chat/thread it's given.
"""
from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import build_info as bi

HERE = Path(__file__).resolve().parent

RELEASE_CHIP = {
    # release_type value -> (label, tg-button style)
    "none":        ("Canary",      "danger"),
    "Pre-release": ("Pre-release", "primary"),
    "Release":     ("Release",     "success"),
}

GITHUB_PROFILE_URL = "https://github.com/nullptr-t-oss"
PROJECT_URL = "https://github.com/nullptr-t-oss/EmberHeart_OnePlus11"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--banner", help="Local file path OR a public https URL for the header image. Optional.")
    p.add_argument("--feat", action="append", default=[], dest="feats", help="Feature id from features.json. Repeatable.")
    p.add_argument("--file", action="append", default=[], dest="files", help="Local file path to attach. Repeatable.")
    p.add_argument("--features-json", default=str(HERE / "features.json"))

    p.add_argument("--product", required=True)
    p.add_argument("--branch", default="")
    p.add_argument("--manifest", default="")
    p.add_argument("--lto", default="")
    p.add_argument("--optimize-level", default="")
    p.add_argument("--kernel-uname", default="")
    p.add_argument("--ksun-version", default="")
    p.add_argument("--release-type", default="none", choices=list(RELEASE_CHIP.keys()))
    p.add_argument("--release-tag", default="", help="e.g. salami-oos16-r7. Shown on the release chip instead of the category label when release-type is Pre-release/Release.")
    p.add_argument("--ksun-commit-url", default="", help="If set, the KSU version cell becomes a clickable chip linking here.")

    p.add_argument("--build-start", type=int, required=True, help="Unix epoch seconds when the build started.")
    p.add_argument("--debug-bundle", action="store_true", help="Minimal message: heading, info table, the attached file(s), build time — no banner/release-chip/feature-tree. For internal debug-archive pings, not the main release message.")

    p.add_argument("--bot-token", default=os.environ.get("TELEGRAM_BOT_TOKEN"))
    p.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"))
    p.add_argument("--thread-id", default=os.environ.get("TELEGRAM_THREAD_ID"))
    p.add_argument("--api-base", default=os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org"))

    p.add_argument("--dry-run", action="store_true", help="Print the payload instead of sending it.")
    return p.parse_args()


def lto_chip(lto: str) -> str:
    style = {"none": "danger", "thin": "success", "full": "primary"}.get(lto, "")
    label = {"none": "NoLTO", "thin": "ThinLTO", "full": "FullLTO"}.get(lto, lto or "N/A")
    style_attr = f' style="{style}"' if style else ""
    return f'<tg-button type="disabled"{style_attr}>{html.escape(label)}</tg-button>'


def release_chip(release_type: str, release_tag: str) -> str:
    label, style = RELEASE_CHIP.get(release_type, (release_type, ""))
    if release_tag and release_type in ("Pre-release", "Release"):
        label = release_tag
    return f'<tg-button type="disabled" style="{style}">{html.escape(label)}</tg-button>'


def build_features_block(feats: dict[str, list[bi.Feature]]) -> str:
    if not feats:
        return ""
    lines = ["<details>", '<summary>What\'s Inside</summary>', ""]
    for category, items in feats.items():
        lines.append("<details>")
        lines.append(f"<summary>{html.escape(category)}</summary>")
        lines.append("")
        for it in items:
            lines.append(f"- **{html.escape(it.name)}**: {html.escape(it.description)}")
        lines.append("</details>")
    lines.append("</details>")
    return "\n".join(lines)


def build_files_block(entries: list[bi.FileEntry]) -> tuple[str, list[dict], dict[str, str]]:
    """Returns (markdown fragment with files interleaved with their hash,
    media list for the attach:// payload, {attach_id: local_path})."""
    lines = []
    media = []
    attach_paths = {}
    for e in entries:
        filename = os.path.basename(e.path)
        lines.append(f"![{html.escape(filename)}](tg://document?id={e.attach_id})")
        lines.append("SHA256 Checksum")
        lines.append(f"```\n{e.sha256}\n```")
        media.append({"id": e.attach_id, "media": {"type": "document", "media": f"attach://{e.attach_id}"}})
        attach_paths[e.attach_id] = e.path
    return "\n\n".join(lines), media, attach_paths


def ksu_cell(ksun_version: str, commit_url: str) -> str:
    label = html.escape(ksun_version or "N/A")
    if not commit_url:
        return label
    return f'<tg-button type="url" style="primary" url="{commit_url}">{label}</tg-button>'


def build_info_table(args: argparse.Namespace) -> str:
    rows = [
        ("LTO", lto_chip(args.lto)),
        ("Optimization", html.escape(args.optimize_level or "N/A")),
        ("Kernel", html.escape(args.kernel_uname or "N/A")),
        ("KSU", ksu_cell(args.ksun_version, args.ksun_commit_url)),
    ]
    body = "".join(f"<tr><td>{label}</td><td>{value}</td></tr>" for label, value in rows)
    header = f'<tr><th colspan="2" align="center">{html.escape(args.product)}</th></tr>'
    return f"<table bordered>{header}{body}</table>"


def build_nav_buttons(ctx: bi.GitHubContext) -> str:
    return "\n".join([
        "<tg-button-row>",
        f'  <tg-button type="url" url="{ctx.commit_url}">Commit {ctx.short_sha}</tg-button>',
        f'  <tg-button type="url" url="{ctx.run_url}">Run #{ctx.run_number}</tg-button>',
        "</tg-button-row>",
        "<tg-button-row>",
        f'  <tg-button type="url" style="primary" url="{GITHUB_PROFILE_URL}">Follow on GitHub</tg-button>',
        "</tg-button-row>",
        "<tg-button-row>",
        f'  <tg-button type="url" style="primary" url="{PROJECT_URL}">Star this project</tg-button>',
        "</tg-button-row>",
    ])


def build_message(args: argparse.Namespace, ctx: bi.GitHubContext) -> tuple[str, list[dict], dict[str, str]]:
    feats = bi.load_features(args.feats, args.features_json)
    entries = bi.collect_files(args.files)
    files_md, media, attach_paths = build_files_block(entries)

    now = int(time.time())
    duration = bi.format_duration(now - args.build_start)
    start_human = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(args.build_start))

    parts = []
    if args.banner and not args.debug_bundle:
        if os.path.isfile(args.banner):
            media.insert(0, {"id": "banner", "media": {"type": "photo", "media": "attach://banner"}})
            attach_paths["banner"] = args.banner
        else:
            media.insert(0, {"id": "banner", "media": {"type": "photo", "media": args.banner}})
        parts.append("![](tg://photo?id=banner)")

    if args.debug_bundle:
        parts.append(f"# {html.escape(args.product)} \u2014 Debug Artifacts")
    else:
        parts.append(f"# {html.escape(args.product)} \u2014 Build Complete")
        parts.append(release_chip(args.release_type, args.release_tag))

    if not args.debug_bundle:
        feats_block = build_features_block(feats)
        if feats_block:
            parts.append(feats_block)

    parts.append(build_info_table(args))

    if files_md:
        parts.append(files_md)

    parts.append(f"> Build time: {duration}\n> Started: {start_human}")
    parts.append(build_nav_buttons(ctx))

    markdown = "\n\n".join(p for p in parts if p)
    return markdown, media, attach_paths


def encode_multipart(fields: dict[str, str], file_fields: dict[str, str]) -> tuple[bytes, str]:
    """file_fields: {form_field_name: local_path}. Whole files are read
    into memory — fine for kernel build artifacts, not for multi-GB blobs."""
    boundary = uuid.uuid4().hex
    CRLF = b"\r\n"
    body = bytearray()

    for name, value in fields.items():
        body += f"--{boundary}".encode() + CRLF
        body += f'Content-Disposition: form-data; name="{name}"'.encode() + CRLF + CRLF
        body += str(value).encode() + CRLF

    for name, path in file_fields.items():
        filename = os.path.basename(path)
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body += f"--{boundary}".encode() + CRLF
        body += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode() + CRLF
        body += f"Content-Type: {ctype}".encode() + CRLF + CRLF
        with open(path, "rb") as f:
            body += f.read()
        body += CRLF

    body += f"--{boundary}--".encode() + CRLF
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def send(args: argparse.Namespace, markdown: str, media: list[dict], attach_paths: dict[str, str]) -> None:
    payload = {"markdown": markdown}
    if media:
        payload["media"] = media

    fields = {
        "chat_id": args.chat_id,
        "message_thread_id": args.thread_id,
        "rich_message": json.dumps(payload),
    }
    file_fields = dict(attach_paths)  # {attach_id: local_path}, already resolved

    body, content_type = encode_multipart(fields, file_fields)
    url = f"{args.api_base.rstrip('/')}/bot{args.bot_token}/sendRichMessage"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        print(f"::warning::[telegram] sendRichMessage failed (HTTP {e.code}): {err_body}", file=sys.stderr)
        return
    except urllib.error.URLError as e:
        print(f"::warning::[telegram] sendRichMessage request failed: {e}", file=sys.stderr)
        return

    if not result.get("ok"):
        print(f"::warning::[telegram] sendRichMessage returned not-ok: {result}", file=sys.stderr)
        return

    print(f"[telegram] Sent with {len(file_fields)} embedded file(s).")


def main() -> None:
    args = parse_args()
    if not args.dry_run and (not args.bot_token or not args.chat_id or not args.thread_id):
        sys.exit("telegram.py: --bot-token/--chat-id/--thread-id (or their env vars) are required unless --dry-run")

    ctx = bi.github_context()
    markdown, media, attach_paths = build_message(args, ctx)

    if args.dry_run:
        print(markdown)
        print("\n--- media ---")
        print(json.dumps(media, indent=2))
        print("\n--- attach_paths ---")
        print(json.dumps(attach_paths, indent=2))
        return

    send(args, markdown, media, attach_paths)


if __name__ == "__main__":
    main()
