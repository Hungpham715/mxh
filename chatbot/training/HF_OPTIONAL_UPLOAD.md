# Optional private Hugging Face upload

The runtime does not require an upload. Keep `adapter_config.json` and adapter weights in a local ignored
directory and select `LLM_PROVIDER=hf_cpu`.

If the owner later approves an upload, create a private model repository, set `HF_TOKEN` only in the local
environment, authenticate with the Hugging Face CLI, and upload the validated adapter directory. Confirm the
repository is private before transferring any artifact. The project never hardcodes a handle/token and no
script uploads automatically.

