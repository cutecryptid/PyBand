from miband2 import MiBand2
from miband3 import MiBand3

DEVICE_MODELS = {"MI Band 2":"mb2", "Mi Band 3": "mb3"}

class MiBand():
    def __init__(self, addr, key, sleepOffset=0, initialize=False, model="mb2"):
        if model == "mb2":
            MiBand2(addr, key, sleepOffset, initialize)
        else:
            MiBand3(addr, key, sleepOffset, initialize)
