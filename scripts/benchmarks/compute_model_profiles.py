#!/usr/bin/env python3
"""
Compute optimal inference profiles for all local GGUF models.
Run from repo root: python scripts/compute_model_profiles.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "agent"))

from local_model_manager import LocalModelManager


def compute_profile(model: dict, hw: dict) -> dict:
    """Compute optimal profile for a model given hardware constraints."""
    vram_free = hw.get("vram_free_gb", 0.0)
    ram_free = hw.get("ram_free_gb", 16.0)  # fallback
    cuda = hw.get("cuda_available", False)
    
    file_gb = model.get("size_gb", 0.0)
    params_b = model.get("params_b", 0)
    quant = model.get("quantization", "Q4_K_M")
    is_mtp = model.get("is_mtp_capable", False)
    total_layers = model.get("block_count", 0)
    if not total_layers and params_b:
        total_layers = max(24, int(params_b * 2.5))
    
    # Target contexts to test
    contexts = [32768, 49152, 65536]
    
    profiles = []
    for n_ctx in contexts:
        # Estimate KV cache: ~2 bytes * n_ctx * n_layers / 1GB
        kv_gb = (n_ctx / 1000.0) * 0.1
        
        if cuda and vram_free > 0:
            # GPU path: find max layers that fit in VRAM
            # weights on GPU + KV cache on GPU
            avail_vram = vram_free * 0.70  # 30% headroom for OS + other apps
            
            if file_gb * 1.05 + kv_gb <= avail_vram:
                # All layers fit
                n_gpu_layers = -1
                vram_used = file_gb * 1.05 + kv_gb
            else:
                # Partial offload: solve for max layers
                # weight per layer ≈ file_gb / total_layers
                layer_weight = file_gb / total_layers if total_layers else file_gb / 32
                # n_gpu_layers * layer_weight * 1.05 + kv_gb <= avail_vram
                max_layers = int((avail_vram - kv_gb) / (layer_weight * 1.05))
                n_gpu_layers = max(0, min(max_layers, total_layers))
                vram_used = n_gpu_layers * layer_weight * 1.05 + kv_gb if n_gpu_layers > 0 else 0
            
            # CPU RAM needed for remaining layers (with mmap, ~25%)
            cpu_frac = 1.0 - (n_gpu_layers / total_layers if total_layers else 0)
            ram_needed = file_gb * cpu_frac * 0.25 + kv_gb * cpu_frac
            
            fits = vram_used <= avail_vram and ram_needed <= ram_free * 0.85
            
            # Estimate tok/s (very rough heuristics)
            if n_gpu_layers == -1:
                base_tps = 35.0  # All GPU
            elif n_gpu_layers > total_layers * 0.5:
                base_tps = 25.0  # Most on GPU
            elif n_gpu_layers > 0:
                base_tps = 15.0  # Partial GPU
            else:
                base_tps = 3.0   # CPU only
            
            # Context penalty: larger context = slower
            ctx_penalty = max(0.6, 1.0 - (n_ctx / 100000.0) * 0.3)
            est_tps = base_tps * ctx_penalty
            
        else:
            # CPU only
            n_gpu_layers = 0
            vram_used = 0
            ram_needed = file_gb * 0.25 + kv_gb
            fits = ram_needed <= ram_free * 0.85
            est_tps = 2.0 * max(0.6, 1.0 - (n_ctx / 100000.0) * 0.3)
        
        profile = {
            "n_ctx": n_ctx,
            "n_gpu_layers": n_gpu_layers,
            "flash_attn": True,
            "cache_type_k": "q8_0",
            "cache_type_v": "q8_0",
            "n_batch": 2048,
            "use_mmap": True,
            "offload_kv_cache": n_gpu_layers != 0,
        }
        
        if is_mtp:
            profile["mtp_n_max"] = 3
            profile["mtp_p_min"] = 0.75
            profile["force_subprocess"] = True
        
        profiles.append({
            "context": n_ctx,
            "fits": fits,
            "vram_used_gb": round(vram_used, 1),
            "ram_needed_gb": round(ram_needed, 1),
            "est_tok_per_sec": round(est_tps, 1),
            "profile": profile,
        })
    
    return profiles


def main():
    mgr = LocalModelManager()
    hw = mgr.get_hardware_info(force_refresh=True)
    
    print("=" * 70)
    print("HARDWARE INFO")
    print("=" * 70)
    print(f"  CUDA Available: {hw.get('cuda_available', False)}")
    print(f"  GPU: {hw.get('gpu_name', 'N/A')}")
    print(f"  VRAM Total: {hw.get('vram_total_gb', 0):.1f} GB")
    print(f"  VRAM Free: {hw.get('vram_free_gb', 0):.1f} GB")
    print(f"  CPU: {hw.get('cpu', 'N/A')}")
    print()
    
    models = mgr.scan_models()
    print(f"MODELS FOUND: {len(models)}")
    print()
    
    for m in models:
        if m.get("architecture") == "unknown" and not m.get("params_b"):
            continue  # Skip non-model files (projectors, etc)
        
        print("=" * 70)
        print(f"MODEL: {m['display_name']}")
        print(f"  File: {m['path']}")
        print(f"  Size: {m['size_gb']} GB")
        print(f"  Params: {m['params_b']}B")
        print(f"  Quant: {m['quantization']}")
        print(f"  Architecture: {m['architecture']}")
        print(f"  MTP Capable: {m.get('is_mtp_capable', False)}")
        print()
        
        profiles = compute_profile(m, hw)
        
        print("  OPTIMAL PROFILES:")
        print(f"  {'Context':<10} {'GPU Layers':<12} {'VRAM(GB)':<10} {'RAM(GB)':<10} {'Est tok/s':<10} {'Fits':<6}")
        print(f"  {'-'*10} {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*6}")
        
        best_profile = None
        best_ctx = 0
        for p in profiles:
            fits_str = "YES" if p["fits"] else "NO"
            gpu_str = "all" if p["profile"]["n_gpu_layers"] == -1 else str(p["profile"]["n_gpu_layers"])
            print(f"  {p['context']:<10} {gpu_str:<12} {p['vram_used_gb']:<10.1f} {p['ram_needed_gb']:<10.1f} {p['est_tok_per_sec']:<10.1f} {fits_str:<6}")
            
            if p["fits"] and p["context"] > best_ctx and p["est_tok_per_sec"] >= 25:
                best_ctx = p["context"]
                best_profile = p
        
        if best_profile:
            print()
            print(f"  RECOMMENDED: {best_ctx} context, {best_profile['est_tok_per_sec']:.1f} tok/s")
            print(f"  Profile params: {best_profile['profile']}")
        elif profiles[0]["fits"]:
            print()
            print(f"  WARNING: Model fits but tok/s < 25. Best: {profiles[0]['est_tok_per_sec']:.1f} tok/s at {profiles[0]['context']}")
        else:
            print()
            print("  WARNING: Model does not fit available memory!")
        
        # Swarm capacity: how many instances fit with 30% OS headroom
        vram_total = hw.get("vram_total_gb", 0)
        os_reserve = vram_total * 0.30  # Leave 30% for OS + other apps
        avail_for_models = vram_total - os_reserve
        
        usable = [p for p in profiles if p["fits"]]
        if usable:
            # GPU-optimized swarm (using best profile that hits >=25 tok/s)
            best_gpu = None
            for p in reversed(usable):  # Prefer larger contexts
                if p["est_tok_per_sec"] >= 25 and p["vram_used_gb"] > 0:
                    best_gpu = p
            if not best_gpu:
                best_gpu = max(usable, key=lambda x: x["est_tok_per_sec"])
            
            gpu_vram = max(best_gpu["vram_used_gb"], 0.5)
            gpu_instances = int(avail_for_models / gpu_vram)
            
            print()
            print(f"  SWARM CAPACITY (RTX 3070 8GB, 30% OS reserve = {os_reserve:.1f}GB):")
            print(f"    GPU-optimized instances: {gpu_instances} (each ~{gpu_vram:.1f}GB VRAM)")
            print(f"    Combined tok/s (estimate): {gpu_instances * best_gpu['est_tok_per_sec']:.1f}")
            
            # CPU-only fallback (if different)
            cpu_profiles = [p for p in usable if p["vram_used_gb"] == 0]
            if cpu_profiles:
                cpu_instances = int(16.0 / 2.0)  # 16GB RAM, ~2GB per CPU model
                print(f"    CPU-only instances: ~{cpu_instances} (each ~2.0GB RAM)")
        
        print()


if __name__ == "__main__":
    main()
