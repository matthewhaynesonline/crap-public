#!/usr/bin/env bash
# Recreate the "Killed: 9" bare-metal failures on Apple Silicon for filming.
# Run each ACT separately so the terminal output lands on camera cleanly.
# NOTE: do NOT use `set -e` here -- we WANT the failing runs to happen on screen.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/hello_by_hand.S"
OUT="$SCRIPT_DIR/repro_out"
SDK="$(xcrun -sdk macosx --show-sdk-path)"
mkdir -p "$OUT"
cd "$OUT"

echo
# # echo "############################################################"
# # echo "# ACT 1 - Pure static binary. No dynamic linker at all.    #"
# # echo "# AMFI kills it instantly, valid signature or not.         #"
# # echo "############################################################"
# as -arch arm64 -o hand_classic.o "$SRC"
# ld -ld_classic -arch arm64 -o hello_static -e _start \
# 	-static -no_new_main -no_objc_relative_method_lists hand_classic.o
# codesign --force --sign - hello_static
# echo "--- load commands (note: NO LC_LOAD_DYLINKER) ---"
# otool -l hello_static | grep -A2 -E 'LC_LOAD_DYLINKER|LC_LOAD_DYLIB|LC_UNIXTHREAD|LC_MAIN'
# echo "--- running it ---"
# ./hello_static
# echo "exit status: $?" # -> Killed: 9

# echo
# echo "############################################################"
# echo "# ACT 2 - Point it at dyld + link libSystem to satisfy     #"
# echo "# the kernel... but strip the signature. Still Killed: 9.  #"
# echo "############################################################"
as -arch arm64 -o hand_hybrid.o "$SRC"
ld -arch arm64 -o hello_unsigned -e _start hand_hybrid.o \
	-lSystem -syslibroot "$SDK"
codesign --remove-signature hello_unsigned 2>/dev/null || true
echo "--- load commands (LC_LOAD_DYLINKER + LC_LOAD_DYLIB now present) ---"
otool -l hello_unsigned | grep -A2 -E 'LC_LOAD_DYLINKER|LC_LOAD_DYLIB'
echo "--- running it (no valid signature) ---"
./hello_unsigned
echo "exit status: $?" # -> Killed: 9

# echo
# echo "############################################################"
# echo "# ACT 3 - Sign the exact same binary. Now it works.        #"
# echo "############################################################"
# cp hello_unsigned hello_signed
# codesign --force --sign - hello_signed
# echo "--- running it ---"
# ./hello_signed ; echo "exit status: $?"      # -> Hello, World!
# echo
