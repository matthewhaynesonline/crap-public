#!/usr/bin/env bash
set -euo pipefail

# Resolve directories relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SRC_RUST_DIR="$PROJECT_ROOT/src_rust/hello"
SRC_DIR="$PROJECT_ROOT/src"
BUILD_DIR="$SCRIPT_DIR/bin"
HEX_DIR="$SCRIPT_DIR/hex"

# Files
RUST_BIN="$BUILD_DIR/hello_from_rust"
RUST_HEX_TXT="$HEX_DIR/hello_from_rust.txt"

C_FILE="$SRC_DIR/hello.c"
C_BIN="$BUILD_DIR/hello_from_c"
C_ASM_FILE="$SCRIPT_DIR/hello_from_c.S"
HEX_TXT="$HEX_DIR/hello_from_c.txt"
HEX_BIN="$BUILD_DIR/hello_from_c_round_trip"

RAW_ASM_FILE="$SCRIPT_DIR/hello_by_hand.S"
RAW_ASM_OBJ_FILE="$SCRIPT_DIR/hello_by_hand.o"
RAW_ASM_BIN="$BUILD_DIR/hello_by_hand"
RAW_ASM_HEX_TXT="$HEX_DIR/hello_by_hand.txt"

RAW_ASM_OBJ_FILE_CLASSIC="$SCRIPT_DIR/hello_by_hand_classic.o"
RAW_ASM_BIN_CLASSIC="$BUILD_DIR/hello_by_hand_asm_classic"
RAW_ASM_HEX_TXT_CLASSIC="$HEX_DIR/hello_by_hand_asm_classic.txt"

mkdir -p "$BUILD_DIR" "$HEX_DIR"

echo -e "\n--- [1/5] Compiling Rust Binary ---"
cargo build --release --manifest-path "$SRC_RUST_DIR/Cargo.toml" \
	--target-dir "$SRC_RUST_DIR/target"
cp "$SRC_RUST_DIR/target/release/hello" "$RUST_BIN"

echo "Size: $(wc -c <"$RUST_BIN") bytes"
xxd "$RUST_BIN" >"$RUST_HEX_TXT"

echo -e "\n--- [2/5] Compiling C Binary ---"
clang "$C_FILE" -o "$C_BIN"

echo "Dumping C binary to hex text file..."
xxd "$C_BIN" >"$HEX_TXT"

echo "Generating readable Assembly (Reference)..."
clang -S -O1 -fno-asynchronous-unwind-tables "$C_FILE" -o "$C_ASM_FILE"

echo -e "\n--- [3/5] Assembling Raw Bare-Metal ---"
echo "macOS Detected: Building Classic and Hybrid Raw binaries..."

echo "Note: This pure static binary will be killed by AMFI on modern macOS."
as -arch arm64 -o "$RAW_ASM_OBJ_FILE_CLASSIC" "$RAW_ASM_FILE"
ld -ld_classic -arch arm64 -o "$RAW_ASM_BIN_CLASSIC" -e _start -static -no_new_main -no_objc_relative_method_lists "$RAW_ASM_OBJ_FILE_CLASSIC"
codesign --force --sign - "$RAW_ASM_BIN_CLASSIC"
xxd "$RAW_ASM_BIN_CLASSIC" >"$RAW_ASM_HEX_TXT_CLASSIC"

echo "Note: Linking against libSystem to satisfy the macOS Kernel."
as -arch arm64 -o "$RAW_ASM_OBJ_FILE" "$RAW_ASM_FILE"
ld -arch arm64 -o "$RAW_ASM_BIN" -e _start "$RAW_ASM_OBJ_FILE" -lSystem -syslibroot "$(xcrun -sdk macosx --show-sdk-path)"
codesign --force --sign - "$RAW_ASM_BIN"
xxd "$RAW_ASM_BIN" >"$RAW_ASM_HEX_TXT"

echo -e "\n--- [4/5] Reconstructing binary from Hex ---"
xxd -r "$HEX_TXT" >"$HEX_BIN"
chmod +x "$HEX_BIN"
echo "Signing the reconstructed macOS binary..."
codesign --force --sign - "$HEX_BIN"

echo -e "\n--- [5/5] Testing Raw Executable ---"
echo -n "Output from raw binary: "
"$RAW_ASM_BIN" || echo "Execution failed (Expected on macOS Classic, but Hybrid should run)."

echo -e "\nmacOS build complete.\n"
