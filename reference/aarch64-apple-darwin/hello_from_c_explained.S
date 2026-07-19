  .text                           ; Switch to the executable code section of memory
  .globl	_main                   ; Make the '_main' symbol public so the OS linker can find the start
  .p2align 2                      ; Align the next instruction to a 4-byte (2^2) memory boundary
_main:                            ; Label marking the exact memory address where 'main' begins
  stp	x29, x30, [sp, #-16]!       ; Store Pair: Save Frame Pointer (x29) & Link Register (x30) to stack, grow stack by 16 bytes
  mov	x29, sp                     ; Set the new Frame Pointer (x29) to the current Stack Pointer (sp)
  
  adrp	x0, l_str@PAGE            ; Get the 4KB memory page address of our string and put it in register x0
  add	x0, x0, l_str@PAGEOFF       ; Add the exact byte offset to x0 to pinpoint the string's full address
  bl	_puts                       ; Branch with Link: Call the 'puts' function to print the string located in x0
  
  mov	w0, #0                      ; Move 0 into w0 (lower half of x0) to act as our 'return 0;' status
  ldp	x29, x30, [sp], #16         ; Load Pair: Restore x29 & x30 from the stack, shrink stack by 16 bytes
  ret                             ; Return: Jump back to the OS using the return address we just restored to x30

  .cstring                        ; Switch to the read-only constant string section of memory
l_str:                            ; Label marking the memory location of our text
  .asciz	"Hello, World!"         ; The string itself, automatically null-terminated (ends with an invisible 0x00 byte)