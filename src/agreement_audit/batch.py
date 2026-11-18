"""
Runs many documents in parallel with progress logs, error capture and a same-run retry for
temporary failures. Used by both the Google Sheets runner and the local-folder CLI.
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import SETTINGS
from .errors import FatalError, RowError

TEMPORARY = re.compile(r"(?i)timeout|network error|API (429|5\d\d)|Download failed \(HTTP (429|5\d\d)\)")


def run_jobs(jobs, process, on_result, on_error, s=SETTINGS):
    """
    jobs:      list of (key, payload, attempts)
    process:   payload -> AuditResult
    on_result: (key, AuditResult) -> None
    on_error:  (key, message, attempts) -> None
    """
    stop = threading.Event()
    stats = {"done": 0, "error": 0}
    t0 = time.time()

    def work(job):
        key, payload, attempts = job
        if stop.is_set():
            return key, "skipped", ""
        start = time.time()
        try:
            res = process(payload)
            on_result(key, res)
            return key, "done", (f"{res.society_name} | Stamped: {res.is_stamped} | Signed: {res.is_signed} | "
                                 f"{time.time() - start:.1f}s | {res.notes}")
        except FatalError as e:
            stop.set()
            return key, "fatal", str(e)
        except Exception as e:
            msg = str(e) if isinstance(e, RowError) else f"{e.__class__.__name__}: {e}"
            on_error(key, msg, attempts)
            return key, "error", msg

    def run_batch(batch):
        retry = []
        ex = ThreadPoolExecutor(max_workers=s.max_workers)
        futures = {ex.submit(work, j): j for j in batch}
        try:
            for i, fut in enumerate(as_completed(futures), 1):
                key, status, info = fut.result()
                if status == "done":
                    stats["done"] += 1
                    print(f"✅ [{i}/{len(batch)}] {key}: {info}")
                elif status == "error":
                    stats["error"] += 1
                    print(f"⚠️ [{i}/{len(batch)}] {key}: {info}")
                    k0, p0, a0 = futures[fut]
                    if TEMPORARY.search(info) and a0 + 1 < s.max_attempts:
                        retry.append((k0, p0, a0 + 1))
                elif status == "fatal":
                    print(f"🛑 {key}: {info}\nStopping - fix the key/credits and run again.")
        except KeyboardInterrupt:
            stop.set()
            print("\n⏹ Stopped. Finished items are saved; run again to continue.")
        finally:
            ex.shutdown(wait=True, cancel_futures=True)
        return retry

    print(f"📄 {len(jobs)} item(s) to process\n")
    retry = run_batch(jobs)
    if s.retry_errors_same_run and retry and not stop.is_set():
        print(f"\n🔁 {len(retry)} item(s) hit a timeout / busy error. Waiting 60s, then retrying once...")
        time.sleep(60)
        stats["error"] -= len(retry)
        run_batch(retry)

    print(f"\nFinished in {(time.time() - t0) / 60:.1f} min → {stats['done']} done, {stats['error']} error(s).")
    return stats
