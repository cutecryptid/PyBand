#!/usr/bin/env python2
import struct
import array
import json
import re
import os
import binascii
import datetime
from Crypto.Cipher import AES
from bluepy.btle import Peripheral, ADDR_TYPE_RANDOM, Service, Characteristic, Descriptor
from miband2time import MiBand2Time
from miband2delegate import MiBand2Delegate
import miband2constants as mb2c

csv_directory = "activity_log/"

lib_path = os.path.dirname(__file__) + ("/" if len(os.path.dirname(__file__)) > 0 else "")
services_data = json.load(open(lib_path + 'mb2services.json'))

def string_hashcode(s):
    h = 0
    for c in s:
        h = (31 * h + ord(c)) & 0xFFFFFFFF
    return ((h + 0x80000000) & 0xFFFFFFFF) - 0x80000000

class MiBand2Alarm:
    def __init__ (self, hour, minute, enabled=True, repetitionMask=128):
        self.hour = hour
        self.minute = minute
        self.enabled = enabled
        self.repetitionMask = repetitionMask

    def toggle(self):
        self.enabled = not self.enabled
        return self.enabled

    def toggleDay(self, day):
        mask = (self.repetitionMask ^ (2**day))
        if mask == 0:
            mask = 128
        if mask > 128:
            mask ^= 128
        self.repetitionMask = mask

    def getRepetitionMask(self):
        return self.repetitionMask

    def getMessage(self, index):
        base = 0
        if self.enabled:
            base = 128

        mask = self.getRepetitionMask()

        return b'\x02' + struct.pack('4B', (base+index), self.hour, self.minute, mask)

    def __str__(self):
        repr = "[{0}] ".format("E" if self.enabled else "D")
        repr += "{0:02d}:{1:02d}".format(self.hour, self.minute)
        if self.getRepetitionMask() != 128:
            mask = self.getRepetitionMask()
            repr += " ({0}{1}{2}{3}{4}{5}{6})".format(
                        "MON" if mask & (2**0) else "",
                        " TUE" if mask & (2**1) else "",
                        " WED" if mask & (2**2) else "",
                        " THU" if mask & (2**3) else "",
                        " FRI" if mask & (2**4) else "",
                        " SAT" if mask & (2**5) else "",
                        " SUN" if mask & (2**6) else "")
        else:
            repr += " (SINGLE SHOT)"
        return repr

