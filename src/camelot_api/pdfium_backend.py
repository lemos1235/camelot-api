"""显式管理 PDFium 渲染资源；调用方必须串行化 PDFium 操作。"""

from __future__ import annotations

from contextlib import ExitStack, closing, contextmanager

from camelot.backends import image_conversion, pdfium_backend


@contextmanager
def managed_pdfium_backend():
    """临时替换默认渲染器；调用方必须在持有提取锁时进入此上下文。

    Hybrid 不转发 backend 参数，而 auto 的探测也自行创建转换器，因此在
    注册项处统一适配，同时保留 Camelot 原有的回退顺序和错误处理。
    """
    original = image_conversion.BACKENDS["pdfium"]
    image_conversion.BACKENDS["pdfium"] = ManagedPdfiumBackend
    try:
        yield
    finally:
        image_conversion.BACKENDS["pdfium"] = original


class ManagedPdfiumBackend(pdfium_backend.PdfiumBackend):
    """保持页面和位图存活，并在正常/异常路径上按逆序释放资源。"""

    @contextmanager
    def _render_image(self, pdf_path: str, resolution: int, page: int):
        if not self.installed():
            raise OSError(f"pypdfium2 is not available: {pdfium_backend.PDFIUM_EXC!r}")

        with ExitStack() as stack:
            doc = pdfium_backend.pdfium.PdfDocument(pdf_path)
            stack.callback(doc.close)
            doc.init_forms()
            pdf_page = doc[page - 1]
            stack.callback(pdf_page.close)
            bitmap = pdf_page.render(scale=resolution / 72)
            stack.callback(bitmap.close)
            image = bitmap.to_pil()
            stack.callback(image.close)
            # PIL 可能共享位图内存，必须在图像消费完成之后才释放位图。
            yield image

    def convert(
        self, pdf_path: str, png_path: str, resolution: int = 300, page: int = 1
    ) -> None:
        with self._render_image(pdf_path, resolution, page) as image:
            image.save(png_path)

    def to_array(self, pdf_path: str, resolution: int = 300, page: int = 1):
        import numpy as np

        with self._render_image(pdf_path, resolution, page) as image:
            with closing(image.convert("RGB")) as rgb_image:
                # 数组必须拥有独立内存，不能返回已释放位图的视图。
                rgb = np.array(rgb_image, dtype=np.uint8)
                return np.ascontiguousarray(rgb[:, :, ::-1])
