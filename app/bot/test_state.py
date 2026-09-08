"""Test holatini boshqarish (admin va user handlerlari uchun)"""

_test_active_global = False


def set_test_active(active: bool):
    global _test_active_global
    _test_active_global = active


def is_test_active() -> bool:
    return _test_active_global