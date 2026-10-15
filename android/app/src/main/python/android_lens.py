"""Keep the native detector's blocking NPU calls off the HTTP event loop."""
import ast


def offload_detector(tree):
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'google_lens_ocr')
    class Offload(ast.NodeTransformer):
        count = 0
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == '_detect_yolo_text_boxes':
                self.count += 1
                assert len(node.args) == 1 and not node.keywords
                call = ast.parse('await asyncio.get_running_loop().run_in_executor(_OCR_BOX_EXECUTOR, _detect_yolo_text_boxes, pil_img)', mode='eval').body
                call.value.args[-1] = node.args[0]
                return ast.copy_location(call, node)
            return self.generic_visit(node)
    transform = Offload()
    transform.visit(function)
    assert transform.count == 1, 'Upstream Lens detector call changed'
    ast.fix_missing_locations(tree)
