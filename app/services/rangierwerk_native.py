"""Small C ABI for the engine also compiled into the LEAP firmware."""
import ctypes as c
import os
from functools import lru_cache
from pathlib import Path

ENGINES = 4
VEHICLES = 24
ORDERS = 4
STEP_MS = 250


@lru_cache
def library(path):
    dll = c.CDLL(path)
    pointer, byte, word, number = c.c_void_p, c.c_uint8, c.c_uint32, c.c_int
    params = {
        "create": (pointer,), "destroy": (None, pointer),
        "reset": (c.c_bool, pointer, word, byte), "join": (c.c_bool, pointer, byte),
        "leave": (None, pointer, byte), "recover": (c.c_bool, pointer, byte),
        "order_count": (None, pointer, byte), "turnout": (c.c_bool, pointer, byte),
        "split": (c.c_bool, pointer, byte, word, word),
        "drive": (byte, pointer, byte, number), "tick": (None, pointer, word),
        "snapshot": (None, pointer, *([c.POINTER(word)] * 3)),
    }
    for name, (result, *args) in params.items():
        fn = getattr(dll, f"rw_{name}")
        fn.restype, fn.argtypes = result, args
    return dll


class Yard:
    def __init__(self):
        default = Path(__file__).resolve().parents[1] / "native" / "librangierwerk.so"
        path = os.environ.get("LEAP_RANGIERWERK_LIBRARY", str(default))
        self.dll = library(path)
        self.handle = self.dll.rw_create()
        if not self.handle:
            raise MemoryError("Rangierwerk yard allocation failed")
        self.header = (c.c_uint32 * 2)()
        self.vehicles = ((c.c_uint32 * 8) * VEHICLES)()
        self.orders = ((c.c_uint32 * 4) * ORDERS)()

    def close(self):
        if self.handle:
            self.dll.rw_destroy(self.handle)
            self.handle = None

    def reset(self, seed, difficulty):
        if not self.dll.rw_reset(self.handle, seed, difficulty):
            raise RuntimeError("Rangierwerk yard generation failed")

    def join(self, slot):
        return self.dll.rw_join(self.handle, slot)

    def leave(self, slot):
        self.dll.rw_leave(self.handle, slot)

    def recover(self, slot):
        return self.dll.rw_recover(self.handle, slot)

    def order_count(self, count):
        self.dll.rw_order_count(self.handle, count)

    def turnout(self, index):
        return self.dll.rw_turnout(self.handle, index)

    def split(self, slot, left, right):
        return self.dll.rw_split(self.handle, slot, left, right)

    def drive(self, slot, direction):
        return self.dll.rw_drive(self.handle, slot, direction)

    def tick(self, ms):
        self.dll.rw_tick(self.handle, ms)

    def snapshot(self):
        self.dll.rw_snapshot(self.handle, c.cast(self.header, c.POINTER(c.c_uint32)),
                             c.cast(self.vehicles, c.POINTER(c.c_uint32)),
                             c.cast(self.orders, c.POINTER(c.c_uint32)))
        return {
            "switches": self.header[0],
            "delivered": self.header[1],
            "vehicles": [[slot, *v] for slot, v in enumerate(self.vehicles) if v[0]],
            "orders": [list(o) for o in self.orders if o[0] and o[3] < o[2]],
        }
