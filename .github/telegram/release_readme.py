#!/usr/bin/env python3
"""Generates the GitHub Release body (release_notes.md) for a finished build.

Shares build_info.py with telegram.py — same --feat/--file mechanism, same
sha256-at-send-time philosophy (hashes the actual release assets being
uploaded, not a value computed earlier in a different job).

Device-config fields (SOC, CODENAME, MODEL, ANDROID_VERSION, ...) are read
from the environment — the calling workflow step should export the matching
configs/<model>.json into $GITHUB_ENV first, the same way env_setup does for
the build job. Anything build-specific (kernel version, KSU tag/version,
SUSFS version) is a required CLI arg instead, since it doesn't live in the
static device config.

Usage:
    release_readme.py --product "OnePlus 11 5G" --release-type Release \
        --kernel-version 6.1.87 --ksun-tag v1.2.3 --ksun-version v1.2.3-abcdef \
        --susfs-version v1.5.7 \
        --feat realtek --feat ath \
        --file EmberHeart.zip --file boot.img \
        --out release_notes.md
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import build_info as bi

HERE = Path(__file__).resolve().parent

KSUN_MANAGER_URL = "https://github.com/KernelSU-Next/KernelSU-Next"
SUSFS_MODULE_URL = "https://github.com/sidex15/ksu_module_susfs"

# Static feature bullets that aren't (yet) part of the --feat/features.json
# mechanism — kept as-is from the previous release notes generator.
STATIC_FEATURES = [
    "Wireguard Support",
    "Magic Mount Support",
    "Ptrace message leak fix for kernels < 5.16",
    "Manual Hooks [scope_min_manual_hooks_v1.4]",
    "CONFIG_TMPFS_XATTR Support [Mountify Support]",
    "BBR v1 Support",
    "Baseband Guard Support (BBG)",
    "Nethunter Support",
    "Mem kernel driver by @Poko-Apps [r/w to physical memory]",
    "IP Set Support",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--feat", action="append", default=[], dest="feats")
    p.add_argument("--file", action="append", default=[], dest="files", help="Release asset to hash + list. Repeatable.")
    p.add_argument("--features-json", default=str(HERE / "features.json"))

    p.add_argument("--product", default=os.environ.get("PRODUCT", ""))
    p.add_argument("--codename", default=os.environ.get("CODENAME", ""))
    p.add_argument("--soc", default=os.environ.get("SOC", ""))
    p.add_argument("--os", dest="os_name", default=os.environ.get("OS", ""))

    p.add_argument("--kernel-version", required=True, help="Actual compiled kernel version (from the build job) — do not confuse with the config's static major.minor field.")
    p.add_argument("--ksun-tag", required=True)
    p.add_argument("--ksun-version", required=True)
    p.add_argument("--susfs-version", default="")

    p.add_argument("--release-type", required=True, choices=["Pre-release", "Release"])
    p.add_argument("--out", default="release_notes.md")
    return p.parse_args()


def build_intro(args: argparse.Namespace) -> str:
    if args.susfs_version:
        lines = [
            f"This release contains KernelSU Next {args.ksun_tag}, Nethunter and SUSFS {args.susfs_version}",
            "",
            "Module:",
            f"-> {SUSFS_MODULE_URL}",
        ]
    else:
        lines = [f"This release contains KernelSU Next {args.ksun_tag} & Nethunter"]
    lines += ["", "Official Managers:", f"-> {KSUN_MANAGER_URL}"]
    return "\n".join(lines)


def build_device_table(args: argparse.Namespace) -> str:
    return "\n".join([
        "### Built Device",
        "",
        "| Model | Codename | SoC | Kernel Version |",
        "|-------|----------|-----|-----------------|",
        f"| {args.product} | {args.codename} | {args.soc or 'N/A'} | {args.kernel_version} |",
    ])


def build_notes(args: argparse.Namespace, feats: dict[str, list[bi.Feature]], entries: list[bi.FileEntry]) -> str:
    parts = [build_intro(args), build_device_table(args)]

    feature_lines = ["### Features", ""]
    if feats:
        feature_lines += ["<details>", "<summary>What's Inside</summary>", ""]
        for category, items in feats.items():
            feature_lines.append(f"#### {category}")
            for it in items:
                feature_lines.append(f"- **{it.name}**: {it.description}")
            feature_lines.append("")
        feature_lines.append("</details>")
        feature_lines.append("")

    feature_lines.append(f"- [+] KernelSU-Next {args.ksun_tag} ( {args.ksun_version} )")
    if args.susfs_version:
        feature_lines.append(f"- [+] SUSFS {args.susfs_version}")
    for f in STATIC_FEATURES:
        feature_lines.append(f"- [+] {f}")
    parts.append("\n".join(feature_lines))

    parts.append(
        "> [!NOTE]\n"
        "> Some features might vary depending on the model due to compatibility issues"
    )

    important_lines = [
        "> [!IMPORTANT]",
        f"> Codename: {args.codename}",
        f"> Supported OS version: {args.os_name}",
    ]
    for e in entries:
        important_lines.append(f"> {os.path.basename(e.path)} hash : {e.sha256}")
    parts.append("\n".join(important_lines))

    return "\n\n".join(parts) + "\n"


def main() -> None:
    args = parse_args()
    feats = bi.load_features(args.feats, args.features_json)
    entries = bi.collect_files(args.files)

    notes = build_notes(args, feats, entries)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(notes)
    print(f"[release_readme] Wrote {args.out} ({len(notes)} chars)")


if __name__ == "__main__":
    main()
