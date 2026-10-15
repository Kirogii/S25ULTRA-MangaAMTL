# Manga inpainting on the S25 Ultra

Source: https://huggingface.co/df1412/anime-big-lama/resolve/main/anime-manga-big-lama.pt (model card: https://huggingface.co/df1412/anime-big-lama). The uploader describes it as Big LaMa fine-tuned on anime/manga and labels the repository MIT. Keep the upstream attribution when distributing model packs.

`export_anime_lama.py` preserves the checkpoint weights. It replaces complex Fourier operators with separable real matrix multiplication and reflection padding with equivalent gathers, using fixed 512×512 inputs. It checks the architecture and compares exported output against the original TorchScript model. `split_anime_lama.py` partitions at existing residual-block boundaries and verifies the composed result against that same reference.

The unsplit graph exceeded the phone's compilation memory budget. Larger partitions also exceeded it. The smaller partitions compile independently, and `AnimePipeline` keeps one QNN session resident at a time. CPU fallback is explicitly disabled; a missing QNN delegation or unexpected provider is an error. Original crop selection, flat-color fill, blending, font sizing and drawing remain in the original renderer.

## Current status: validated and installed

The first partitioned conversion failed NPU fidelity because intermediate Fourier values overflowed. Scaling each Fourier axis separately and reducing the internal network resolution to 256 pixels fixed this. The installed 27-stage compiled model passes NPU fidelity: mean absolute error 0.000166617, maximum 0.00674385. Every neural stage delegates to QNN, with CPU fallback disabled.

On October 13, 2026, a diagnostic precompilation pass using three concurrent QNN sessions caused the app to crash from memory exhaustion. The phone stayed on. The test was force-stopped and concurrent precompilation was removed.

The reduced-resolution variant uses the original weights at 256×256 internally, retaining the app's 512×512 tensor interface. Average pooling reduces the image, max pooling preserves small masked regions, bilinear interpolation restores the painted image, and the original pixels are retained outside the mask. This reduces spatial activations to one quarter at corresponding network layers; it does not reduce weight storage or establish a fourfold reduction in total RAM. Export and 27 separately evaluated partitions match this reduced-resolution reference within 0.000002713 maximum error on the host. This checks conversion accuracy, not manga restoration quality.

`AnimePipeline` now releases intermediate tensors once no future stage needs them. Its sequential sessions still forbid CPU fallback. The reduced-resolution graph also separates encoder and decoder layers, rather than compiling each whole section together.

Guarded compilation experiments exceeded development memory limits before using fast QNN graph preparation. The corrected 27-stage version then compiled and passed on the phone. The deployed pack contains those compiled contexts, so ordinary use does not compile raw ONNX graphs. The diagnostic monitor currently stops above 2.5 GiB PSS, 3 GiB RSS, below 2.5 GiB available memory, or on timeout/monitoring failure. Sampling can overshoot, so this is not a hard allocator limit.

`prepare_models.py --anime-lama` requires the successful device fidelity report and collected compiled contexts before packaging. Those contexts are available in `models/anime-npu` and are used by the installed OCR + inpainting build. `AnimePipeline.Cached` reuses them across crops, closes consumed intermediate results, and checks each session's QNN profile once. Warm inference measured 0.247–0.248 seconds with approximately 300–333 MB PSS in the native test. See `SPEED.md` and `evidence/speed/` for end-to-end measurements. This is specific to this chipset/runtime; Samsung translation's internal NPU use remains unverified.
