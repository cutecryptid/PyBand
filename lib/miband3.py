#!/usr/bin/env python3
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
        print("UNINMPLEMENTED FOR MB3")
        pass

    def setDisplayTimeFormat(self, format):
        print("CAN'T CHANGE TIME FORMAT ON MB3")
        pass
