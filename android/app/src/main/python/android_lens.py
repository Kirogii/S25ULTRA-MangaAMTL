"""Overlap native text detection with the Lens request without blocking HTTP."""
import ast
import copy
import time


def add_live_ocr(tree):
    """Keep GUI labels outside manga-trained YOLO boxes in live mode."""
    function = copy.deepcopy(next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'google_lens_ocr'))
    function.name = '_live_google_lens_ocr'
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_group_lens_blocks_by_yolo':
            node.func.id = '_live_group_lens_blocks_by_yolo'
    tree.body.append(function)
    ast.fix_missing_locations(tree)


def live_groups(group, blocks, boxes, size):
    grouped = group(blocks, boxes, size)
    used = {tuple(box) for region in grouped for box in region.get('bboxes', [region['bbox']])}
    return grouped + [block for block in blocks if tuple(block['bbox']) not in used]


def install_http_timing(module):
    """Separate the external Lens request from local preprocessing and grouping."""
    original_get_api = module.get_lens_api

    def get_api():
        api = original_get_api()
        handler = api.request_handler
        if not getattr(handler, '_mangaamtl_timed', False):
            original_post = handler.post_raw

            async def post(*args, **kwargs):
                started = time.perf_counter()
                try:
                    return await original_post(*args, **kwargs)
                finally:
                    module.logging.info('[Lens HTTP] %.3fs', time.perf_counter() - started)

            handler.post_raw = post
            handler._mangaamtl_timed = True
        return api

    module.get_lens_api = get_api


def offload_detector(tree):
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'google_lens_ocr')
    class Offload(ast.NodeTransformer):
        count = 0
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == '_detect_yolo_text_boxes':
                self.count += 1
                assert len(node.args) == 1 and not node.keywords
                assert isinstance(node.args[0], ast.Name) and node.args[0].id == 'pil_img'
                call = ast.parse('await _android_yolo_future', mode='eval').body
                return ast.copy_location(call, node)
            return self.generic_visit(node)
    transform = Offload()
    transform.visit(function)
    assert transform.count == 1, 'Upstream Lens detector call changed'
    start = ast.parse('_android_yolo_future = asyncio.get_running_loop().run_in_executor(_OCR_BOX_EXECUTOR, _detect_yolo_text_boxes, pil_img)').body
    cleanup = ast.parse('if not _android_yolo_future.done():\n _android_yolo_future.cancel()\nawait asyncio.gather(_android_yolo_future, return_exceptions=True)').body
    # Cancel abandoned futures on empty/failed Lens responses; native work already
    # running finishes on its executor. Successful calls still propagate NPU errors.
    function.body = start + [ast.Try(body=function.body, handlers=[], orelse=[], finalbody=cleanup)]
    ast.fix_missing_locations(tree)
