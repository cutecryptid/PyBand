#!/usr/bin/env python2
import json
from abstract_miband import AbstractMiBand
from miband3delegate import MiBand3Delegate
import mibandconstants as mbc

class MiBand3(AbstractMiBand):
    _MODEL = "mb3"

    def __init__(self, addr, key, sleepOffset=0, initialize=False):
        AbstractMiBand.__init__(self, addr, key, sleepOffset=0, initialize=False)

        self.init_activity_svc()
        self.init_fetch_svc()
        self.init_alert_svc()
        self.init_hrm_svc()
        self.init_dev_event_svc()
        self.init_config_svc()
        self.init_firmware_svc()
        self.init_user_settings_svc()
        self.init_time_svc()
        self.init_batt_svc()

        self.waitForNotifications(0.5)
        self.setTimeToSystem()
        self.battery_info = self.req_battery()

    def get_model(self):
        return self._MODEL

    def get_model_delegate(self):
        return MiBand3Delegate(self)

    def setDisplayItems(self, steps=False, distance=False, calories=False, heartrate=False, battery=False):
        print "UNINMPLEMENTED FOR MB3"
        pass

    # Changes time display to time or datetime (not tested on MB3)
    # Probably changes main display, try adjusting bytes on command
    # If it doesn't work, log MB3 commands and reimplement
    def setDisplayTimeFormat(self, format):
        if format == "date":
            print "Enabling Date Format..."
            self.char_config.write(b'\x06\x0a\x00\x03')
        elif format == "time":
            print "Enabling Time Format..."
            self.char_config.write(b'\x06\x0a\x00\x00')
        else:
            print "Only 'date' and 'time' formats supported"

    # Changes time display to 12h or 24h format (not tested on MB3)
    # Probably not working, test
    def setDisplayTimeHours(self, format):
        if format == 12:
            print "Enabling 12 hours Format..."
            self.char_config.write(b'\x06\x02\x00\x00')
        elif format == 24:
            print "Enabling 24 hours Format..."
            self.char_config.write(b'\x06\x02\x00\x01')
        else:
            print "Only 12 and 24 formats supported"
