import binascii
import struct
from bluepy.btle import DefaultDelegate
from mibandtime import MiBandTime
from miband_activity_frame import MiBandActivityFrame

class MiBand3Delegate(DefaultDelegate):

    """This Class inherits DefaultDelegate to handle the different notifications."""
    def __init__(self, device):
        DefaultDelegate.__init__(self)
        self.device = device
        self.device.fetch_state = "FETCH"
        self.pulledBytes = 0
        self.sessionBytes = 0
        self.totalBytes = 0
        self.fetchCount = 0
        self.fetchDate = None
        self.device.activityDataBuffer = []

    def handleNotification(self, hnd, data):
        # Debug purposes
        # print("HANDLE: " + str(hex(hnd)))
        # print("DATA: " + str(binascii.hexlify(data)))
        if hasattr(self.device, 'char_auth') and hnd == self.device.char_auth.getHandle():
            if data[:3] == b'\x10\x01\x01':
                self.device.req_rdn()
            elif data[:3] == b'\x10\x01\x04':
                self.device.state = "ERROR: Key Sending failed"
            elif data[:3] == b'\x10\x02\x01':
                random_nr = data[3:]
                self.device.send_enc_rdn(random_nr)
            elif data[:3] == b'\x10\x02\x04':
                self.device.state = "ERROR: Something wrong when requesting the random number..."
            elif data[:3] == b'\x10\x03\x01':
                print("Authenticated!")
                self.device.state = "AUTHENTICATED"
            elif data[:3] == b'\x10\x03\x04':
                print("Encryption Key Auth Fail, sending new key...")
                self.device.send_key()
            else:
                self.device.state = "ERROR: Auth failed"
            #print("Auth Response: " + str(binascii.hexlify(data)))

        elif hasattr(self.device, 'char_hrm') and hnd == self.device.char_hrm.getHandle():
            rate = struct.unpack('bb', data)[1]
            print("Heart Rate: " + str(rate))

        elif hasattr(self.device, 'char_battery') and hnd == self.device.char_battery.getHandle():
            if data[:3] == b'\x10\x17\x01':
                print "Success reading Battery Level"
            else:
                print("Unhandled Battery Response " + hex(hnd) + ": " + str(binascii.hexlify(data)))

        elif hasattr(self.device, 'char_activity') and hnd == self.device.char_activity.getHandle():
            self.pulledBytes = len(data)
            self.sessionBytes += len(data)
            self.totalBytes += len(data)
            data = data[1:]
            for i in range(len(data)/4):
                frame = data[i*4:(i*4)+4]
                act_type, act_intens, act_steps, act_heart = struct.unpack("4B", frame)
                parsed_frame = MiBandActivityFrame(self.device, self.fetchDate, act_type, act_intens, act_steps, act_heart)
                self.device.activityDataBuffer.append(parsed_frame)
                #parsed_frame
                self.fetchDate = self.fetchDate.addMinutes(1)

        elif hasattr(self.device, 'char_fetch') and hnd == self.device.char_fetch.getHandle():
            if data[:3] == b'\x10\x02\x04':
                self.device.fetch_state = "ERROR"
            elif data[:3] == b'\x10\x01\x01':
                bts, year, month, day, hour, min, dst, tz = struct.unpack('<IH6B', data[3:])
                self.fetchDate = MiBandTime(self.device, year, month, day, hour, min)
                if (bts > 0):
                    print("Fetching {0} activity frames since {1}".format(bts, self.fetchDate))
                    print("Fetch Round {0}".format(self.fetchCount))
                    self.device.fetch_state = "READY"
                else:
                    self.fetchCount = 0
                    self.sessionBytes = 0
                    self.totalBytes = 0
                    self.device.fetch_state = "FINISHED"
            elif data[:3] == b'\x10\x02\x01':
                print("Pulled {0} bytes this session".format(self.sessionBytes))
                self.sessionBytes = 0
                if (self.fetchDate.minutesUntilNow() > 0):
                    if (self.fetchCount >= 5):
                        print ("Fetched {0} rounds, not fetching any more now".format(self.fetchCount))
                        self.fetchCount = 0
                        self.sessionBytes = 0
                        self.totalBytes = 0
                        self.device.fetch_state = "FINISHED"
                    else:
                        self.device.fetch_state = "SUCCESS"
                        self.device.lastSyncDate = self.fetchDate
                        self.fetchCount += 1
                else:
                    self.fetchCount = 0
                    self.sessionBytes = 0
                    self.totalBytes = 0
                    self.device.fetch_state = "FINISHED"
                self.device.lastSyncDate = self.fetchDate
            else:
                self.fetchCount = 0
                self.sessionBytes = 0
                self.totalBytes = 0
                print("Error fetching, pleade check code and retry: " + str(binascii.hexlify(data)))
                self.device.fetch_state = "TERMINATED"
            #"DELEGATE: ", self.device.fetch_state

        elif hasattr(self.device, 'char_dev_event') and hnd == self.device.char_dev_event.getHandle():
            self.device.onEvent(struct.unpack('B', data)[0])

        elif hasattr(self.device, 'char_config') and hnd == self.device.char_config.getHandle():
            if data[:3] == b'\x10\x02\x04':
                print "ERROR Configuring"
            if data[:3] == b'\x10\x62\x05':
                print "ERROR Configuring, too many parameters"
            elif data[:3] == b'\x10\x02\x01':
                print "SUCCESS Configuring Alarm Endpoint"
            elif data[:3] == b'\x10\x0a\x01':
                print "SUCCESS Configuring Display Endpoint"
            elif data[0] == b'\x10' and data[-1] == b'\x01':
                print "SUCCESS Configuring %s Endpoint" % str(binascii.hexlify(data[1:-1]))
            else:
                print("Unhandled Configuration Response " + hex(hnd) + ": " + str(binascii.hexlify(data)))

        elif hasattr(self.device, 'char_user_settings') and hnd == self.device.char_user_settings.getHandle():
            print("Unhandled User Settings Response " + hex(hnd) + ": " + str(binascii.hexlify(data)))

        else:
            print("Unhandled Response " + hex(hnd) + ": " + str(binascii.hexlify(data)))
