# Veridict Training Report

Generated: 2026-04-21T12:39:37
Base model: `google/gemma-3-27b-it`
Total wall-clock: 1259.7 min

## Metrics

| Model | Status | Valid JSON | Issue Type Acc | Severity Acc | Golden Issue Acc | Elapsed (min) |
|-------|--------|-----------:|---------------:|-------------:|-----------------:|--------------:|
| harvey | ERROR | — | — | — | — | — |
| kira | ERROR | — | — | — | — | — |
| admin | ERROR | — | — | — | — | — |

## Adapter checkpoints

- [ ] `C:\Users\hac23\PycharmProjects\Veridict\outputs\harvey_adapter`
- [ ] `C:\Users\hac23\PycharmProjects\Veridict\outputs\kira_adapter`
- [ ] `C:\Users\hac23\PycharmProjects\Veridict\outputs\admin_adapter`

## Files

- Run state: `C:\Users\hac23\PycharmProjects\Veridict\outputs\run_state.json`
- Full log: `C:\Users\hac23\PycharmProjects\Veridict\outputs\training_run.log`

## Next step

Wire the adapters into `app/backend/agents/reviewer.py` and `app/backend/agents/admin.py`.

Windows PowerShell
Copyright (C) Microsoft Corporation. All rights reserved.

Install the latest PowerShell for new features and improvements! https://aka.ms/PSWindows

PS C:\WINDOWS\system32> cd C:\Users\hac23\PycharmProjects\Veridict
PS C:\Users\hac23\PycharmProjects\Veridict> set PYTHONUTF8=1 && set HF_HUB_DISABLE_SYMLINKS_WARNING=1 && .venv\Scripts\python.exe scripts\run_training_sequence.py
At line:1 char:18
+ set PYTHONUTF8=1 && set HF_HUB_DISABLE_SYMLINKS_WARNING=1 && .venv\Sc ...
+                  ~~
The token '&&' is not a valid statement separator in this version.
At line:1 char:59
+ set PYTHONUTF8=1 && set HF_HUB_DISABLE_SYMLINKS_WARNING=1 && .venv\Sc ...
+                                                           ~~
The token '&&' is not a valid statement separator in this version.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : InvalidEndOfLine

PS C:\Users\hac23\PycharmProjects\Veridict> $env:PYTHONUTF8=1; $env:HF_HUB_DISABLE_SYMLINKS_WARNING=1; .venv\Scripts\python.exe scripts\run_training_sequence.py
============================================================
VERIDICT — SEQUENTIAL GRPO QLORA TRAINING
Base model: google/gemma-3-27b-it
MAX_STEPS:  2000
============================================================

Running preflight checks...
Preflight OK.

GPU: NVIDIA RTX 4000 Ada Generation  (21.5 GB VRAM)

Loading tokenizer once (shared across all three models)...
Tokenizer loaded. Vocab size: 262144

Loading and preparing all three datasets...

[Harvey] 9,992 training examples
[Kira] 4,000 training examples
[Admin] 8,002 training examples  (natural=2, harvey-primary~4000, kira-primary~4000)

############################################################
  TRAINING: HARVEY  (num_generations=4)
  Examples: 9,992
  Output:   C:\Users\hac23\PycharmProjects\Veridict\outputs\harvey_adapter
############################################################

  Loading google/gemma-3-27b-it in 4-bit NF4 ...
`torch_dtype` is deprecated! Use `dtype` instead!
Fetching 12 files: 100%|###########################################################| 12/12 [4:40:00<00:00, 1400.02s/it]
Download complete: 100%|########################################################| 54.9G/54.9G [4:40:00<00:00, 3.27MB/s]
Loading weights: 100%|#######################################################################################################################################################| 1247/1247 [00:34<00:00, 35.98it/s]
generation_config.json: 100%|###################################################################################################################################################| 215/215 [00:00<00:00, 1.04MB/s]
  Model loaded in 16841s. VRAM used: 19.1 GB

