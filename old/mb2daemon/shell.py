import json
import threading
import binascii
from bluepy.btle import Scanner, DefaultDelegate, BTLEException
import re
import sys
import struct
import Queue
sys.path.append('/home/miband2server/mb2daemon/lib')
from miband2 import MiBand2
from miband2time import MiBand2Time

q = Queue.Queue()
max_connections = 5
# For automated download stablish a period in which we don't download data
# activity_fetch_cooldown = 6 * 60
connected_devices = {}
mibands = {}
registered_devices = json.load(open('storage/registered_devices.json'))
devices_last_sync = json.load(open('storage/devices_last_sync.json'))


class MiBand2ScanDelegate(DefaultDelegate):
    def __init__(self):
        DefaultDelegate.__init__(self)
        self.tmp_devices = {}

    def handleDiscovery(self, dev, isNewDev, isNewData):
        try:
            name = dev.getValueText(9)
            serv = dev.getValueText(2)
            if name == 'MI Band 2' and serv == 'e0fe' and dev.addr:
                self.tmp_devices[dev.addr] = dev
        except:
            print "ERROR"


def scan_miband2(scanner,):
    print("Scanning!")
    scanner.clear()
    scanner.start()
    t = threading.currentThread()
    while getattr(t, "do_scan", True):
        scanner.process(0.1)
    print("Stopped scanning...")
    scanner.stop()

def save_registered(devs, sync):
    with open('storage/registered_devices.json', 'wb') as outfile:
        json.dump(devs, outfile)
    with open('storage/devices_last_sync.json', 'wb') as outfile:
        json.dump(sync, outfile)

def worker():
    while True:
        item = q.get()
        do_fetch_activity(item)
        q.task_done()

def do_fetch_activity(item):
    print "Fetching MiBand2 [%s] activity!" % item
    if item not in connected_devices.keys():
        try:
            mb2 = MiBand2(item, initialize=False)
            connected_devices[item] = mb2
        except BTLEException as e:
            print("There was a problem connecting this MiBand2, try again later")
            print e
    try:
        if item in devices_last_sync.keys():
            connected_devices[item].setLastSyncDate(devices_last_sync[item])
        connected_devices[item].send_alert(b'\x01')
        connected_devices[item].fetch_activity_data()
        connected_devices[item].send_alert(b'\x01')
        devices_last_sync[item] = str(connected_devices[item].lastSyncDate)
        print "Finished fetching MiBand2 [%s] activity!" % item
    except BTLEException as e:
        print("There was a problem retrieving this MiBand2's activity, try again later")
        print e
    finally:
        connected_devices[item].disconnect()
        del connected_devices[item]

