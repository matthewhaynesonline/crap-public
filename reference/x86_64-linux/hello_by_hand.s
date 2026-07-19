  .intel_syntax noprefix     # Use Intel syntax instead of AT&T syntax for much better readability
  .global _start             # The standard entry point for Linux ELF binaries

  .text                      # Switch to the executable code section
_start:                      # Label marking the precise entry point
  # --- SYSTEM CALL: sys_write (Print to screen) ---
  mov rax, 1                 # Syscall Number: 1 (sys_write in Linux x86_64)
  mov rdi, 1                 # Argument 1: File descriptor for Standard Output (stdout = 1)
  lea rsi, [rip + str]       # Argument 2: Load the address of our string into rsi (using instruction-pointer relative addressing)
  mov rdx, 14                # Argument 3: The exact length of our string in bytes (14 characters)
  syscall                    # Trap to the Linux kernel to execute

  # --- SYSTEM CALL: sys_exit (Terminate program cleanly) ---
  mov rax, 60                # Syscall Number: 60 (sys_exit in Linux x86_64)
  mov rdi, 0                 # Argument 1: Exit status code (0 = success)
  syscall                    # Trap to the Linux kernel to instantly kill the process

  .data                      # Switch to the data section
str:                         # Label marking the memory location of our text
  .ascii "Hello, World!\n"   # The string itself as raw bytes
