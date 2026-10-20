import logging
import sys

logger = logging.getLogger(__name__)

BUTTON_SIZE = 24
BUTTON_GAP = 6

_target_class = None
_content_view_class = None
_installed = []


def add_buttons(native_window, buttons):
    if sys.platform != "darwin" or native_window is None or not buttons:
        return
    try:
        from PyObjCTools import AppHelper
    except ImportError:
        return
    AppHelper.callAfter(_install, native_window, buttons)


def _install(native_window, buttons):
    try:
        import AppKit

        width = BUTTON_GAP + len(buttons) * (BUTTON_SIZE + BUTTON_GAP)
        container = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, width, 28))
        targets = []
        for index, (symbol, tooltip, on_click) in enumerate(buttons):
            image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, tooltip)
            target = new_target(on_click)
            button = AppKit.NSButton.buttonWithImage_target_action_(image, target, "performClick:")
            button.setBordered_(False)
            button.setToolTip_(tooltip)
            x = BUTTON_GAP + index * (BUTTON_SIZE + BUTTON_GAP)
            button.setFrame_(AppKit.NSMakeRect(x, 2, BUTTON_SIZE, BUTTON_SIZE))
            container.addSubview_(button)
            targets.append(target)
        accessory = AppKit.NSTitlebarAccessoryViewController.alloc().init()
        accessory.setView_(container)
        accessory.setLayoutAttribute_(AppKit.NSLayoutAttributeTrailing)
        native_window.addTitlebarAccessoryViewController_(accessory)
        _installed.append((targets, accessory))
    except Exception:
        logger.exception("Cannot add buttons to the title bar")
    _pin_content_below_titlebar(native_window)


def _pin_content_below_titlebar(native_window):
    try:
        import AppKit
        from webview.platforms.cocoa import BrowserView

        instance = BrowserView.get_instance("window", native_window)
        if instance is None:
            return
        webview = instance.webview
        container = new_content_view(native_window.contentView().frame())
        webview.removeFromSuperview()
        native_window.setContentView_(container)
        container.addSubview_(webview)
        container.layoutContent()
        native_window.makeFirstResponder_(webview)
    except Exception:
        logger.exception("Cannot pin the content below the title bar")


def new_content_view(frame):
    global _content_view_class
    if _content_view_class is None:
        import AppKit

        class EzyOCRContentView(AppKit.NSView):
            def resizeSubviewsWithOldSize_(self, old_size):
                self.layoutContent()

            def layoutContent(self):
                bounds = self.bounds()
                height = bounds.size.height
                window = self.window()
                if window is not None:
                    layout_rect = self.convertRect_fromView_(window.contentLayoutRect(), None)
                    height = max(0, min(height, AppKit.NSMaxY(layout_rect)))
                frame = AppKit.NSMakeRect(0, 0, bounds.size.width, height)
                for subview in self.subviews():
                    subview.setFrame_(frame)

        _content_view_class = EzyOCRContentView
    return _content_view_class.alloc().initWithFrame_(frame)


def new_target(on_click):
    global _target_class
    if _target_class is None:
        from Foundation import NSObject

        class EzyOCRTitlebarTarget(NSObject):
            def performClick_(self, sender):
                self.callback()

        _target_class = EzyOCRTitlebarTarget
    target = _target_class.alloc().init()
    target.callback = on_click
    return target
