import asyncio
import threading


async def prepare_in_thread(func, *args, cancel_check=None, **kwargs):
    """Join cancellable file preparation before the caller closes or removes its files."""
    stopped = threading.Event()

    def cancelled():
        return stopped.is_set() or (cancel_check is not None and cancel_check())

    operation = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs, cancel_check=cancelled))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        stopped.set()
        await asyncio.gather(operation, return_exceptions=True)
        raise
