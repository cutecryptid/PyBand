#!/usr/bin/env python2
import struct
import re
from Crypto.Cipher import AES
from bluepy.btle import Peripheral, ADDR_TYPE_RANDOM, BTLEException
from miband2time import MiBand2Time
from miband2delegate import MiBand2Delegate

UUID_SVC_MIBAND = "0000fee0-0000-1000-8000-00805f9b34fb"
UUID_SVC_MIBAND2 = "0000fee100001000800000805f9b34fb"
UUID_CHAR_AUTH = "00000009-0000-3512-2118-0009af100700"
UUID_SVC_ALERT = "00001802-0000-1000-8000-00805f9b34fb"
UUID_CHAR_ALERT = "00002a06-0000-1000-8000-00805f9b34fb"
UUID_SVC_ALERT_NOTIFICATION = "00001811-0000-1000-8000-00805f9b34fb"
UUID_CHAR_NEW_ALERT = "00002a46-0000-1000-8000-00805f9b34fb"
UUID_SVC_HEART_RATE = "0000180d00001000800000805f9b34fb"
UUID_CHAR_HRM_MEASURE = "00002a3700001000800000805f9b34fb"
UUID_CHAR_HRM_CONTROL = "00002a3900001000800000805f9b34fb"
BASE_UUID = "0000fee1-0000-1000-8000-00805f9b34fb";
UUID_SERVICE_HEART_RATE = "0000180d-0000-1000-8000-00805f9b34fb";
UUID_SERVICE_FIRMWARE_SERVICE = "00001530-0000-3512-2118-0009af100700";
UUID_CHARACTERISTIC_FIRMWARE = "00001531-0000-3512-2118-0009af100700";
UUID_CHARACTERISTIC_FIRMWARE_DATA = "00001532-0000-3512-2118-0009af100700";
UUID_UNKNOWN_CHARACTERISTIC0 = "00000000-0000-3512-2118-0009af100700";
UUID_UNKNOWN_CHARACTERISTIC1 = "00000001-0000-3512-2118-0009af100700";
UUID_UNKNOWN_CHARACTERISTIC2 = "00000002-0000-3512-2118-0009af100700";

# Alarms, Display and other configuration.

UUID_CHARACTERISTIC_CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb";
UUID_CHARACTERISTIC_3_CONFIGURATION = "00000003-0000-3512-2118-0009af100700";
UUID_CHARACTERISTIC_4_FETCH = "00000004-0000-3512-2118-0009af100700";
UUID_CHARACTERISTIC_5_ACTIVITY_DATA = "00000005-0000-3512-2118-0009af100700";
UUID_CHARACTERISTIC_6_BATTERY_INFO = "00000006-0000-3512-2118-0009af100700";
UUID_CHARACTERISTIC_7_REALTIME_STEPS = "00000007-0000-3512-2118-0009af100700";
UUID_CHARACTERISTIC_8_USER_SETTINGS = "00000008-0000-3512-2118-0009af100700";

UUID_CHARACTERISTIC_AUTH = "00000009-0000-3512-2118-0009af100700";
UUID_CHARACTERISTIC_DEVICEEVENT = "00000010-0000-3512-2118-0009af100700";

ALERT_LEVEL_NONE = 0;
ALERT_LEVEL_MESSAGE = 1;
ALERT_LEVEL_PHONE_CALL = 2;
ALERT_LEVEL_VIBRATE_ONLY = 3;

HRM_COMMAND = 0x15
HRM_MODE_SLEEP      = 0x00
HRM_MODE_CONTINUOUS = 0x01
HRM_MODE_ONE_SHOT   = 0x02

CCCD_UUID = 0x2902

RESPONSE = 0x10;

SUCCESS = 0x01;
COMMAND_ACTIVITY_DATA_START_DATE = 0x01;
COMMAND_ACTIVITY_DATA_TYPE_ACTIVTY = 0x01;
COMMAND_ACTIVITY_DATA_TYPE_UNKNOWN_2 = 0x02;
# issued on first connect, followd by COMMAND_XXXX_ACTIVITY_DATA instead of COMMAND_FETCH_DATA
COMMAND_ACTIVITY_DATA_XXX_DATE = 0x02;

# TODO: Key should be generated and stored during init

csv_directory = "activity_log/"