def main():
    sc = Scanner()
    scd = MiBand2ScanDelegate()
    sc.withDelegate(scd)

    scan_thread = threading.Thread(target=scan_miband2, args=(sc,))
    scan_thread.start()

    for i in range(max_connections):
         t = threading.Thread(target=worker)
         t.daemon = True
         t.start()

    while True:
        try:
            s = raw_input('> ')
        except:
            break

        try:
            command = s.strip().lower()
            if command == "exit":
                scan_thread.do_scan = False
                scan_thread.join()
                print ("Disconnecting from %s devices" % len(connected_devices.values()))
                for con in connected_devices.values():
                    con.disconnect()
                print("Saving changes to Registered Devices storage")
                save_registered(registered_devices, devices_last_sync)
                break

            elif command == "save":
                print("Saving changes to Registered Devices storage")
                save_registered(registered_devices, devices_last_sync)
            elif command == "devices":
                mibands = scd.tmp_devices
                for idx,mb in enumerate(mibands.keys()):
                    str = "[%s] Mi Band 2 (%s) %sdB " % (idx,mb,mibands[mibands.keys()[idx]].rssi)
                    if mb in registered_devices:
                        str += "[R]"
                    if mb in connected_devices:
                        str += "[C]"
                    print str
            elif "alert" in command:
                arg = re.search("\w+\s+(\d+)\s+(\d+)", command)
                if arg != None and len(arg.groups()) == 2:
                    dev_id = int(arg.groups()[0])
                    alert_int = int(arg.groups()[1])
                    if mibands.keys()[dev_id] in registered_devices:
                        if mibands.keys()[dev_id] in connected_devices.keys():
                            try:
                                mb2 = connected_devices[mibands.keys()[dev_id]]
                                data = struct.pack('B', alert_int)
                                mb2.send_alert(data)
                                print "Sending Notification: " + binascii.hexlify(data)
                            except BTLEException:
                                print("There was a problem alerting this MiBand2, try again later")
                        else:
                            print("That MiBand2 is not connected!")
                    else:
                        print("That MiBand2 is not registered")
                else:
                    print("'alert' takes two parameters")
            elif "unregister" in command:
                arg = re.search("\w+\s+(\d+)", command)
                if arg != None and len(arg.groups()) == 1:
                    dev_id = int(arg.groups()[0])
                    if mibands.keys()[dev_id] in registered_devices:
                        if not mibands.keys()[dev_id] in connected_devices.values():
                            try:
                                registered_devices.remove(mibands.keys()[dev_id])
                                print("MiBand2 unregistered!")
                            except BTLEException:
                                print("There was a problem unregistering this MiBand2, try again later")
                        else:
                            print("Disconnect the miBand2 first!")
                    else:
                        print("That MiBand2 is not registered")
                else:
                    print("'unregister' takes only one parameter")

            elif "register" in command:
                arg = re.search("\w+\s+(\d+)", command)
                if arg != None and len(arg.groups()) == 1:
                    dev_id = int(arg.groups()[0])
                    if mibands.keys()[dev_id] in registered_devices:
                        print("That MiBand2 is already registered")
                    else:
                        try:
                            mb2 = MiBand2(mibands.keys()[dev_id], initialize=True)
                            registered_devices.append(mibands.keys()[dev_id])
                        except BTLEException as e:
                            print("There was a problem disconnecting this MiBand2, try again later")
                            print e
                else:
                    print("'register' takes only one parameter")

            elif "disconnect" in command:
                arg = re.search("\w+\s+(\d+)", command)
                if arg != None and len(arg.groups()) == 1:
                    dev_id = int(arg.groups()[0])
                    if len(connected_devices.keys()) >= max_connections:
                        print("Can't connect to more than 5 devices at the same time, disconnect some")
                    else:
                        if mibands.keys()[dev_id] in connected_devices.keys():
                            try:
                                mb2 = connected_devices[mibands.keys()[dev_id]]
                                mb2.disconnect()
                                del connected_devices[mibands.keys()[dev_id]]
                                del mb2
                                print ("MiBand2 disconnected!")
                            except BTLEException as e:
                                print("There was a problem disconnecting this MiBand2, try again later")
                                print e
                        else:
                            print("That MiBand2 isn't connected!")
                else:
                    print("'connect' takes only one parameter")

            elif "connect" in command:
                arg = re.search("\w+\s+(\d+)", command)
                if arg != None and len(arg.groups()) == 1:
                    dev_id = int(arg.groups()[0])
                    if len(connected_devices.keys()) >= 5:
                        print("Can't connect to more than 5 devices at the same time, disconnect some")
                    else:
                        if mibands.keys()[dev_id] in registered_devices:
                            if mibands.keys()[dev_id] in connected_devices.keys():
                                print("That MiBand2 is already connected")
                            else:
                                try:
                                    mb2 = MiBand2(mibands.keys()[dev_id], initialize=False)
                                    connected_devices[mibands.keys()[dev_id]] = mb2
                                except BTLEException as e:
                                    print("There was a problem connecting to this MiBand2, try again later")
                                    print e
                        else:
                            print("You have to register the MiBand2 before connecting to it")
                else:
                    print("'connect' takes only one parameter")

            elif "activity" in command:
                arg = re.search("\w+\s+(\w+)", command)
                if arg != None and len(arg.groups()) == 1:
                    if arg.groups()[0] == 'all':
                        print("Fetching all registered and in range Miband2's activity data")
                        # Check that the registered device is present on the scanned mibands list
                        for item in filter(lambda x: x in registered_devices, mibands.keys()):
                            q.put(item)
                    else:
                        dev_id = int(arg.groups()[0])
                        if mibands.keys()[dev_id] in registered_devices:
                            q.put(mibands.keys()[dev_id])
                        else:
                            print("MiBand2 should be registered before fetching activity data")
                else:
                    print("'activity' takes only one parameter")
            elif command == '':
                pass
            else:
                print ("Unknown command %s, try using 'help'" % command)

        except OSError:
            print 'Invalid command'

if __name__ == '__main__':
    main()
