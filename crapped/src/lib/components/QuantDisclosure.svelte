<!-- The default model's quantization tradeoff; custom models have not been scored here. -->
<details class="quant-disclosure">
  <summary>
    Fine print: the default Q6_K scores 109/144, f16 scores 114/144 (five fewer correct, blah, blah,
    blah)
  </summary>
  <p>
    The default download is a quantized copy of CRAP v1.1. On the same frozen 144-item evaluation,
    Q6_K got 109 correct and f16 got 114. Five items regressed and none improved: three wrong exit
    values and two wrong string outputs. The binaries for those five items were valid, but their
    behavior was wrong.
  </p>
  <p>
    Q6_K was measured once through native llama.cpp on October 15, 2026, against the saved f16
    October 8 run. This is not a full browser evaluation. Browser output matched native Q6_K on two
    sample prompts. These scores do not cover a custom URL or local model.
  </p>
</details>
