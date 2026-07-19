  .global _start             ; Make the '_start' symbol public so the OS linker knows where to start execution
  .align 2                   ; Align the next instruction to a 4-byte (2^2) memory boundary (standard for ARM64 instructions)

_start:                      ; Label marking the exact memory address where execution begins
  ; --- SYSTEM CALL: sys_write (Print to screen) ---
  mov	x0, #1                 ; Argument 1: File descriptor for Standard Output (stdout = 1)
  adr	x1, str                ; Argument 2: Calculate the relative address of 'str' and load it into x1
  mov	x2, #14                ; Argument 3: The exact length of our string in bytes (14 characters)
  mov	x16, #4                ; Syscall Number: Load 4 (the macOS kernel number for sys_write) into register x16
  svc	#0x80                  ; Supervisor Call: Pause execution and trap to the kernel to perform the system call

  ; --- SYSTEM CALL: sys_exit (Terminate program cleanly) ---
  mov	x0, #0                 ; Argument 1: Exit status code (0 = success, no errors)
  mov	x16, #1                ; Syscall Number: Load 1 (the macOS kernel number for sys_exit) into register x16
  svc	#0x80                  ; Supervisor Call: Trap to the kernel to instantly kill the process

str:                         ; Label marking the memory location of our text
  .ascii "Hello, World!\n"   ; The string itself as raw bytes. Note: No null terminator is needed because we gave the kernel the exact length.