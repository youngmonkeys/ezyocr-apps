import html
import logging
import re
import sys
import threading

logger = logging.getLogger(__name__)

PRINT_WINDOW_SIZE = (480, 640)

PRINT_SHIM_JS = """
(function() {
    if (window.__ezyocrPrintShim || !window.pywebview) {
        return;
    }
    window.__ezyocrPrintShim = true;
    var nativeOpen = window.open;
    window.open = function(url) {
        if (url && url !== 'about:blank') {
            return nativeOpen.apply(window, arguments);
        }
        var chunks = [];
        var printWindow = {
            closed: false,
            onafterprint: null,
            document: {
                open: function() { chunks = []; },
                write: function() { chunks.push(Array.prototype.join.call(arguments, '')); },
                writeln: function() { chunks.push(Array.prototype.join.call(arguments, '') + '\\n'); },
                close: function() {}
            },
            focus: function() {},
            close: function() { printWindow.closed = true; },
            print: function() {
                window.pywebview.api.print_html(chunks.join(''), window.location.href).then(function() {
                    if (typeof printWindow.onafterprint === 'function') {
                        printWindow.onafterprint();
                    }
                });
            }
        };
        return printWindow;
    };
})();
"""

_delegate_class = None
_pending = {}


def add_base_url(content, base_url):
    if not base_url or re.search(r"<base\s", content, re.IGNORECASE):
        return content
    tag = f'<base href="{html.escape(base_url, quote=True)}">'
    match = re.search(r"<head[^>]*>", content, re.IGNORECASE)
    if match:
        return content[:match.end()] + tag + content[match.end():]
    return tag + content


def print_window(window, settings):
    if sys.platform != "darwin":
        window.run_js("window.print()")
        return
    from PyObjCTools import AppHelper

    AppHelper.callAfter(_run_print_operation, window, settings)


def _run_print_operation(window, settings):
    try:
        import AppKit

        webview = window.native.contentView()
        info = AppKit.NSPrintInfo.sharedPrintInfo().copy()
        info.setHorizontalPagination_(AppKit.NSFitPagination)
        info.setHorizontallyCentered_(False)
        info.setVerticallyCentered_(False)
        info.setTopMargin_(0)
        info.setBottomMargin_(0)
        info.setLeftMargin_(0)
        info.setRightMargin_(0)
        if settings.page_printer_name:
            printer = AppKit.NSPrinter.printerWithName_(settings.page_printer_name)
            if printer is not None:
                info.setPrinter_(printer)
            else:
                logger.warning("Printer %s not found, using the default printer", settings.page_printer_name)
        operation = webview._printOperationWithPrintInfo_(info)
        operation.setShowsPrintPanel_(settings.show_print_dialog)
        operation.setShowsProgressPanel_(settings.show_print_dialog)
        delegate = _get_delegate_class().alloc().init()
        _pending[id(delegate)] = (delegate, window)
        operation.runOperationModalForWindow_delegate_didRunSelector_contextInfo_(
            window.native,
            delegate,
            b"printOperationDidRun:success:contextInfo:",
            None,
        )
    except Exception:
        logger.exception("Cannot print page")
        _close(window)


def _get_delegate_class():
    global _delegate_class
    if _delegate_class is None:
        import objc
        from Foundation import NSObject

        class EzyOCRPrintDelegate(NSObject):
            @objc.typedSelector(b"v@:@Z^v")
            def printOperationDidRun_success_contextInfo_(self, operation, success, context):
                _, window = _pending.pop(id(self), (None, None))
                if not success:
                    logger.info("Printing was cancelled or failed")
                if window is not None:
                    _close(window)

        _delegate_class = EzyOCRPrintDelegate
    return _delegate_class


def _close(window):
    threading.Thread(target=window.destroy, name="print-window-close", daemon=True).start()
