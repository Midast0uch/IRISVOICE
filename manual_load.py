import asyncio, pathlib
from backend.agent.local_model_manager import get_local_model_manager

async def main():
    mgr = get_local_model_manager()
    print("is_loaded before:", mgr.is_loaded())
    print("effective_models_dir:", mgr.effective_models_dir)
    path = r"C:\Users\midas\.lmstudio\models\lmstudio-community\Bonsai-27B-GGUF\Bonsai-27B-Q1_0.gguf"
    print("exists?", pathlib.Path(path).exists())
    # Try to load with progress callback
    async def cb(evt):
        print(f"progress {evt.get('pct')}% {evt.get('phase')} {evt.get('msg')}")
    try:
        ok = await mgr.load_model(path, profile="balanced", progress_cb=cb)
        print("load result:", ok)
        print("is_loaded after:", mgr.is_loaded())
        print("status:", mgr.get_status())
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
