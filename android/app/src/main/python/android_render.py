"""Keep cold NPU rendering out of short-lived extension worker requests."""
import asyncio
import time
from collections import OrderedDict
from functools import wraps
import hashlib
import json


def install_image_cache(module):
    """Reuse deterministic completed renders without retaining page objects."""
    original = module._render_translated_image
    images, total_bytes = OrderedDict(), 0

    def key(job):
        mode = module._inpaint_mode
        fingerprint = job.get('request_fingerprint')
        if mode not in {'blur', 'none'} or not fingerprint or job['result'].get('style_aware'):
            return None
        metadata = dict(result=job['result'], target=job['target_lang'],
            inpaint=job.get('inpaint', True), skip_sfx=job.get('skip_sfx', False),
            ocr=job.get('ocr_mode', module._ocr_mode), mode=mode,
            font=str(module._current_font_path), stroke=module._current_stroke_width,
            font_revision=getattr(module, '_android_font_revision', 0))
        digest = hashlib.blake2b(json.dumps(metadata, sort_keys=True, ensure_ascii=False).encode('utf-8'), digest_size=16).digest()
        return fingerprint, digest

    @wraps(original)
    async def render(job_id, job):
        nonlocal total_bytes
        await module._ensure_job_active(job_id)
        identity = key(job)
        cached = images.get(identity) if identity is not None else None
        if cached is not None:
            images.move_to_end(identity)
            await module._ensure_job_active(job_id)
            module.logging.info('[Render cache] Exact completed image hit')
            return module.Response(content=cached, media_type='image/png')
        response = await original(job_id, job)
        if identity is not None and response.status_code == 200 and key(job) == identity:
            content = response.body
            if len(content) <= 16_000_000:
                old = images.pop(identity, None)
                if old is not None: total_bytes -= len(old)
                images[identity] = content; total_bytes += len(content)
                while len(images) > 8 or total_bytes > 16_000_000:
                    _, removed = images.popitem(last=False); total_bytes -= len(removed)
        return response

    module._render_translated_image = render


def install_status_wait(module):
    original = module._process_job

    async def process(job_id):
        try:
            return await original(job_id)
        finally:
            job = module._jobs.get(job_id)
            if job is not None and 'android_status_event' in job:
                job['android_status_event'].set()

    module._process_job = process


async def wait_status(module, job_id):
    """Wake the page when translation ends, bounded below worker timeouts."""
    job = module._jobs.get(job_id)
    if job is not None and job.get('status') in {'pending', 'processing'}:
        event = job.setdefault('android_status_event', asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass


def prune(module, now=None):
    """Keep recent delivered pages for retries without retaining a whole chapter's pixels."""
    now = time.time() if now is None else now
    delivered = []
    for key, job in list(module._jobs.items()):
        if job.get('rendering') or job.get('status') not in {'completed', 'failed', 'cancelled'}:
            continue
        age = now - job.get('last_health', job.get('created', now))
        if age > 120:
            removed = module._jobs.pop(key, None)
            if removed and removed.get('image') is not None: removed['image'].close()
        elif job.get('android_image_delivered'):
            page = job.get('image')
            delivered.append((key, job, 0 if page is None else page.width * page.height * 4))
    pixels = sum(item[2] for item in delivered)
    while len(delivered) > 8 or (pixels > 128_000_000 and len(delivered) > 1):
        key, job, size = delivered.pop(0)
        module._jobs.pop(key, None)
        if job.get('image') is not None: job['image'].close()
        pixels -= size


async def image(module, job_id):
    job = module._jobs.get(job_id)
    if job is None:
        return module.JSONResponse({"detail": "Job not found"}, status_code=404)
    if job.get("status") != "completed":
        return module.JSONResponse({"detail": "Job is not completed"}, status_code=409)
    task = job.get("android_render_task")
    if task is None:
        job["rendering"] = True
        async def render():
            try:
                return await module.get_translated_image(job_id)
            finally:
                job["rendering"] = False
        task = job["android_render_task"] = asyncio.create_task(render())
    if not task.done():
        # Finish warm renders in this request; cold renders retain the retry path.
        await asyncio.wait({task}, timeout=0.5)
    if not task.done():
        return module.JSONResponse({"status": "rendering"}, status_code=202, headers={"Retry-After": "2"})
    try:
        response = task.result()
        if response.status_code == 200: job['android_image_delivered'] = True
        return response
    except Exception as error:
        return module.JSONResponse({"detail": str(error)}, status_code=getattr(error, "status_code", 500))
