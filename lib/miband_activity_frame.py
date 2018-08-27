class MiBandActivityFrame:
    def __init__(self, device, dtm, type, intensity, steps, heartrate):
        self.device = device
        self.dtm = dtm
        self.type = type
        self.intensity = intensity
        self.steps = steps
        self.heartrate = heartrate

    def __str__(self):
        return str(self.dtm) + " (" + str(self.type) + ") !" + str(self.intensity) + "! #" + str(self.steps) + "# ^" + str(self.heartrate) + "^"
