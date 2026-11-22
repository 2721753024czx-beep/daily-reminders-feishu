#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    printf '用法：sh build-shortcuts.sh <Base 标识> <数据表 ID>\n' >&2
    exit 2
fi

cd "$(dirname "$0")"
unsigned_dir="$(mktemp -d)"
trap 'rm -rf "$unsigned_dir"' EXIT
mkdir -p dist

build_shortcut() {
    variant="$1"
    filename="$2"
    python3 shortcut/build.py --variant "$variant" --base-token "$3" --table-id "$4" \
        "$unsigned_dir/$filename"
    /usr/bin/shortcuts sign --mode anyone --input "$unsigned_dir/$filename" --output "dist/$filename"
}

build_shortcut create '新增必做（可同步）.shortcut' "$1" "$2"
build_shortcut sync '同步必做状态.shortcut' "$1" "$2"
printf '已生成 dist/ 下的两条快捷指令。\n'