class MiBand2(Peripheral):
    _KEY = b'\x30\x31\x32\x33\x34\x35\x36\x37\x38\x39\x40\x41\x42\x43\x44\x45'
    _send_key_cmd = struct.pack('<18s', b'\x01\x08' + _KEY)
    _send_rnd_cmd = struct.pack('<2s', b'\x02\x08')
    _send_enc_key = struct.pack('<2s', b'\x03\x08')
    _fetch_cmd = struct.pack('<1s', b'\x02')
    _activity_data_start_cmd = struct.pack('<1s', b'\x01')
    _activity_data_type_activity_cmd = struct.pack('<1s', b'\x01')

    def __init__(self, addr, sleepOffset=0, initialize=False):
        Peripheral.__init__(self, addr, addrType=ADDR_TYPE_RANDOM)
        print("Connected")

        self.battery_info = {
            'level': 0,
            'status': 'normal',
            'prev_charge': None,
            'last_charge': None,
            'last_charge_amount': 0
        }

        self.timeout = 5.0
        self.state = None
        self.fetch_state = "FETCH"
        self.sleepOffset = sleepOffset
        self.activityDataBuffer = []
        # TODO: lastSyncDate should be dynamically fetched
        self.lastSyncDate = MiBand2Time(self, 2000, 00, 00, 00, 00)
        self.setDelegate(MiBand2Delegate(self))
        # Enable auth service notifications on startup
        self.svcs = self.getServices()
        self.init_auth_svc()
        self.auth_notif(True)
        self.waitForNotifications(0.1)
        self.setSecurityLevel(level="medium")

        if initialize:
            self.initialize()
            self.disconnect()
        else:
            self.authenticate()

    def disconnect(self):
        if(hasattr(self, 'cccd_auth')):
            self.auth_notif(False)
        if(hasattr(self, 'cccd_activity')):
            self.activity_notif(False)
        if(hasattr(self, 'cccd_fetch')):
            self.fetch_notif(False)
        if(hasattr(self, 'cccd_hrm')):
            self.hrm_notif(False)
        if(hasattr(self, 'cccd_dev_event')):
            self.dev_event_notif(False)
        Peripheral.disconnect(self)

    def init_auth_svc(self):
        if (not hasattr(self, 'char_auth')):
            svc = self.getServiceByUUID(UUID_SVC_MIBAND2)
            self.char_auth = svc.getCharacteristics(UUID_CHAR_AUTH)[0]
            self.cccd_auth = self.char_auth.getDescriptors(forUUID=CCCD_UUID)[0]

    def init_activity_svc(self):
        if (not hasattr(self, 'char_activity')):
            svc = self.getServiceByUUID(UUID_SVC_MIBAND)
            self.char_activity = svc.getCharacteristics(UUID_CHARACTERISTIC_5_ACTIVITY_DATA)[0]
            self.cccd_activity = self.char_activity.getDescriptors(forUUID=CCCD_UUID)[0]

    def init_fetch_svc(self):
        if (not hasattr(self, 'char_fetch')):
            svc = self.getServiceByUUID(UUID_SVC_MIBAND)
            self.char_fetch = svc.getCharacteristics(UUID_CHARACTERISTIC_4_FETCH)[0]
            self.cccd_fetch = self.char_fetch.getDescriptors(forUUID=CCCD_UUID)[0]

    def init_alert_svc(self):
        if (not hasattr(self, 'char_alert')):
            svc = self.getServiceByUUID(UUID_SVC_ALERT)
            self.char_alert = svc.getCharacteristics(UUID_CHAR_ALERT)[0]
            #svc = self.getServiceByUUID(UUID_SVC_ALERT_NOTIFICATION)
            #self.char_newalert = svc.getCharacteristics(UUID_CHAR_NEW_ALERT)[0]
            #self.cccd_newalert = self.char_newalert.getDescriptors(forUUID=CCCD_UUID-1)[0]

    def init_hrm_svc(self):
        if (not hasattr(self, 'char_hrm_ctrl')):
            svc = self.getServiceByUUID(UUID_SVC_HEART_RATE)
            self.char_hrm_ctrl = svc.getCharacteristics(UUID_CHAR_HRM_CONTROL)[0]
            self.char_hrm = svc.getCharacteristics(UUID_CHAR_HRM_MEASURE)[0]
            self.cccd_hrm = self.char_hrm.getDescriptors(forUUID=CCCD_UUID)[0]

    def init_batt_svc(self):
        if (not hasattr(self, 'char_batt')):
            svc = self.getServiceByUUID(UUID_SVC_MIBAND)
            self.char_battery = svc.getCharacteristics(UUID_CHARACTERISTIC_6_BATTERY_INFO)[0]

    def init_time_svc(self):
        if (not hasattr(self, 'char_current_time')):
            svc = self.getServiceByUUID(UUID_SVC_MIBAND)
            self.char_current_time = svc.getCharacteristics(UUID_CHARACTERISTIC_CURRENT_TIME)[0]

    def init_dev_event_svc(self):
        if (not hasattr(self, 'char_device_event')):
            svc = self.getServiceByUUID(UUID_SVC_MIBAND)
            self.char_dev_event = svc.getCharacteristics(UUID_CHARACTERISTIC_DEVICEEVENT )[0]
            self.cccd_dev_event = self.char_dev_event.getDescriptors(forUUID=CCCD_UUID)[0]

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

    def auth_notif(self, status):
        if status:
            print("Enabling Auth Service notifications status...")
            self.cccd_auth.write(b"\x01\x00", True)
        elif not status:
            print("Disabling Auth Service notifications status...")
            self.cccd_auth.write(b"\x00\x00", True)
        else:
            print("Something went wrong while changing the Auth Service notifications status...")

    def activity_notif(self, status):
        self.init_activity_svc()
        if status:
            print("Enabling Activity Service notifications status...")
            self.cccd_activity.write(b"\x01\x00", True)
        elif not status:
            print("Disabling Activity Service notifications status...")
            self.cccd_activity.write(b"\x00\x00", True)
        else:
            print("Something went wrong while changing the Activity Service notifications status...")

    def fetch_notif(self, status):
        self.init_fetch_svc()
        if status:
            print("Enabling Fetch Service notifications status...")
            self.cccd_fetch.write(b"\x01\x00", True)
        elif not status:
            print("Disabling Fetch Service notifications status...")
            self.cccd_fetch.write(b"\x00\x00", True)
        else:
            print("Something went wrong while changing the Fetch Service notifications status...")

    def hrm_notif(self, status):
        self.init_hrm_svc()
        if status:
            print("Enabling HRM Service notifications status...")
            self.cccd_hrm.write(b"\x01\x00", True)
        elif not status:
            print("Disabling HRM Service notifications status...")
            self.cccd_hrm.write(b"\x00\x00", True)
        else:
            print("Something went wrong while changing the HRM Service notifications status...")

    def dev_event_notif(self, status):
        self.init_dev_event_svc()
        if status:
            print("Enabling Device Events notifications status...")
            self.cccd_dev_event.write(b"\x01\x00", True)
        elif not status:
            print("Disabling Device Events notifications status...")
            self.cccd_dev_event.write(b"\x00\x00", True)
        else:
            print("Something went wrong while changing the Device Events notifications status...")

    # def alert_notif(self, status):
    #     self.init_alert_svc()
    #     if status:
    #         print("Enabling New Alerts notifications status...")
    #         self.cccd_newalert.write(b"\x01\x00")
    #     elif not status:
    #         print("Disabling New Alerts notifications status...")
    #         self.cccd_newalert.write(b"\x00\x00")
    #     else:
    #         print("Something went wrong while changing the New Alerts notifications status...")

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
            self.waitForNotifications(0.1)
            if self.state == "AUTHENTICATED":
                return True
            elif self.state:
                return False

    def authenticate(self):
        self.req_rdn()

        while True:
            self.waitForNotifications(0.1)
            if self.state == "AUTHENTICATED":
                return True
            elif self.state:
                return False


    def monitorHeartRate(self):
        self.init_hrm_svc()
        self.hrm_notif(True)
        print("Cont. HRM start")
        self.char_hrm_ctrl.write(b'\x15\x01\x00', True)
        self.char_hrm_ctrl.write(b'\x15\x01\x01', True)
        for i in range(30):
            self.waitForNotifications(1.0)


    def req_battery(self):
        self.init_batt_svc()
        print("Requesting Battery Info")
        b_data = self.char_battery.read()
        self.battery_info['level'] = struct.unpack('1b', b_data[1])[0]
        self.battery_info['status'] = 'normal' if struct.unpack('1b', b_data[2])[0] == 0 else 'charging'
        y,m,d,h,mm,s,tz = struct.unpack('<1H6B', b_data[3:11])
        self.battery_info['prev_charge'] = MiBand2Time(self, y, m, d, h, mm, sec=s, dst=0, tz=tz)
        y,m,d,h,mm,s,tz = struct.unpack('<1H6B', b_data[11:19])
        self.battery_info['last_charge'] = MiBand2Time(self, y, m, d, h, mm, sec=s, dst=0, tz=tz)
        self.battery_info['last_charge_amount'] = struct.unpack('<1b', b_data[19])[0]
        return self.battery_info

    def getTime(self):
        self.init_time_svc()
        dtm = self.char_current_time.read()
        return MiBand2Time.dateBytesToDatetime(self, dtm)

    def setTime(self, dtm):
        self.init_time_svc()
        bytes = dtm.getBytes()
        self.char_current_time.write(bytes, True)

    def getLastSyncDate(self):
        return self.lastSyncDate

    def setLastSyncDate(self,datestring):
        m = re.search("(\d+)-(\d+)-(\d+)\s+(\d+):(\d+)", datestring)
        if m.groups() != None:
            date = list(map(lambda x: int(x), m.groups()))
            dtm = MiBand2Time(self, date[0], date[1], date[2], date[3], date[4])
            self.lastSyncDate = dtm
        else:
            print("Datestring is not in correct format")

    def fetch_activity_data(self, save_route=None):

        self.init_fetch_svc()
        self.init_activity_svc()
        self.fetch_notif(True)
        self.activity_notif(True)

        while self.fetch_state == "FETCH":
            self.start_fetching()
            if self.fetch_state == "SUCCESS":
                self.fetch_state = "FETCH"

        if self.fetch_state == "FINISHED":
            print "Finished Successfully!"
            self.store_activity_data(save_route)
        else:
            print "Finished but something went wrong, not storing data"

        self.fetch_state = "FETCH"


    def start_fetching(self):
        syncDate = self.lastSyncDate

        self.char_fetch.write(bytes(self._activity_data_start_cmd + self._activity_data_type_activity_cmd + syncDate.getBytes()))

        while self.fetch_state != "READY" and self.fetch_state != "FINISHED":
            self.waitForNotifications(0.1)

        if self.fetch_state == "READY":
            self.char_fetch.write(self._fetch_cmd)
            while self.fetch_state != "SUCCESS" and self.fetch_state != "TERMINATED" and self.fetch_state != "FINISHED":
                self.waitForNotifications(0.1)

    def store_activity_data(self, base_route=None):
        print("Storing {0} activity data frames".format(len(self.activityDataBuffer)))
        if base_route == None:
            csv_file = open(csv_directory + self.addr.replace(':','')+'_'+str(self.activityDataBuffer[0].dtm).replace(':','_')+'-'+str(self.activityDataBuffer[-1].dtm).replace(':','_')+'.csv'.replace(' ', ''), "w")
        else:
            csv_file = open(base_route + self.addr.replace(':','')+'_'+str(self.activityDataBuffer[0].dtm).replace(':','_')+'-'+str(self.activityDataBuffer[-1].dtm).replace(':','_')+'.csv'.replace(' ', ''), "w")
        csv_file.write("device_mac, date, type, intensity, steps, heartrate\n")
        for frame in self.activityDataBuffer:
            csv_file.write(str(self.addr) +", "+ str(frame.dtm)+", "+str(frame.type)+", "+str(frame.intensity)+", "+str(frame.steps)+", "+str(frame.heartrate)+"\n")
        csv_file.close()

    def send_alert(self, code):
        self.init_alert_svc()
        self.char_alert.write(code)

    def event_listen(self):
        self.init_dev_event_svc()
        self.dev_event_notif(True)
        print ("Listening for any event")
        while True:
            self.waitForNotifications(0.1)

    def onEvent(self, data):
        if data == 1:
            print "Fell Asleep"
        elif data == 2:
            print "Woke Up"
        elif data == 4:
            print "Button Pressed"
