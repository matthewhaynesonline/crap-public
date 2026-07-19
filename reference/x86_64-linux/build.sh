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
C_ASM_FILE="$SCRIPT_DIR/hello_from_c.s"
HEX_TXT="$HEX_DIR/hello_from_c.txt"
C_STRIPPED_BIN="$BUILD_DIR/hello_from_c_stripped"
HEX_STRIPPED_TXT="$HEX_DIR/hello_from_c_stripped.txt"
HEX_BIN="$BUILD_DIR/hello_from_c_round_trip"

RAW_ASM_FILE="$SCRIPT_DIR/hello_by_hand.s"
RAW_ASM_OBJ_FILE="$SCRIPT_DIR/hello_by_hand.o"
RAW_ASM_BIN="$BUILD_DIR/hello_by_hand"
RAW_ASM_HEX_TXT="$HEX_DIR/hello_by_hand.txt"

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
clang -S -O1 -fno-asynchronous-unwind-tables -mllvm --x86-asm-syntax=intel "$C_FILE" -o "$C_ASM_FILE"

echo -e "\n--- [3/5] Assembling Raw Bare-Metal ---"
echo "Linux Detected: Building native static binary..."
as -o "$RAW_ASM_OBJ_FILE" "$RAW_ASM_FILE"
ld -o "$RAW_ASM_BIN" "$RAW_ASM_OBJ_FILE"
xxd "$RAW_ASM_BIN" >"$RAW_ASM_HEX_TXT"

echo "Creating stripped variations..."
cp "$C_BIN" "$C_STRIPPED_BIN"
strip --strip-all "$C_STRIPPED_BIN"
xxd "$C_STRIPPED_BIN" >"$HEX_STRIPPED_TXT"

echo -e "\n--- [4/5] Reconstructing binary from Hex ---"
xxd -r "$HEX_TXT" >"$HEX_BIN"
chmod +x "$HEX_BIN"

echo -e "\n--- [5/5] Testing Raw Executable ---"
echo -n "Output from raw binary: "
"$RAW_ASM_BIN"

echo -e "\nLinux build complete.\n"
