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
services_data = json.load(open(lib_path + 'mb3services.json'))

def string_hashcode(s):
    h = 0
    for c in s:
        h = (31 * h + ord(c)) & 0xFFFFFFFF
    return ((h + 0x80000000) & 0xFFFFFFFF) - 0x80000000


class MiBand3(Peripheral):
    _send_rnd_cmd = struct.pack('<2s', b'\x02\x08')
    _send_enc_key = struct.pack('<2s', b'\x03\x08')
    _fetch_cmd = struct.pack('<1s', b'\x02')
    _activity_data_start_cmd = struct.pack('<1s', b'\x01')
    _activity_data_type_activity_cmd = struct.pack('<1s', b'\x01')

    def __init__(self, addr, key, sleepOffset=0, initialize=False):
        Peripheral.__init__(self, addr, addrType=ADDR_TYPE_RANDOM)
        print("Connected")

        self.key = key
        self._send_key_cmd = struct.pack('<18s', b'\x01\x08' + str(self.key))

        self.timeout = 2
        self.state = None
        self.fetch_state = "FETCH"
        self.sleepOffset = sleepOffset
        self.activityDataBuffer = []
        self.lastSyncDate = MiBand2Time(self, 2000, 00, 00, 00, 00)
        self.alarms = []
        self.setDelegate(MiBand2Delegate(self))

        self.svcs = self.getServices()

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
        self.init_time_svc()
        self.init_batt_svc()

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

    def force_disconnect(self):
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

    # def init_svc(self, name, svc_uuid, char_uuid):
    #     if (not hasattr(self, 'char_'+name)):
    #         svc_data = self.getServiceByUUID(svc_uuid)
    #         char = svc_data.getCharacteristics(char_uuid)[0]
    #         svc = Service(self, svc_uuid, svc_data.hndStart, svc_data.hndEnd)
    #         setattr(self, 'char_'+name, Characteristic(self, char_uuid, char.handle, char.properties, char.valHandle))
    #         if len(char.getDescriptors()) > 0:
    #             setattr(self, 'cccd_'+name, Descriptor(self, char.descs[0].uuid, char.descs[0].handle))
    #             print("Enabling %s notifications..." % name)
    #             getattr(self, 'cccd_'+name).write(b"\x01\x00", True)
    #             self.enabled_notifs.append(name)

    def init_auth_svc(self):
        self.init_svc('auth', mb2c.UUID_SVC_MIBAND2, mb2c.UUID_CHARACTERISTIC_AUTH)

    def init_activity_svc(self):
        self.init_svc('activity', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_5_ACTIVITY_DATA)

    def init_fetch_svc(self):
        self.init_svc('fetch', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_4_FETCH)

    def init_batt_svc(self):
        self.init_svc('battery', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_6_BATTERY_INFO)

    def init_time_svc(self):
        self.init_svc('current_time', mb2c.UUID_SVC_MIBAND, mb2c.UUID_CHARACTERISTIC_CURRENT_TIME)

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
