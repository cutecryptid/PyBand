#!/usr/bin/env python2
import struct
import json
import re
import os
import binascii
import datetime
import array
from Crypto.Cipher import AES
from bluepy.btle import Service, Characteristic, Descriptor, Peripheral, ADDR_TYPE_RANDOM
from mibandtime import MiBandTime
from mibandalarm import MiBandAlarm
import mibandconstants as mbc

# Auxiliar function to encode the username to the MiBand
def string_hashcode(s):
    h = 0
    for c in s:
        h = (31 * h + ord(c)) & 0xFFFFFFFF
    return ((h + 0x80000000) & 0xFFFFFFFF) - 0x80000000

class AbstractMiBand(Peripheral):
    # Pre-enconded byte commands to do the basic functionality
    # Other commands are not pre-encoded in variables and are just used once on their methods
    _send_rnd_cmd = struct.pack('<2s', b'\x02\x08')
    _send_enc_key = struct.pack('<2s', b'\x03\x08')
    _fetch_cmd = struct.pack('<1s', b'\x02')
    _activity_data_start_cmd = struct.pack('<1s', b'\x01')
    _activity_data_type_activity_cmd = struct.pack('<1s', b'\x01')

    def __init__(self, addr, key, sleepOffset=0, initialize=False):
        # Both mibands are created as a BLE peripheral
        Peripheral.__init__(self, addr, addrType=ADDR_TYPE_RANDOM)
        print("Connected")

        self.key = key

        # The command with the AUTH KEY has to be created during initialization as it's parametrized
        self._send_key_cmd = struct.pack('<18s', b'\x01\x08' + str(self.key))

        # Default values for any MiBand
        self.timeout = 2 # Common timeout for BLE responses in seconds
        self.state = None # AUTH state, used only during authentication
        self.fetch_state = "FETCH" # FETCH state, used only suring activity data fetching
        self.sleepOffset = sleepOffset # Offset in hours to allow th band to record sleeping during the day if needed
        # MBs only record sleep at night, if the user usually sleeps during the day because whatever, this parameter
        # has to be adjusted accordingly so the MB "thinks" the user is sleeping at times it can record sleep.
        self.activityDataBuffer = [] # Buffer for the fetched activity data, flushed once it's saved
        self.lastSyncDate = MiBandTime(self, 2000, 00, 00, 00, 00) # Initial sync date, can't be read from device, stored locally
        self.alarms = []
        self.enabled_notifs = [] # Services with notifications we have suscribed to so we can turn them off before disconnecting

        # Enable auth service notifications on startup
        self.init_auth_svc()
        self.waitForNotifications(self.timeout)
        self.setSecurityLevel(level="medium")

        # Set the right delegate (See MiBand2Delegate, MiBand3Delegate)
        self.setDelegate(self.get_model_delegate())

        if initialize:
            # Just store the auth key on both sides and do the handshake
            self.initialize()
            self.waitForNotifications(0.5)
        else:
            # Once authenticated we can skip some steps
            self.authenticate()
            self.waitForNotifications(0.5)

    # Abstract method to return proper model
    def get_model(self):
        pass

    # Abstract method to return proper delegate
    def get_model_delegate(self):
        pass

    # Initializes any characteristic given a name, a service UUID and the characteristic's UUID
    # This is done by loading data from a JSON file describing the full GATT of each device
    # instead of querying the device, that is SO MUCH slower
    # Alsos suscribes to the characteristic's notifications
    def init_svc(self, name, svc_uuid, char_uuid):
        if (not hasattr(self, 'char_'+name)):
            services_data = json.load(open(mbc.lib_path + self.get_model() + 'services.json'))
            svc_data = services_data[svc_uuid]
            char = svc_data["chars"][char_uuid]
            svc = Service(self, svc_uuid, svc_data["hndStart"], svc_data["hndEnd"])
            setattr(self, 'char_'+name, Characteristic(self, char_uuid, char["handle"], char["properties"], char["valHandle"]))
            if len(char["descs"].keys()) > 0:
                setattr(self, 'cccd_'+name, Descriptor(self, char["descs"].keys()[0], char["descs"].values()[0]["handle"]))
                print("Enabling %s notifications..." % name)
                getattr(self, 'cccd_'+name).write(b"\x01\x00", True)
                self.enabled_notifs.append(name)

    # Each characteristic/group of characteristics are initialized on their own methods
    # MBC is a constants file that gives name to each relevant UUID so it can be used here
    def init_auth_svc(self):
        self.init_svc('auth', mbc.UUID_SVC_MIBAND2, mbc.UUID_CHARACTERISTIC_AUTH)

    def init_activity_svc(self):
        self.init_svc('activity', mbc.UUID_SVC_MIBAND, mbc.UUID_CHARACTERISTIC_5_ACTIVITY_DATA)

    def init_fetch_svc(self):
        self.init_svc('fetch', mbc.UUID_SVC_MIBAND, mbc.UUID_CHARACTERISTIC_4_FETCH)

    def init_alert_svc(self):
        self.init_svc('alert', mbc.UUID_SVC_ALERT, mbc.UUID_CHAR_ALERT)

    def init_hrm_svc(self):
        self.init_svc('hrm_ctrl', mbc.UUID_SVC_HEART_RATE, mbc.UUID_CHAR_HRM_CONTROL)
        self.init_svc('hrm', mbc.UUID_SVC_HEART_RATE, mbc.UUID_CHAR_HRM_MEASURE)

    def init_batt_svc(self):
        self.init_svc('battery', mbc.UUID_SVC_MIBAND, mbc.UUID_CHARACTERISTIC_6_BATTERY_INFO)

    def init_time_svc(self):
        self.init_svc('current_time', mbc.UUID_SVC_MIBAND, mbc.UUID_CHARACTERISTIC_CURRENT_TIME)

    def init_dev_event_svc(self):
        self.init_svc('dev_event', mbc.UUID_SVC_MIBAND, mbc.UUID_CHARACTERISTIC_DEVICEEVENT)

    def init_config_svc(self):
        self.init_svc('config', mbc.UUID_SVC_MIBAND, mbc.UUID_CHARACTERISTIC_3_CONFIGURATION)

    def init_user_settings_svc(self):
        self.init_svc('user_settings', mbc.UUID_SVC_MIBAND, mbc.UUID_CHARACTERISTIC_8_USER_SETTINGS)

    def init_firmware_svc(self):
        self.init_svc('firmware', mbc.UUID_SERVICE_FIRMWARE_SERVICE, mbc.UUID_CHARACTERISTIC_FIRMWARE)
        self.init_svc('firmware_data', mbc.UUID_SERVICE_FIRMWARE_SERVICE, mbc.UUID_CHARACTERISTIC_FIRMWARE_DATA)

    # Starts a thread that checks for notifications on the background, delegate handles them
    def toggle_background_notifications(self):
        if not self.notif_thread.isAlive():
            print("Starting Notificaction Thread...")
            self.notif_thread.start()
            print("Notificaction Thread Started!")
        else:
            print("Stopping Notificaction Thread...")
            self.notif_thread.start()
            print("Notificaction Thread Stopped!")

    # Auxiliar methods for authentication/initialization
    def encrypt(self, message):
        aes = AES.new(self.key, AES.MODE_ECB)
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

    # Politely disconnect from device, unsuscribing from notifiations and such
    def disconnect(self):
        if (hasattr(self, 'enabled_notifs')):
            self.waitForNotifications(3)
            for n in self.enabled_notifs:
                print("Disabling %s service notifications status..." % n)
                getattr(self, 'cccd_'+n).write(b"\x00\x00", True)
                self.enabled_notifs.remove(n)
        Peripheral.disconnect(self)

    # Roughly disconnect if something goes poorly (Device gets out of range)
    def force_disconnect(self):
        Peripheral.disconnect(self)

    def monitorHeartRate(self):
        print("Cont. HRM start")
        self.char_hrm_ctrl.write(b'\x15\x01\x00', True)
        self.char_hrm_ctrl.write(b'\x15\x01\x01', True)
        for i in range(30):
            self.waitForNotifications(self.timeout)

    # Disabled: Interval set to 0, Sleep set to 0
    # Enabled:  Interval set to not 0, Sleep set to 0
    # Sleep Only: Interval set to not 0, Sleep set to 1
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
        b_info['prev_charge'] = MiBandTime(self, y, m, d, h, mm, sec=s, dst=0, tz=tz)
        y,m,d,h,mm,s,tz = struct.unpack('<1H6B', b_data[11:19])
        b_info['last_charge'] = MiBandTime(self, y, m, d, h, mm, sec=s, dst=0, tz=tz)
        b_info['last_charge_amount'] = struct.unpack('<1b', b_data[19])[0]
        return b_info

    def getTime(self):
        dtm = self.char_current_time.read()
        return MiBandTime.dateBytesToDatetime(self, dtm)

    def setTime(self, dtm):
        bytes = dtm.getBytes()
        self.char_current_time.write(bytes, True)

    def setTimeToSystem(self):
        now = datetime.datetime.now()
        print("Setting time to %s" % str(now))
        self.setTime(MiBandTime(self, now.year, now.month, now.day, now.hour, now.minute, sec=now.second))

    # Changes time display to time or datetime (not tested on MB3)
    # Probably has a different behavior in MB3, switching the main display
    def setDisplayTimeFormat(self, format):
        pass

    # Changes time display to 12h or 24h format
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
        dtm = MiBandTime(self, date.year, date.month, date.day, date.hour, date.minute)
        self.lastSyncDate = dtm

    # Multiple functions to fetch activity fron the MiBand, implemented as a state machine
    # State is initialized here, but is changed on the appropiate Delegate Class
    def fetch_activity_data(self):
        self.fetch_state = "FETCH"

        # Loop Fetch until finished
        while self.fetch_state == "FETCH":
            self.start_fetching()
            if self.fetch_state == "SUCCESS":
                self.fetch_state = "FETCH"

        # If finished, we're good, if not, abort
        if self.fetch_state == "FINISHED":
            print "Finished Successfully!"
        else:
            print "Finished but something went wrong, not storing data"

        # Return to FETCH state for the next time we fetch
        self.fetch_state = "FETCH"

    # Tells the device we are ready to listen for the incoming ActivityDataFrames
    def start_fetching(self):
        syncDate = self.lastSyncDate

        self.char_fetch.write(bytes(self._activity_data_start_cmd + self._activity_data_type_activity_cmd + syncDate.getBytes()))

        while self.fetch_state != "READY" and self.fetch_state != "FINISHED":
            self.waitForNotifications(self.timeout)

        if self.fetch_state == "READY":
            self.char_fetch.write(self._fetch_cmd)
            while self.fetch_state != "SUCCESS" and self.fetch_state != "TERMINATED" and self.fetch_state != "FINISHED":
                self.waitForNotifications(self.timeout)

    # Write a CSV file with the data stored on the ActivityBuffer and flush it (Should this go here or on SHELL/API????)
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

    # Some simple events we have identified
    def onEvent(self, data):
        if data == 1:
            print "Fell Asleep"
        elif data == 2:
            print "Woke Up"
        elif data == 4:
            print "Button Pressed"

    # Alarms work as a queue, we can't read them, so they have to be stored locally
    # Watch out for inconsistencies when using multiple clients (Shell/API)
    def queueAlarm(self, hour, minute, repetitionMask=128, enableAlarm=True):
        if len(self.alarms) >= 5:
            print "Can't store more than 5 alarms at a time."
            return -1
        else:
            alarm = MiBandAlarm(hour, minute, enabled=enableAlarm,
                                            repetitionMask=repetitionMask)
            self.alarms.append(alarm)
            index = len(self.alarms)-1
            print "Writing Alarm {0} at position {1}".format(str(alarm), index)
            self.char_config.write(alarm.getMessage(index))
            self.waitForNotifications(self.timeout)
            return index

    # Modify alarm
    def setAlarm(self, index, hour, minute, repetitionMask, enableAlarm):
        if index >= len(self.alarms):
            print "Alarm doesn't exist."
            return False
        else:
            if repetitionMask == 0:
                repetitionMask = 128
            alarm = MiBandAlarm(hour, minute, enabled=enableAlarm,
                                            repetitionMask=repetitionMask)
            self.alarms[index] = alarm
            print "Writing Alarm {0} at position {1}".format(str(alarm), index)
            self.char_config.write(alarm.getMessage(index))
            self.waitForNotifications(self.timeout)
            return True

    # Change alarm between ON/OFF state
    def toggleAlarm(self, index):
        alarm = self.alarms[index]

        print "{0} Alarm {1}".format("Enabling" if not alarm.enabled else "Disabling", str(alarm))
        self.alarms[index].toggle()

        self.char_config.write(alarm.getMessage(index))
        self.waitForNotifications(self.timeout)

    # Change a weekday on which the alarm repeats between ON/OFF (0 = Monday)
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
        # Tricky, move all alarms one position, starting at the deleted one,
        # and delete the last one

        alarm = self.alarms[index]

        print "Deleting alarm {0}".format(str(alarm))
        for i in range (index+1, len(self.alarms)):
            alarm = self.alarms[i]
            self.char_config.write(alarm.getMessage(i))
            self.waitForNotifications(self.timeout)

        last = len(self.alarms)-1
        alarm = MiBandAlarm(0, 0, enabled=False)
        self.char_config.write(alarm.getMessage(last))
        self.waitForNotifications(self.timeout)

        del self.alarms[index]

    def cleanAlarms(self):
        print "Clearing all alarms from device"
        for i in range(10):
            alarm = MiBandAlarm(0, 0, enabled=False)
            self.char_config.write(alarm.getMessage(i))
            self.waitForNotifications(self.timeout)
        self.alarms = []


    # Sets user info for data interpretation, alias is just a code, not relevant
    # Pairing and device-identification is done by auto-generated auth keys
    # If the stored key changes, official MiFit app will delete user data
    # Watch out for changes like these
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

    # This is pretty different between MB2 and MB3, so it's left out for each class
    # to implement it. Currently only implemented in MB2
    # Probable we will need to change method's signature to take a BOOL ARRAY
    # because display items are very different bewteen MB2 and MB3
    def setDisplayItems(self, steps=False, distance=False, calories=False, heartrate=False, battery=False):
        pass

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

    # Very dangerous, auth not required, just connection
    # Will reset everything to factory, DELETE data AND CHANGE DEVICE'S MAC
    # DO NOT USE LIGHTLY
    # ALEX MUCHO CUIDAO QUE LA LIAS
    def factoryReset(self, force=False):
        if not force:
            print ("Factory resetting will wipe everything and change the device's MAC, use 'force' parameter if you know what you are doing")
        else:
            print("Resetting Device...")
            self.char_config.write(b'\x06\x0b\x00\x01')
            self.waitForNotifications(self.timeout)
            self.disconnect()

    # NO IDEA OF WHAT THIS DOES TO THE MIBAND LOL
    def reboot(self):
        self.char_firmware.write(b'\x05')
        self.waitForNotifications(self.timeout)
