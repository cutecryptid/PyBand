#!/usr/bin/env python3
import json
import array
from abstract_miband import AbstractMiBand
from miband2delegate import MiBand2Delegate
import mibandconstants as mbc

class MiBand2(AbstractMiBand):
    _MODEL = "mb2"

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
        return MiBand2Delegate(self)

    def setDisplayItems(self, steps=False, distance=False, calories=False, heartrate=False, battery=False):
        print("Setting display items to [{0}{1}{2}{3}{4}]...".format(
            " STP" if steps else "", " DST" if distance else "", " CAL" if calories else "",
            " HRT" if heartrate else "", " BAT" if battery else ""))

        screen_change_byte = 1
        command_change_screens = [0x0a, 0x01, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05]
        if steps:
            command_change_screens[screen_change_byte] |= 0x02
        if distance:
            command_change_screens[screen_change_byte] |= 0x04
        if calories:
            command_change_screens[screen_change_byte] |= 0x08
        if heartrate:
            command_change_screens[screen_change_byte] |= 0x10
        if battery:
            command_change_screens[screen_change_byte] |= 0x20

        msg_command = array.array('B', command_change_screens).tostring()
        self.char_config.write(msg_command)
        self.waitForNotifications(self.timeout)

    # Changes time display to time or datetime
    def setDisplayTimeFormat(self, format):
        if format == "date":
            print("Enabling Date Format...")
            self.char_config.write(b'\x06\x0a\x00\x03')
        elif format == "time":
            print("Enabling Time Format...")
            self.char_config.write(b'\x06\x0a\x00\x00')
        else:
            print("Only 'date' and 'time' formats supported")
