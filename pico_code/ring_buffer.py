class RingBuffer:
    """Buffer circular de métricas de ejecución en microsegundos (minimum_PicoROS)."""

    def __init__(self, size=10, unit="us"):
        self.size = size
        self.data = [0] * size
        self.index = 0
        self.count = 0
        self.full = False
        self.unit = unit

    def append(self, value):
        self.data[self.index] = value
        self.count += 1
        self.index = self.count % self.size
        if self.index == 0:
            self.full = True

    def get(self):
        if not self.full:
            return self.data[: self.index]
        return self.data[self.index :] + self.data[: self.index]

    def get_disord(self):
        if not self.full:
            return self.data[: self.index]
        return self.data

    def __len__(self):
        return self.size if self.full else self.index

    def stats(self):
        data = self.get_disord()
        ret_dic = {
            "len": len(data),
            "count": self.count,
            "unit": self.unit,
        }
        if not data:
            return ret_dic
        res = dict(ret_dic)
        res["min"] = min(data)
        res["max"] = max(data)
        res["avg"] = sum(data) / len(data)
        return res

