#!/usr/bin/env bash
# Builds the Rich Markdown body for a Telegram build notification.
# Usage: build_message.sh <started|failed|success>
#
# Reads everything from environment variables (set by the workflow before
# calling this script) so the same script covers all three notification
# phases without duplicating the layout three times in YAML.
set -euo pipefail

PHASE="${1:?usage: build_message.sh <started|failed|success>}"

# GITHUB_ACTOR, GITHUB_REF_NAME, GITHUB_REPOSITORY, GITHUB_SHA,
# GITHUB_RUN_NUMBER and GITHUB_RUN_ID are already set by the Actions
# runner for every step — no need for the workflow to pass them in.
SHORT_SHA="${GITHUB_SHA:0:7}"
ACTOR="${ACTOR:-$GITHUB_ACTOR}"
BRANCH="${BRANCH:-$GITHUB_REF_NAME}"

human_size() {
  # $1: file path. Prints a human size or "N/A" if the file doesn't exist.
  if [ -f "$1" ]; then
    du -h "$1" | cut -f1
  else
    echo "N/A"
  fi
}

module_count() {
  # $1: a .modules.load file (one module name per line).
  if [ -f "$1" ]; then
    wc -l < "$1" | tr -d ' '
  else
    echo "—"
  fi
}

lto_chip() {
  case "${LTO:-}" in
    none) echo '<tg-button type="disabled" style="danger">NoLTO</tg-button>' ;;
    thin) echo '<tg-button type="disabled" style="success">ThinLTO</tg-button>' ;;
    full) echo '<tg-button type="disabled" style="primary">FullLTO</tg-button>' ;;
    *)    echo "<tg-button type=\"disabled\">${LTO:-N/A}</tg-button>" ;;
  esac
}

nav_buttons() {
  cat <<MD
<tg-button-row>
  <tg-button type="url" url="https://github.com/${GITHUB_REPOSITORY}/commit/${GITHUB_SHA}">Commit ${SHORT_SHA}</tg-button>
  <tg-button type="url" url="https://github.com/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}">Run #${GITHUB_RUN_NUMBER}</tg-button>
</tg-button-row>
MD
}

case "$PHASE" in
  started)
    cat <<MD
# Build Started
##### Release type : ${RELEASE_TYPE}
<footer>Triggered by ${ACTOR}</footer>

---

| Device | ${PRODUCT} |
| --- | --- |
| Branch | ${BRANCH} |
| Manifest | ${MANIFEST} |
| Optimization | ${OPTIMIZE_LEVEL} |
| LTO | $(lto_chip) |

> Started: ${BUILD_START_HUMAN}

$(nav_buttons)
MD
    ;;

  failed)
    cat <<MD
# ${FAIL_EMOJI} Build ${FAIL_REASON}

| Device | ${PRODUCT} |
| --- | --- |
| Stage | ${FAIL_STAGE} |
| Branch | ${BRANCH} |
| Started | ${BUILD_START_HUMAN:-N/A} |

$(nav_buttons)
MD
    ;;

  success)
    cat <<MD
# ✅ Build Complete — ${PRODUCT}

| Partition | Size | Modules |
| --- | --- | --- |
| AK3 zip | $(human_size "${DIST_DIR}/${AK3_ZIP}") | — |
| boot.img | $(human_size "${DIST_DIR}/boot.img") | — |
| system_dlkm.img | $(human_size "${DIST_DIR}/system_dlkm.img") | $(module_count "${DIST_DIR}/system_dlkm.modules.load") |
| vendor_boot.img | $(human_size "${DIST_DIR}/vendor_boot.img") | $(module_count "${DIST_DIR}/vendor_boot.modules.load") |
| vendor_dlkm.img | $(human_size "${DIST_DIR}/vendor_dlkm.img") | $(module_count "${DIST_DIR}/vendor_dlkm.modules.load") |

<details>
<summary>SHA256 Checksums</summary>

\`\`\`
Kernel        : ${KERNEL_SHA256:-N/A}
Boot          : ${BOOT_SHA256:-N/A}
System DLKM   : ${SYSTEM_DLKM_SHA256:-N/A}
Vendor Boot   : ${VENDOR_BOOT_SHA256:-N/A}
Vendor DLKM   : ${VENDOR_DLKM_SHA256:-N/A}
\`\`\`
</details>

| Build time | ${BUILD_TIME:-N/A} |
| --- | --- |
| Started | ${BUILD_START_HUMAN:-N/A} |

$(nav_buttons)
MD
    ;;

  *)
    echo "::error::[build_message] Unknown phase: $PHASE" >&2
    exit 1
    ;;
esac