Traceback (most recent call last):
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\run_training_sequence.py", line 215, in train_one_with_retries
    return _train_attempt(name, dataset, reward_fn, output_dir, tokenizer, num_gen)
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\run_training_sequence.py", line 151, in _train_attempt
    config = get_grpo_config(output_dir, num_generations=num_generations)
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\train_shared.py", line 433, in get_grpo_config
    return GRPOConfig(
        output_dir=str(output_dir),
    ...<19 lines>...
        top_p=0.95,
    )
TypeError: GRPOConfig.__init__() got an unexpected keyword argument 'max_prompt_length'

[HARVEY] Marked failed; continuing to next model.

############################################################
  TRAINING: KIRA  (num_generations=4)
  Examples: 4,000
  Output:   C:\Users\hac23\PycharmProjects\Veridict\outputs\kira_adapter
############################################################

  Loading google/gemma-3-27b-it in 4-bit NF4 ...
  SDPA attention failed (Some modules are dispatched on the CPU or the disk. Make sure you have enough GPU RAM to fit the quantized model. If you want to dispatch the model on the CPU or the disk while keeping these modules in 32-bit, you need to set `llm_int8_enable_fp32_cpu_offload=True` and pass a custom `device_map` to `from_pretrained`. Check https://huggingface.co/docs/transformers/main/en/main_classes/quantization#offload-between-cpu-and-gpu for more details. ); falling back to eager attention.
Traceback (most recent call last):
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\train_shared.py", line 461, in load_base_model
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
    ...<4 lines>...
        attn_implementation="sdpa",
    )
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\models\auto\auto_factory.py", line 387, in from_pretrained
    return model_class.from_pretrained(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        pretrained_model_name_or_path, *model_args, config=config, **hub_kwargs, **kwargs
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\modeling_utils.py", line 4116, in from_pretrained
    device_map = _get_device_map(model, device_map, max_memory, hf_quantizer)
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\integrations\accelerate.py", line 373, in _get_device_map
    hf_quantizer.validate_environment(device_map=device_map)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\quantizers\quantizer_bnb_4bit.py", line 74, in validate_environment
    raise ValueError(
    ...<6 lines>...
    )
ValueError: Some modules are dispatched on the CPU or the disk. Make sure you have enough GPU RAM to fit the quantized model. If you want to dispatch the model on the CPU or the disk while keeping these modules in 32-bit, you need to set `llm_int8_enable_fp32_cpu_offload=True` and pass a custom `device_map` to `from_pretrained`. Check https://huggingface.co/docs/transformers/main/en/main_classes/quantization#offload-between-cpu-and-gpu for more details.

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\run_training_sequence.py", line 215, in train_one_with_retries
    return _train_attempt(name, dataset, reward_fn, output_dir, tokenizer, num_gen)
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\run_training_sequence.py", line 147, in _train_attempt
    model = load_base_model(HF_MODEL_ID)
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\train_shared.py", line 471, in load_base_model
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
    ...<4 lines>...
        attn_implementation="eager",
    )
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\models\auto\auto_factory.py", line 387, in from_pretrained
    return model_class.from_pretrained(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        pretrained_model_name_or_path, *model_args, config=config, **hub_kwargs, **kwargs
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\modeling_utils.py", line 4116, in from_pretrained
    device_map = _get_device_map(model, device_map, max_memory, hf_quantizer)
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\integrations\accelerate.py", line 373, in _get_device_map
    hf_quantizer.validate_environment(device_map=device_map)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\quantizers\quantizer_bnb_4bit.py", line 74, in validate_environment
    raise ValueError(
    ...<6 lines>...
    )
ValueError: Some modules are dispatched on the CPU or the disk. Make sure you have enough GPU RAM to fit the quantized model. If you want to dispatch the model on the CPU or the disk while keeping these modules in 32-bit, you need to set `llm_int8_enable_fp32_cpu_offload=True` and pass a custom `device_map` to `from_pretrained`. Check https://huggingface.co/docs/transformers/main/en/main_classes/quantization#offload-between-cpu-and-gpu for more details.

[KIRA] Marked failed; continuing to next model.

############################################################
  TRAINING: ADMIN  (num_generations=4)
  Examples: 8,002
  Output:   C:\Users\hac23\PycharmProjects\Veridict\outputs\admin_adapter
############################################################

  Loading google/gemma-3-27b-it in 4-bit NF4 ...
  SDPA attention failed (Some modules are dispatched on the CPU or the disk. Make sure you have enough GPU RAM to fit the quantized model. If you want to dispatch the model on the CPU or the disk while keeping these modules in 32-bit, you need to set `llm_int8_enable_fp32_cpu_offload=True` and pass a custom `device_map` to `from_pretrained`. Check https://huggingface.co/docs/transformers/main/en/main_classes/quantization#offload-between-cpu-and-gpu for more details. ); falling back to eager attention.
Traceback (most recent call last):
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\train_shared.py", line 461, in load_base_model
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
    ...<4 lines>...
        attn_implementation="sdpa",
    )
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\models\auto\auto_factory.py", line 387, in from_pretrained
    return model_class.from_pretrained(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        pretrained_model_name_or_path, *model_args, config=config, **hub_kwargs, **kwargs
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\modeling_utils.py", line 4116, in from_pretrained
    device_map = _get_device_map(model, device_map, max_memory, hf_quantizer)
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\integrations\accelerate.py", line 373, in _get_device_map
    hf_quantizer.validate_environment(device_map=device_map)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\quantizers\quantizer_bnb_4bit.py", line 74, in validate_environment
    raise ValueError(
    ...<6 lines>...
    )
ValueError: Some modules are dispatched on the CPU or the disk. Make sure you have enough GPU RAM to fit the quantized model. If you want to dispatch the model on the CPU or the disk while keeping these modules in 32-bit, you need to set `llm_int8_enable_fp32_cpu_offload=True` and pass a custom `device_map` to `from_pretrained`. Check https://huggingface.co/docs/transformers/main/en/main_classes/quantization#offload-between-cpu-and-gpu for more details.

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\run_training_sequence.py", line 215, in train_one_with_retries
    return _train_attempt(name, dataset, reward_fn, output_dir, tokenizer, num_gen)
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\run_training_sequence.py", line 147, in _train_attempt
    model = load_base_model(HF_MODEL_ID)
  File "C:\Users\hac23\PycharmProjects\Veridict\scripts\train_shared.py", line 471, in load_base_model
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
    ...<4 lines>...
        attn_implementation="eager",
    )
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\models\auto\auto_factory.py", line 387, in from_pretrained
    return model_class.from_pretrained(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        pretrained_model_name_or_path, *model_args, config=config, **hub_kwargs, **kwargs
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\modeling_utils.py", line 4116, in from_pretrained
    device_map = _get_device_map(model, device_map, max_memory, hf_quantizer)
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\integrations\accelerate.py", line 373, in _get_device_map
    hf_quantizer.validate_environment(device_map=device_map)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\hac23\PycharmProjects\Veridict\.venv\Lib\site-packages\transformers\quantizers\quantizer_bnb_4bit.py", line 74, in validate_environment
    raise ValueError(
    ...<6 lines>...
    )
ValueError: Some modules are dispatched on the CPU or the disk. Make sure you have enough GPU RAM to fit the quantized model. If you want to dispatch the model on the CPU or the disk while keeping these modules in 32-bit, you need to set `llm_int8_enable_fp32_cpu_offload=True` and pass a custom `device_map` to `from_pretrained`. Check https://huggingface.co/docs/transformers/main/en/main_classes/quantization#offload-between-cpu-and-gpu for more details.

[ADMIN] Marked failed; continuing to next model.

============================================================
TRAINING SEQUENCE COMPLETE — SUMMARY
============================================================
Model        JSON Valid   Issue Type     Severity     Status
---------- ------------ ------------ ------------ ----------
HARVEY                -            -            -      ERROR
KIRA                  -            -            -      ERROR
ADMIN                 -            -            -      ERROR

Report written to C:\Users\hac23\PycharmProjects\Veridict\outputs\TRAINING_REPORT.md

Total wall-clock: 1259.7 min
Report: C:\Users\hac23\PycharmProjects\Veridict\outputs\TRAINING_REPORT.md