class MiBand2(Peripheral):
    _send_rnd_cmd = struct.pack('<2s', b'\x02\x08')
    _send_enc_key = struct.pack('<2s', b'\x03\x08')
    _fetch_cmd = struct.pack('<1s', b'\x02')
    _activity_data_start_cmd = struct.pack('<1s', b'\x01')
    _activity_data_type_activity_cmd = struct.pack('<1s', b'\x01')

    def __init__(self, addr, key, sleepOffset=0, initialize=False):
        Peripheral.__init__(self, addr, addrType=ADDR_TYPE_RANDOM)
        print("Connected")

        self._KEY = key
        self._send_key_cmd = struct.pack('<18s', b'\x01\x08' + str(self._KEY))

        self.timeout = 2
        self.state = None
        self.fetch_state = "FETCH"
        self.sleepOffset = sleepOffset
        self.activityDataBuffer = []
        self.lastSyncDate = MiBand2Time(self, 2000, 00, 00, 00, 00)
        self.alarms = []
        self.setDelegate(MiBand2Delegate(self))

        self.enabled_notifs = []

        # Enable auth service notifications on startup
        self.init_auth_svc()

        self.waitForNotifications(self.timeout)
        self.setSecurityLevel(level="medium")

        if initialize:
            self.initialize()
            self.waitForNotifications(0.5)
        else:
            self.authenticate()
            self.waitForNotifications(0.5)

        self.init_activity_svc()
        self.init_fetch_svc()
        self.init_alert_svc()
        self.init_hrm_svc()
        self.init_time_svc()
        self.init_dev_event_svc()
        self.init_batt_svc()
        self.init_config_svc()
        self.init_firmware_svc()
        self.init_user_settings_svc()

        self.waitForNotifications(0.5)
        self.setTimeToSystem()
        self.battery_info = self.req_battery()

    def disconnect(self):
        if (hasattr(self, 'enabled_notifs')):
            for n in self.enabled_notifs:
                print("Disabling %s service notifications status..." % n)
                getattr(self, 'cccd_'+n).write(b"\x00\x00", True)
                self.enabled_notifs.remove(n)
        Peripheral.disconnect(self)

    def init_svc(self, name, svc_uuid, char_uuid):
        if (not hasattr(self, 'char_'+name)):
            svc_data = services_data[svc_uuid]
            char = svc_data["chars"][char_uuid]
            svc = Service(self, svc_uuid, svc_data["hndStart"], svc_data["hndEnd"])
            setattr(self, 'char_'+name, Characteristic(self, char_uuid, char["handle"], char["properties"], char["valHandle"]))
            if len(char["descs"].keys()) > 0:
                setattr(self, 'cccd_'+name, Descriptor(self, char["descs"].keys()[0], char["descs"].values()[0]["handle"]))
                print("Enabling %s notifications..." % name)
                getattr(self, 'cccd_'+name).write(b"\x01\x00", True)
                self.enabled_notifs.append(name)

    def init_auth_svc(self):
        self.init_svc('auth', mb2c.UUID_SVC_MIBAND2, mb2c.UUID_CHARACTERISTIC_AUTH)

    def init_activity_svc(self):
        self.init_svc('activity', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_5_ACTIVITY_DATA)

    def init_fetch_svc(self):
        self.init_svc('fetch', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_4_FETCH)

    def init_alert_svc(self):
        self.init_svc('alert', mb2c.UUID_SVC_ALERT, mb2c.UUID_CHAR_ALERT)

    def init_hrm_svc(self):
        self.init_svc('hrm_ctrl', mb2c.UUID_SVC_HEART_RATE, mb2c.UUID_CHAR_HRM_CONTROL)
        self.init_svc('hrm', mb2c.UUID_SVC_HEART_RATE, mb2c.UUID_CHAR_HRM_MEASURE)

    def init_batt_svc(self):
        self.init_svc('battery', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_6_BATTERY_INFO)

    def init_time_svc(self):
        self.init_svc('current_time', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_CURRENT_TIME)

    def init_dev_event_svc(self):
        self.init_svc('dev_event', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_DEVICEEVENT)

    def init_config_svc(self):
        self.init_svc('config', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_3_CONFIGURATION)

    def init_user_settings_svc(self):
        self.init_svc('user_settings', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_8_USER_SETTINGS)

    def init_firmware_svc(self):
        self.init_svc('firmware', mb2c.UUID_SERVICE_FIRMWARE_SERVICE, mb2c.UUID_CHARACTERISTIC_FIRMWARE)
        self.init_svc('firmware_data', mb2c.UUID_SERVICE_FIRMWARE_SERVICE, mb2c.UUID_CHARACTERISTIC_FIRMWARE_DATA)

    def toggle_background_notifications(self):
        if not self.notif_thread.isAlive():
            print("Starting Notificaction Thread...")
            self.notif_thread.start()
            print("Notificaction Thread Started!")
        else:
            print("Stopping Notificaction Thread...")
            self.notif_thread.start()
            print("Notificaction Thread Stopped!")

    def encrypt(self, message):
        aes = AES.new(self._KEY, AES.MODE_ECB)
        return aes.encrypt(message)

    def send_key(self):
        print("Sending Key...")
        self.char_auth.write(self._send_key_cmd)
        self.waitForNotifications(self.timeout)

    def req_rdn(self):
        print("Requesting random number...")
        self.char_auth.write(self._send_rnd_cmd)
        self.waitForNotifications(self.timeout)

    def send_enc_rdn(self, data):
        print("Sending encrypted random number")
        cmd = self._send_enc_key + self.encrypt(data)
        send_cmd = struct.pack('<18s', cmd)
        self.char_auth.write(send_cmd)
        self.waitForNotifications(self.timeout)

    def initialize(self):
        self.send_key()

        while True:
            self.waitForNotifications(self.timeout)
            if self.state == "AUTHENTICATED":
                return True
            elif self.state:
                return False

    def authenticate(self):
        self.req_rdn()

        while True:
            self.waitForNotifications(self.timeout)
            if self.state == "AUTHENTICATED":
                return True
            elif self.state:
                return False

    def monitorHeartRate(self):
        print("Cont. HRM start")
        self.char_hrm_ctrl.write(b'\x15\x01\x00', True)
        self.char_hrm_ctrl.write(b'\x15\x01\x01', True)
        for i in range(30):
            self.waitForNotifications(self.timeout)

    def monitorHeartRateSleep(self, enable):
        if enable:
            print("Enabling Sleep HR Measurement...")
            self.char_hrm_ctrl.write(b'\x15\x00\x01', True)
        else:
            print("Disabling Sleep HR Measurement...")
            self.char_hrm_ctrl.write(b'\x15\x00\x00', True)

        self.waitForNotifications(self.timeout)

    def setMonitorHeartRateInterval(self, interval):
        print "Setting heart rate measurement interval to %s minutes" % interval
        self.char_hrm_ctrl.write(b'\x14' + struct.pack('B', interval), True)

    def req_battery(self):
        print("Requesting Battery Info")
        b_data = self.char_battery.read()
        b_info = {}
        b_info['level'] = struct.unpack('1b', b_data[1])[0]
        b_info['status'] = 'normal' if struct.unpack('1b', b_data[2])[0] == 0 else 'charging'
        y,m,d,h,mm,s,tz = struct.unpack('<1H6B', b_data[3:11])
        b_info['prev_charge'] = MiBand2Time(self, y, m, d, h, mm, sec=s, dst=0, tz=tz)
        y,m,d,h,mm,s,tz = struct.unpack('<1H6B', b_data[11:19])
        b_info['last_charge'] = MiBand2Time(self, y, m, d, h, mm, sec=s, dst=0, tz=tz)
        b_info['last_charge_amount'] = struct.unpack('<1b', b_data[19])[0]
        return b_info

    def getTime(self):
        dtm = self.char_current_time.read()
        return MiBand2Time.dateBytesToDatetime(self, dtm)

    def setTime(self, dtm):
        bytes = dtm.getBytes()
        self.char_current_time.write(bytes, True)

    def setTimeToSystem(self):
        now = datetime.datetime.now()
        print("Setting time to %s" % str(now))
        self.setTime(MiBand2Time(self, now.year, now.month, now.day, now.hour, now.minute, sec=now.second))

    def setDisplayTimeFormat(self, format):
        if format == "date":
            print "Enabling Date Format..."
            self.char_config.write(b'\x06\x0a\x00\x03')
        elif format == "time":
            print "Enabling Time Format..."
            self.char_config.write(b'\x06\x0a\x00\x00')
        else:
            print "Only 'date' and 'time' formats supported"

    def setDisplayTimeHours(self, format):
        if format == 12:
            print "Enabling 12 hours Format..."
            self.char_config.write(b'\x06\x02\x00\x00')
        elif format == 24:
            print "Enabling 24 hours Format..."
            self.char_config.write(b'\x06\x02\x00\x01')
        else:
            print "Only 12 and 24 formats supported"

    def getLastSyncDate(self):
        return self.lastSyncDate

    def setLastSyncDate(self,date):
        dtm = MiBand2Time(self, date.year, date.month, date.day, date.hour, date.minute)
        self.lastSyncDate = dtm

    def fetch_activity_data(self):
        self.fetch_state = "FETCH"

        while self.fetch_state == "FETCH":
            self.start_fetching()
            if self.fetch_state == "SUCCESS":
                self.fetch_state = "FETCH"

        if self.fetch_state == "FINISHED":
            print "Finished Successfully!"
        else:
            print "Finished but something went wrong, not storing data"

        self.fetch_state = "FETCH"

    def start_fetching(self):
        syncDate = self.lastSyncDate

        self.char_fetch.write(bytes(self._activity_data_start_cmd + self._activity_data_type_activity_cmd + syncDate.getBytes()))

        while self.fetch_state != "READY" and self.fetch_state != "FINISHED":
            self.waitForNotifications(self.timeout)

        if self.fetch_state == "READY":
            self.char_fetch.write(self._fetch_cmd)
            while self.fetch_state != "SUCCESS" and self.fetch_state != "TERMINATED" and self.fetch_state != "FINISHED":
                self.waitForNotifications(self.timeout)

    def store_activity_data_file(self, base_route):
        print("Storing {0} activity data frames".format(len(self.activityDataBuffer)))
        csv_file = open(base_route + self.addr.replace(':','')+'_'+str(self.activityDataBuffer[0].dtm).replace(':','_')+'-'+str(self.activityDataBuffer[-1].dtm).replace(':','_')+'.csv'.replace(' ', ''), "w")
        csv_file.write("device_mac, date, type, intensity, steps, heartrate\n")
        for frame in self.activityDataBuffer:
            csv_file.write(str(self.addr) +", "+ str(frame.dtm)+", "+str(frame.type)+", "+str(frame.intensity)+", "+str(frame.steps)+", "+str(frame.heartrate)+"\n")
        csv_file.close()
        self.clearActivityDataBuffer()

    def getActivityDataBuffer(self):
        return self.activityDataBuffer

    def clearActivityDataBuffer(self):
        self.activityDataBuffer = []

    def send_alert(self, code):
        self.char_alert.write(code)

    def event_listen(self):
        print ("Listening for any event")
        while True:
            self.waitForNotifications(self.timeout)

    def onEvent(self, data):
        if data == 1:
            print "Fell Asleep"
        elif data == 2:
            print "Woke Up"
        elif data == 4:
            print "Button Pressed"

    def queueAlarm(self, hour, minute, repetitionMask=128, enableAlarm=True):
        if len(self.alarms) >= 5:
            print "Can't store more than 5 alarms at a time."
            return -1
        else:
            alarm = MiBand2Alarm(hour, minute, enabled=enableAlarm,
                                            repetitionMask=repetitionMask)
            self.alarms.append(alarm)
            index = len(self.alarms)-1
            print "Writing Alarm {0} at position {1}".format(str(alarm), index)
            self.char_config.write(alarm.getMessage(index))
            self.waitForNotifications(self.timeout)
            return index

    def setAlarm(self, index, hour, minute, repetitionMask, enableAlarm):
        if index >= len(self.alarms):
            print "Alarm doesn't exist."
            return False
        else:
            if repetitionMask == 0:
                repetitionMask = 128
            alarm = MiBand2Alarm(hour, minute, enabled=enableAlarm,
                                            repetitionMask=repetitionMask)
            self.alarms[index] = alarm
            print "Writing Alarm {0} at position {1}".format(str(alarm), index)
            self.char_config.write(alarm.getMessage(index))
            self.waitForNotifications(self.timeout)
            return True

    def toggleAlarm(self, index):
        alarm = self.alarms[index]

        print "{0} Alarm {1}".format("Enabling" if not alarm.enabled else "Disabling", str(alarm))
        self.alarms[index].toggle()

        self.char_config.write(alarm.getMessage(index))
        self.waitForNotifications(self.timeout)

    def toggleAlarmDay(self, index, day):
        alarm = self.alarms[index]

        self.alarms[index].toggleDay(day)
        print "Changing Alarm to {0}".format(str(alarm))

        self.char_config.write(alarm.getMessage(index))
        self.waitForNotifications(self.timeout)

    def changeAlarmTime(self, index, hour, minute):
        alarm = self.alarms[index]

        self.alarms[index].hour = hour
        self.alarms[index].minute = minute
        print "Changing Alarm to {0}".format(str(alarm))

        self.char_config.write(alarm.getMessage(index))
        self.waitForNotifications(self.timeout)

    def deleteAlarm(self, index):
        # Tricky, move all alarms one position beginning at the deleted one
        # and delete the last one

        alarm = self.alarms[index]

        print "Deleting alarm {0}".format(str(alarm))
        for i in range (index+1, len(self.alarms)):
            alarm = self.alarms[i]
            self.char_config.write(alarm.getMessage(i))
            self.waitForNotifications(self.timeout)

        last = len(self.alarms)-1
        alarm = MiBand2Alarm(0, 0, enabled=False)
        self.char_config.write(alarm.getMessage(last))
        self.waitForNotifications(self.timeout)

        del self.alarms[index]

    def cleanAlarms(self):
        print "Clearing all alarms from device"
        for i in range(10):
            alarm = MiBand2Alarm(0, 0, enabled=False)
            self.char_config.write(alarm.getMessage(i))
            self.waitForNotifications(self.timeout)
        self.alarms = []

    def setUserInfo(self, alias, sex, height, weight, birth_date):
        print("Attempting to set user info...")
        userid = string_hashcode(alias)

        user_msg = b'\x4f\x00\x00'
        user_msg += struct.pack('<H', birth_date[0])
        user_msg += struct.pack('B', birth_date[1])
        user_msg += struct.pack('B', birth_date[2])
        user_msg += struct.pack('B', sex)
        user_msg += struct.pack('<H', height)
        user_msg += struct.pack('<H', weight*200)
        user_msg += struct.pack('<i', userid)

        self.char_user_settings.write(user_msg)
        self.waitForNotifications(self.timeout)

    def setWearLocation(self, location):
        if location in ['left', 'right']:
            print("Attempting to set wear location to %s wrist..." % location)
            if location == 'left':
                self.char_user_settings.write(b'\x20\x00\x00\x02')
            else:
                self.char_user_settings.write(b'\x20\x00\x00\x82')
            self.waitForNotifications(self.timeout)
        else:
            print("Only left and right wrists supported, sorry three-handed man")

    def setDistanceUnit(self, unit):
        if unit in ['metric', 'imperial']:
            print("Attempting to change to %s system..." % unit)
            if unit == 'metric':
                self.char_user_settings.write(b'\x06\x03\x00\x00')
            else:
                self.char_user_settings.write(b'\x06\x03\x00\x01')
            self.waitForNotifications(self.timeout)
        else:
            print("Only metric and imperial supported, sorry natural system fan")

    def setLiftWristToActivate(self, enable):
        if enable:
            print("Enabling activate display on wrist lift")
            self.char_config.write(b'\x05\x00\x01')
        else:
            print("Disabling activate display on wrist lift")
            self.char_config.write(b'\x05\x00\x00')
        self.waitForNotifications(self.timeout)

    def setFitnessGoal(self, goal):
        print("Attempting to set Fitness Goal to %s steps..." % goal)

        goal_msg = b'\x10\x00\x00'
        goal_msg += struct.pack('H', goal)
        goal_msg += b'\x00\x00'

        self.char_user_settings.write(goal_msg)
        self.waitForNotifications(self.timeout)

    def setDisplayItems(self, steps=False, distance=False, calories=False, heartrate=False, battery=False):
        print ("Setting display items to [{0}{1}{2}{3}{4}]...".format(
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

    def setDoNotDisturb(self, mode, start=None, end=None, enableLift=True):
        dnd_msg = [0x09]

        if mode == "off":
            print("Turning off Do not Disturb...")
            dnd_msg += [0x02]

        elif mode == "automatic":
            print("Setting do not disturb to Automatic...")
            dnd_msg += [0x03]

        elif mode == "scheduled":
            dnd_msg += [0x01, 0x01, 0x00, 0x06, 0x00]
            if start == None:
                start = (1,0)
            dnd_msg[2] = start[0]
            dnd_msg[3] = start[1]
            if end == None:
                end = (6,0)
            dnd_msg[4] = end[0]
            dnd_msg[5] = end[1]
            print("Setting Do Not Disturb between {0:02d}:{1:02d} and {2:02d}:{3:02d}".format(
                    start[0], start[1], end[0], end[1]))

        else:
            print("Only off, automatic and scheduled supported")
            return

        if not enableLift:
            # Set first byte of mode to 1 if we want to disable the lift-to-activate
            print("Disabling Lift to Activate during DND time")
            dnd_msg[1] |= 0x80

        self.char_config.write(array.array('B', dnd_msg).tostring())
        self.waitForNotifications(self.timeout)

    def setRotateWristToSwitchInfo(self, enable):
        print("Setting rotate wrist to cycle info to %s..." % enable)

        if enable:
            self.char_config.write(b'\x06\x0d\x00\x01')
        else:
            self.char_config.write(b'\x06\x0d\x00\x00')
        self.waitForNotifications(self.timeout)

    def setInactivityWarnings(self, enable, threshold=60, start=(8, 0), end=(19, 0), enableDND=False, dndStart=(0,0), dndEnd=(0,0)):
        if enable:
            print("Enabling Inactivity Warnings from {0:02d}:{1:02d} to {2:02d}:{3:02d}...".format(
                    start[0], start[1], end[0], end[1]))
            inactivity_cmd = [ 0x08, 0x01, 0x3c, 0x00, 0x04, 0x00, 0x15, 0x00, 0x00, 0x00, 0x00, 0x00 ]

            inactivity_cmd[2] = threshold

            inactivity_cmd[4] = start[0]
            inactivity_cmd[5] = start[1]

            if enableDND:
                print("Do-Not-Disturbing from {0:02d}:{1:02d} to {2:02d}:{3:02d}...".format(
                        dndStart[0], dndStart[1], dndEnd[0], dndEnd[1]))
                inactivity_cmd[6] = dndStart[0]
                inactivity_cmd[7] = dndStart[1]

                inactivity_cmd[8] = dndEnd[0]
                inactivity_cmd[9] = dndEnd[1]

                inactivity_cmd[10] = end[0]
                inactivity_cmd[11] = end[1]
            else:
                inactivity_cmd[6] = end[0]
                inactivity_cmd[7] = end[1]

            self.char_config.write(array.array('B',inactivity_cmd).tostring())
        else:
            print("Disabling Inactivity Warnings...")
            self.char_config.write(b'\x08\x00\x3c\x00\x04\x00\x15\x00\x00\x00\x00\x00')
        self.waitForNotifications(self.timeout)

    def setDisplayCaller(self, enable):
        if enable:
            print("Enabling Display Caller ID...")
            self.char_config.write(b'\x06\x10\x00\x00\x01')
        else:
            print("Disabling Display Caller ID...")
            self.char_config.write(b'\x06\x10\x00\x00\x00')
        self.waitForNotifications(self.timeout)

    def setGoalNotification(self, enable):
        self.enable_notif('config', True)

        if enable:
            print("Enabling Goal Notification...")
            self.char_config.write(b'\x06\x06\x00\x01')
        else:
            print("Disabling Goal Notification...")
            self.char_config.write(b'\x06\x06\x00\x00')
        self.waitForNotifications(self.timeout)

    def factoryReset(self, force=False):
        if not force:
            print ("Factory resetting will wipe everything and change the device's MAC, use 'force' parameter if you know what you are doing")
        else:
            print("Resetting Device...")
            self.char_config.write(b'\x06\x0b\x00\x01')
            self.waitForNotifications(self.timeout)
            self.disconnect()

    def reboot(self):
        self.char_firmware.write(b'\x05')
        self.waitForNotifications(self.timeout)
