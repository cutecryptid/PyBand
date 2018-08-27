import calendar
import datetime
import struct

class MiBandTime:
    def __init__(self, device, year, month, day, hour, min, sec=None, weekday=None, dst=0, tz=4):
        # Infer precision from parameters if not specified
        self.device = device
        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.min = min
        self.sec = sec
        if self.sec != None:
            self.precision = "sec"
            if weekday != None:
                self.weekday = weekday
            else:
                self.weekday = calendar.weekday(self.year, self.month, self.day) + 1
        else:
            self.precision = "min"
        self.dst = dst
        self.tz = tz

    def toDatetime(self):
        return datetime.datetime(self.year, self.month, self.day, self.hour, self.min)

    def getBytes(self, honorOffset=False):
        # Trick the miband to record sleep out of schedule
        if(honorOffset):
            if(self.device.sleepOffset != 0):
                datetime[3] += self.sleepOffset

        if (self.precision == 'min'):
            dateBytes = struct.pack('<H4B', self.year, self.month, self.day, self.hour, self.min)
        elif (self.precision == 'sec'):
            dateBytes = struct.pack('<H7B', self.year, self.month, self.day, self.hour, self.min, self.sec, self.weekday, 0)
        else:
            raise ValueError('Precision can only be min or sec, got {0}'.format(self.precision))

        # Last byte is timezone, but datetime is tz-unaware in python so it shouldn't be needed
        tail = struct.pack('2B', self.dst, self.tz)
        return dateBytes + tail

    @staticmethod
    def dateBytesToDatetime(device, datetime):
        mbDate = None
        if (len(datetime) == 8):
            dtm = struct.unpack('<H4B', datetime[0:6])
            tz = struct.unpack('<2B', datetime[6:8])
            mbDate = MiBandTime(self, device, dtm[0], dtm[1], dtm[2], dtm[3], dtm[4], dst=tz[0], tz=tz[1])
        elif (len(datetime) == 11):
            dtm = struct.unpack('<H7B', datetime[0:9])
            tz = struct.unpack('<2B', datetime[9:11])
            mbDate = MiBandTime(device, dtm[0], dtm[1], dtm[2], dtm[3], dtm[4], sec=dtm[5], weekday=dtm[6], dst=tz[0], tz=tz[1])
        else:
            raise ValueError('Unsupported DatetimeBytes length {0}'.format(len(datetime)))
        return mbDate

    def toMinPrecision(self):
        self.precision = "min"
        self.sec = None
        self.weekday = None

    def toSecPrecision(self, sec, weekday):
        self.precision = "sec"
        self.sec = sec
        self.weekday = weekday

    def addMinutes(self, minutes):
        tmp_sec = self.sec if self.sec != None else 0
        tmp_min = (self.min + minutes + (tmp_sec/60))
        tmp_hour = (self.hour + (tmp_min/60))
        tmp_day = (self.day + (tmp_hour/24)) - 1
        monthdays = calendar.monthrange(self.year, self.month)[1]
        tmp_month = (self.month + (tmp_day/(monthdays))) - 1
        tmp_year = (self.year + (tmp_month/12))

        if self.precision == "sec":
            tmp_weekday = calendar.weekday(tmp_year, tmp_month%12+1, tmp_day%monthdays+1)+1
            return MiBandTime(self, tmp_year, tmp_month%12+1 , tmp_day%monthdays+1, tmp_hour%24, tmp_min%60, tmp_sec%60, weekday=tmp_weekday, dst=self.dst, tz=self.tz)
        else:
            return MiBandTime(self, tmp_year, tmp_month%12+1, tmp_day%monthdays+1, tmp_hour%24, tmp_min%60, dst=self.dst, tz=self.tz)

    def minutesUntilNow(self):
        now = datetime.datetime.now()
        years = now.year - self.year
        months = now.month - self.month
        days = now.day - self.day
        hours = now.hour - self.hour
        minutes = now.minute - self.min

        return years*365*24*60 + months*30*24*60 + days*24*60 + hours*60 + minutes

    def __str__(self):
        ret = "{0:04d}-{1:02d}-{2:02d} {3:02d}:{4:02d}".format(self.year, self.month, self.day, self.hour, self.min)
        if self.precision == "sec":
            ret += ":{0:02}".format(self.sec, self.weekday)
        return ret
