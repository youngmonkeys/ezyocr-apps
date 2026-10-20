import logging
import sys

from ezyocr.titlebar import new_target

logger = logging.getLogger(__name__)

_state = {
    "camera_title": None,
    "camera_titles": (),
    "about": None,
    "about_target": None,
    "patched": False,
}


def dynamic_titles():
    return sys.platform == "darwin"


def install_about(on_click):
    if sys.platform != "darwin":
        return
    _state["about"] = on_click
    _patch_recreate_menus()


def install_camera_title(title, all_titles):
    if sys.platform != "darwin":
        return
    _state["camera_title"] = title
    _state["camera_titles"] = tuple(all_titles)
    _patch_recreate_menus()


def set_camera_title(title):
    if sys.platform != "darwin":
        return
    try:
        from PyObjCTools import AppHelper
    except ImportError:
        return
    _state["camera_title"] = title
    AppHelper.callAfter(_update_camera_title)


def _patch_recreate_menus():
    if _state["patched"]:
        return
    try:
        from webview.platforms.cocoa import BrowserView
    except ImportError:
        return
    recreate_menus = BrowserView._recreate_menus

    def _recreate_menus(browser_view, user_menu):
        main_menu = recreate_menus(browser_view, user_menu)
        _attach_about(main_menu)
        _retitle_camera(main_menu)
        return main_menu

    BrowserView._recreate_menus = _recreate_menus
    _state["patched"] = True


def _update_camera_title():
    try:
        import AppKit

        main_menu = AppKit.NSApplication.sharedApplication().mainMenu()
        if main_menu is not None:
            _retitle_camera(main_menu)
    except Exception:
        logger.exception("Cannot update the camera menu item")


def _retitle_camera(main_menu):
    title = _state["camera_title"]
    if title is None:
        return
    try:
        for item in main_menu.itemArray():
            submenu = item.submenu()
            if submenu is None:
                continue
            for child in submenu.itemArray():
                if child.title() in _state["camera_titles"]:
                    child.setTitle_(title)
                    return
    except Exception:
        logger.exception("Cannot update the camera menu item")


def _attach_about(main_menu):
    if _state["about"] is None:
        return
    try:
        app_item = _find_item_with_action(main_menu, "orderFrontStandardAboutPanel:")
        if app_item is None:
            return
        app_menu = app_item.submenu()
        index = app_menu.indexOfItemWithTarget_andAction_(None, "orderFrontStandardAboutPanel:")
        if index < 0:
            return
        item = app_menu.itemAtIndex_(index)
        if _state["about_target"] is None:
            _state["about_target"] = new_target(_state["about"])
        item.setTarget_(_state["about_target"])
        item.setAction_("performClick:")
    except Exception:
        logger.exception("Cannot customize the About menu item")


def _find_item_with_action(main_menu, action):
    for item in main_menu.itemArray():
        submenu = item.submenu()
        if submenu is None:
            continue
        for child in submenu.itemArray():
            name = child.action()
            if isinstance(name, bytes):
                name = name.decode()
            if name == action:
                return item
    return None
