#!/usr/bin/env python

import cmd
import pyodbc
import json
import threading
import binascii
from bluepy.btle import Scanner, DefaultDelegate, BTLEException
import re
import sys
import copy
import struct
import datetime
import Queue
import ConfigParser
import argparse
import os
import string
import random
import time
base_route = os.path.dirname(os.path.realpath(__file__))
config_route = base_route + "/configuration"
sys.path.append(base_route + '/lib')
from miband2 import MiBand2, MiBand2Alarm
import miband2db as mb2db

CONFIG_MODE="GERIATIC"

q = Queue.Queue()
max_connections = 5
# For automated download stablish a period in which we don't download data
# activity_fetch_cooldown = 6 * 60
connected_devices = {}
mibands = {}

config = ConfigParser.ConfigParser()
config.readfp(open(config_route + '/mb2_presets.conf'))

class MiBand2ScanDelegate(DefaultDelegate):
    def __init__(self, thresh):
        DefaultDelegate.__init__(self)
        self.tmp_devices = {}
        self.thresh = thresh

    def handleDiscovery(self, dev, isNewDev, isNewData):
        try:
            name = dev.getValueText(9)
            serv = dev.getValueText(2)
            if name == 'MI Band 2' and serv == 'e0fe' and dev.addr and dev.rssi >= self.thresh:
                self.tmp_devices[dev.addr] = {"device": dev, "strikes": 0}
        except:
            print "ERROR"


def read_json(filename, default="{}"):
    try:
        f = open(filename)
    except IOError:
        f = open(filename, 'w')
        f.write(default)
        f.close()
        f = open(filename)
    js = json.load(f)
    f.close()
    return js

def save_local(cmd):
    with open(base_route + '/localdata/registered_devices.json', 'wb') as outfile:
        json.dump(cmd.registered_devices, outfile)
    with open(base_route + '/localdata/devices_last_sync.json', 'wb') as outfile:
        json.dump(cmd.devices_last_sync, outfile)
    with open(base_route + '/localdata/devices_alarms.json', 'wb') as outfile:
        json.dump(cmd.devices_alarms, outfile)
    with open(base_route + '/localdata/devices_keys.json', 'wb') as outfile:
        json.dump(cmd.devices_keys, outfile)

def scan_miband2(scanner,strikes,thresh):
    print("Scanning!")
    scanner.clear()
    scanner.start()
    t = threading.currentThread()
    while getattr(t, "do_scan", True):
        old_devices = copy.deepcopy(scanner.delegate.tmp_devices)
        scanner.process(1)
        for d in old_devices.keys():
            if d in scanner.delegate.tmp_devices.keys() and (d not in connected_devices.keys()):
                if ((old_devices[d]["device"].rssi >= scanner.delegate.tmp_devices[d]["device"].rssi)
                    or scanner.delegate.tmp_devices[d]["device"].rssi < thresh):
                    scanner.delegate.tmp_devices[d]["strikes"] += 1
                    if scanner.delegate.tmp_devices[d]["strikes"] >= strikes:
                        del scanner.delegate.tmp_devices[d]
    print("Stopped scanning...")
    scanner.stop()

def ping_connected(sleeptime):
    print("Pinging connected devices...")
    t = threading.currentThread()
    while getattr(t, "do_ping", True):
        for d in connected_devices.keys():
            try:
                connected_devices[d].char_battery.read()
            except Exception as e:
                print e
                connected_devices[d].force_disconnect()
                del connected_devices[d]
        time.sleep(sleeptime)
    print("Stopped pinging...")

def random_key(length=16):
    return ''.join(random.choice(string.ascii_uppercase + string.digits + string.ascii_lowercase) for _ in range(length))

def worker(cmd):
    while True:
        item = q.get()
        do_fetch_activity(item, cmd)
        q.task_done()

def do_fetch_activity(item, cmd):
    print "Fetching MiBand2 [%s] activity!" % item
    if item not in connected_devices.keys():
        try:
            if not item in cmd.devices_keys.keys():
                cmd.devices_keys[item] = random_key()
            mb2 = MiBand2(addr, self.devices_keys[item], initialize=False)
            connected_devices[item] = mb2
        except BTLEException as e:
            print("There was a problem connecting this MiBand2, try again later")
            print e
    try:
        if args.mode == "db":
            last_sync = mb2db.get_device_last_sync(mb2db.cnxn, item)
        else:
            last_sync = None
            if item in cmd.devices_last_sync.keys():
                last_sync = cmd.devices_last_sync[item]
        if last_sync != None:
            connected_devices[item].setLastSyncDate(last_sync)
        connected_devices[item].send_alert(b'\x03')
        connected_devices[item].fetch_activity_data()
        connected_devices[item].send_alert(b'\x03')
        if len(connected_devices[item].getActivityDataBuffer()) > 0:
            print "Saving Data to DB..."
            if args.mode == "db":
                mb2db.write_activity_data(mb2db.cnxn, connected_devices[item])
            else:
                connected_devices[item].store_activity_data_file(base_route + '/localdata/activity_log/')
        print "Finished fetching MiBand2 [%s] activity!" % item
    except BTLEException as e:
        print("There was a problem retrieving this MiBand2's activity, try again later")
        print e

class MiBand2CMD(cmd.Cmd):
    """Command Processor for intercating with many MiBand2s at a time"""
    def __init__(self):
        cmd.Cmd.__init__(self)
        threshold = -70
        strikes = 5
        pingtimer = 1
        self.sc = Scanner()
        self.scd = MiBand2ScanDelegate(threshold)
        self.sc.withDelegate(self.scd)

        self.mibands = []

        self.scan_thread = threading.Thread(target=scan_miband2, args=(self.sc,strikes,threshold))
        self.scan_thread.start()

        self.ping_thread = threading.Thread(target=ping_connected, args=(pingtimer,))
        self.ping_thread.start()

        for i in range(max_connections):
             t = threading.Thread(target=worker, args=(self,))
             t.daemon = True
             t.start()

        self.prompt =  'MB2S # '

    def exit_safely(self):
        self.scan_thread.do_scan = False
        self.ping_thread.do_ping = False
        self.scan_thread.join()
        print ("Disconnecting from %s devices" % len(connected_devices.values()))
        for con in connected_devices.values():
            con.disconnect()
        return True

    def do_devices(self, line):
        tmp_mibands = copy.deepcopy(self.scd.tmp_devices)
        self.mibands = {k: v["device"] for k, v in tmp_mibands.items()}
        tmp_strikes = {k: v["strikes"] for k, v in tmp_mibands.items()}
        for idx,mb in enumerate(self.mibands.keys()):
            name = "Someone"
            uid = 0
            udata = None
            if args.mode == "db":
                udata = mb2db.get_user_data(mb2db.cnxn, mb2db.get_device_user(mb2db.cnxn, mb))
            else:
                # TODO: User Data on local storage???
                pass
            if udata:
                name = udata["alias"]
                uid = udata["id"]
            str = "[%s]%10s's MB2 <U:%05d> (%s) %sdB S:%s " % (idx,name,uid,mb,self.mibands[self.mibands.keys()[idx]].rssi, "X"*tmp_strikes[self.mibands.keys()[idx]])
            if (args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, mb)) or (args.mode == "json" and mb in self.registered_devices):
                str += "[R]"
            if mb in connected_devices:
                mb2 = connected_devices[mb]
                if args.mode == "db":
                    mb2db.update_battery(mb2db.cnxn, mb2.addr, mb2.battery_info['level'])
                str += "[C] [B:{0:03d}%]".format(mb2.battery_info["level"])
            print str

    def do_reboot(self, params):
        try:
           dev_id = int(params)
        except ValueError:
           print "*** arguments should be numbers"
           return
        except IndexError:
           print "*** alert takes at least one parameter"
           return
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if ((args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]))
            or (args.mode == "json" and self.mibands.keys()[dev_id] in self.registered_devices)):
            if self.mibands.keys()[dev_id] in connected_devices.keys():
                try:
                    mb2 = connected_devices[self.mibands.keys()[dev_id]]
                    mb2.reboot()
                except BTLEException:
                    print("There was a problem rebooting this MiBand2, try again later")
            else:
                print("That MiBand2 is not connected!")
        else:
            print("That MiBand2 is not registered")

    def do_alert(self, params):
        l = params.split()
        if len(l)!=2:
           print "*** invalid number of arguments"
           return
        try:
           l = [int(i) for i in l]
        except ValueError:
           print "*** arguments should be numbers"
           return
        except IndexError:
           print "*** alert takes at least one parameter"
           return
        dev_id = int(l[0])
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        alert_int = int(l[1])
        if ((args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]))
            or args.mode == "json" and self.mibands.keys()[dev_id] in self.registered_devices):
            if self.mibands.keys()[dev_id] in connected_devices.keys():
                try:
                    mb2 = connected_devices[self.mibands.keys()[dev_id]]
                    data = struct.pack('B', alert_int)
                    mb2.send_alert(data)
                    print "Sending Notification: " + binascii.hexlify(data)
                except BTLEException:
                    print("There was a problem alerting this MiBand2, try again later")
            else:
                print("That MiBand2 is not connected!")
        else:
            print("That MiBand2 is not registered")

    def do_configure(self, params):
        l = params.split()
        try:
           dev_id = int(l[0])
           command = ""
           if len(l) > 1:
               command = l[1]
        except ValueError:
           print "*** argument 1 should be number"
           return
        except IndexError:
           print "*** configure takes at least one parameter"
           return
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if command == "":
            print("Using default configuration preset [%s]" % CONFIG_MODE)
            command = CONFIG_MODE
        if not config.has_section(command):
           print "*** invalid configuration preset '%s'" % command
           return
        self.configure_miband(dev_id, command)

    def configure_miband(self, dev_id, preset):
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if ((args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]))
            or args.mode == "json" and self.mibands.keys()[dev_id] in self.registered_devices):
            if self.mibands.keys()[dev_id] in connected_devices.keys():
                try:
                    mb2 = connected_devices[self.mibands.keys()[dev_id]]
                    print("Configuring MiBand to [%s] presets" % preset)
                    if config.has_option(preset, "MonitorHRSleep"):
                        mb2.monitorHeartRateSleep(config.getint(preset, "MonitorHRSleep"))
                    if config.has_option(preset, "MonitorHRInterval"):
                        mb2.setMonitorHeartRateInterval(config.getint(preset, "MonitorHRInterval"))
                    if config.has_option(preset, "DisplayTimeFormat"):
                        mb2.setDisplayTimeFormat(config.get(preset, "DisplayTimeFormat"))
                    if config.has_option(preset, "DisplayTimeHours"):
                        mb2.setDisplayTimeHours(config.getint(preset, "DisplayTimeHours"))
                    if config.has_option(preset, "DistanceUnit"):
                        mb2.setDistanceUnit(config.get(preset, "DistanceUnit"))
                    if config.has_option(preset, "LiftWristActivate"):
                        mb2.setLiftWristToActivate(config.getint(preset, "LiftWristActivate"))
                    if config.has_option(preset, "RotateWristSwitch"):
                        mb2.setRotateWristToSwitchInfo(config.getint(preset, "RotateWristSwitch"))
                    if config.has_option(preset, "DisplayItems"):
                        disp = [x.strip() for x in config.get(preset, 'DisplayItems').split(',')]
                        steps = True if 'steps' in disp else False
                        distance = True if 'distance' in disp else False
                        calories = True if 'calories' in disp else False
                        heartrate = True if 'heartrate' in disp else False
                        battery = True if 'battery' in disp else False
                        mb2.setDisplayItems(steps=steps, distance=distance, calories=calories, heartrate=heartrate, battery=battery)
                    if config.has_option(preset, "DoNotDisturb"):
                        enableLift = config.getint(preset, "DoNotDisturbLift") if config.has_option(preset, "DoNotDisturbLift") else 1
                        mb2.setDoNotDisturb(config.get(preset, "DoNotDisturb"), enableLift=enableLift)
                    if config.has_option(preset, "InactivityWarnings"):
                        start = config.getint(preset, "InactivityWarningsStart") if config.has_option(preset, "InactivityWarningsStart") else 8
                        end = config.getint(preset, "InactivityWarningsEnd") if config.has_option(preset, "InactivityWarningsEnd") else 19
                        threshold = config.getint(preset, "InactivityWarningsThresholdHours") if config.has_option(preset, "InactivityWarningsThresholdHours") else 1
                        mb2.setInactivityWarnings(config.getint(preset, "InactivityWarnings"), threshold=threshold*60, start=(start, 0), end=(end, 0))
                    if config.has_option(preset, "DisplayCaller"):
                        mb2.setDisplayCaller(config.getint(preset, "DisplayCaller"))

                except BTLEException as e:
                    print("There was a problem configuring this MiBand2, try again later")
                    print e
            else:
                print("That MiBand2 is not connected, please connect it before configuring.")
        else:
            print("That MiBand2 is not registered, please register it before configuring.")

    def do_setuser(self, params):
        try:
           l = params.split()
           dev_id = int(l[0])
           if args.mode == "db":
               user_id = int(l[1])
           else:
               # TODO: Not persisted
               user_alias = l[1]
               if l[2] == "M":
                   user_gender = 0
               elif l[2] == "F":
                   user_gender = 1
               else:
                   user_gender = 2
               user_bd_year = int(l[3])
               user_bd_month = int(l[4])
               user_bd_day = 0
               user_weight = float(l[5])
               user_height = int(l[6])
           position = None
           if l[2] == "left":
               position = (0, "left")
           elif l[2] == "right":
               position = (1, "right")
           else:
               print("*** only left and right supported")
               return
        except ValueError:
           print "*** argument should be number"
           return
        except IndexError:
           print "*** setuser takes at least one parameter"
           return
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if args.mode == "db":
            udata = mb2db.get_user_data(mb2db.cnxn, user_id)
        if udata or args.mode == "json":
            if ((args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]))
                or args.mode == "json" and self.mibands.keys()[dev_id] in self.registered_devices):
                if self.mibands.keys()[dev_id] in connected_devices.keys():
                    mb2 = connected_devices[self.mibands.keys()[dev_id]]
                    if args.mode == "db":
                        if mb2db.set_device_user(mb2db.cnxn, mb2.addr, user_id, position[0]):
                            mb2.setUserInfo(udata["alias"], udata["sex"], udata["height"], udata["weight"], udata["birth"])
                    else:
                        mb2.setUserInfo(user_alias, user_gender, user_height, user_weight, (user_bd_year, user_bd_month, user_bd_day))
                    mb2.setWearLocation(position[1])
                else:
                    print("MiBand2 should be connected before setting user data")
            else:
                print("MiBand2 should be registered before setting user data")
        else:
            print("*** user with id %s doesn't exist" % user_id)

    def do_reluser(self, params):
        if args.mode == "db":
            try:
               l = params.split()
               dev_id = int(l[0])
               user_id = int(l[1])
            except ValueError:
               print "*** argument should be number"
               return
            except IndexError:
               print "*** reluser takes at least one parameter"
               return
            if dev_id >= len(self.mibands.keys()):
                print "*** device not in the device list"
                return
            udata = mb2db.get_user_data(mb2db.cnxn, user_id)
            if udata:
                if mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]):
                    if self.mibands.keys()[dev_id] in connected_devices.keys():
                        mb2 = connected_devices[self.mibands.keys()[dev_id]]
                        if mb2db.release_device_user(mb2db.cnxn, mb2.addr, user_id):
                            print "MiBand Released from user"
                        else:
                            print "There was a problem releasing this MiBand"
                    else:
                        print("MiBand2 should be connected before releasing user data")
                else:
                    print("MiBand2 should be registered before releasing user data")
            else:
                print("*** user with id %s doesn't exist" % user_id)
        else:
            # TODO: If storage, release properly
            print("This operation is only available for DB mode")

    def do_connect(self, params):
        try:
           l = int(params)
        except ValueError:
           print "*** argument should be number"
           return
        except IndexError:
           print "*** connect takes at least one parameter"
           return
        dev_id = l
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if len(connected_devices.keys()) >= 5:
            print("Can't connect to more than 5 devices at the same time, disconnect some")
        else:
            if ((args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]))
                or args.mode == "json" and self.mibands.keys()[dev_id] in self.registered_devices):
                if self.mibands.keys()[dev_id] in connected_devices.keys():
                    print("That MiBand2 is already connected")
                else:
                    try:
                        addr = self.mibands.keys()[dev_id]
                        self.scd.tmp_devices[addr]["strikes"] = -9999
                        if not addr in self.devices_keys.keys():
                            self.devices_keys[addr] = random_key()
                        mb2 = MiBand2(addr, self.devices_keys[addr], initialize=False)
                        connected_devices[self.mibands.keys()[dev_id]] = mb2
                        if args.mode == "db":
                            alarms = mb2db.get_device_alarms(mb2db.cnxn, mb2.addr)
                            mb2db.update_battery(mb2db.cnxn, mb2.addr, mb2.battery_info['level'])
                        else:
                            if mb2.addr in self.devices_alarms.keys():
                                alarms = self.devices_alarms[mb2.addr]
                            else:
                                alarms = []
                        for a in alarms:
                            mb2.alarms += [MiBand2Alarm(a["hour"], a["minute"], enabled=a["enabled"], repetitionMask=a["repetition"])]
                        self.scd.tmp_devices[addr]["strikes"] = 0
                    except BTLEException as e:
                        print("There was a problem connecting to this MiBand2, try again later")
                        print e
            else:
                print("You have to register the MiBand2 before connecting to it")

    def do_disconnect(self, params):
        try:
           l = int(params)
        except ValueError:
           print "*** argument should be number"
           return
        except IndexError:
           print "*** disconnect takes at least one parameter"
           return
        dev_id = l
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if self.mibands.keys()[dev_id] in connected_devices.keys():
            try:
                mb2 = connected_devices[self.mibands.keys()[dev_id]]
                mb2.disconnect()
                del connected_devices[self.mibands.keys()[dev_id]]
                del mb2
                print ("MiBand2 disconnected!")
            except BTLEException as e:
                print("There was a problem disconnecting this MiBand2, try again later")
                print e
        else:
            print("That MiBand2 isn't connected!")

    def do_register(self, params):
        try:
           l = int(params)
        except ValueError:
           print "*** argument should be number"
           return
        except IndexError:
           print "*** register takes at least one parameter"
           return
        dev_id = l
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if ((args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]))
            or args.mode == "json" and self.mibands.keys()[dev_id] in self.registered_devices):
            print("That MiBand2 is already registered")
        else:
            mb2 = None
            try:
                addr = self.mibands.keys()[dev_id]
                self.scd.tmp_devices[addr]["strikes"] = -9999
                if not addr in self.devices_keys.keys():
                    self.devices_keys[addr] = random_key()
                mb2 = MiBand2(addr, self.devices_keys[addr], initialize=False)
                mb2.cleanAlarms()
                if args.mode == "db":
                    mb2db.delete_all_alarms(mb2db.cnxn, mb2.addr)
                    mb2db.register_device(mb2db.cnxn, mb2.addr)
                    mb2db.update_battery(mb2db.cnxn, mb2.addr, mb2.battery_info['level'])
                else:
                    self.registered_devices += [mb2.addr]
                # Device stays connected after initialize, but we don't want that
                mb2.disconnect()
                self.scd.tmp_devices[addr]["strikes"] = 0
            except BTLEException as e:
                print("There was a problem registering this MiBand2, try again later")
                print e
                mb2.disconnect

    def do_unregister(self, params):
        try:
           l = int(params)
        except ValueError:
           print "*** argument should be number"
           return
        except IndexError:
           print "*** unregister takes at least one parameter"
           return
        dev_id = l
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if ((args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]))
            or args.mode == "json" and self.mibands.keys()[dev_id] in self.registered_devices):
            if not self.mibands.keys()[dev_id] in connected_devices.values():
                try:
                    if args.mode == "db":
                        mb2db.unregister_device(mb2db.cnxn, self.mibands.keys()[dev_id])
                        mb2db.delete_all_alarms(mb2db.cnxn, self.mibands.keys()[dev_id])
                    else:
                        self.registered_devices.remove(self.mibands.keys()[dev_id])
                    print("MiBand2 unregistered!")
                except BTLEException:
                    print("There was a problem unregistering this MiBand2, try again later")
            else:
                print("Disconnect the miBand2 first!")
        else:
            print("That MiBand2 is not registered")


    def do_activity(self, params):
        try:
           l = int(params)
        except ValueError:
            print "*** argument should be number"
            return
        except IndexError:
           print "*** activity takes at least one parameter"
           return
        dev_id = l
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if ((args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]))
            or args.mode == "json" and self.mibands.keys()[dev_id] in self.registered_devices):
            if self.mibands.keys()[dev_id] in connected_devices.keys():
                q.put(self.mibands.keys()[dev_id])
                q.join()
            else:
                print("MiBand2 should be connected before fetching activity data")
        else:
            print("MiBand2 should be registered before fetching activity data")

    def do_alarms(self, params):
        l = params.split()
        try:
           dev_id = int(l[0])
           command = "list"
           if len(l) > 1:
               command = l[1]
        except ValueError:
           print "*** argument 1 should be number"
           return
        except IndexError:
           print "*** alarms takes at least one parameter"
           return
        if command not in ['list', 'queue', 'set', 'toggle', 'toggleday', 'delete', 'clear']:
           print "*** invalid alarm command, see help"
           return
        if dev_id >= len(self.mibands.keys()):
            print "*** device not in the device list"
            return
        if ((args.mode == "db" and mb2db.is_device_registered(mb2db.cnxn, self.mibands.keys()[dev_id]))
            or args.mode == "json" and self.mibands.keys()[dev_id] in self.registered_devices):
            if self.mibands.keys()[dev_id] in connected_devices.keys():
                mb2 = connected_devices[self.mibands.keys()[dev_id]]
                if args.mode == "db":
                    alarms = mb2db.get_device_alarms(mb2db.cnxn, self.mibands.keys()[dev_id])
                else:
                    if self.mibands.keys()[dev_id] in self.devices_alarms.keys():
                        alarms = self.devices_alarms[self.mibands.keys()[dev_id]]
                    else:
                        alarms = []
                if command == 'list':
                    if len(alarms) > 0:
                        for idx,a in enumerate(mb2.alarms):
                            print "[%s]" % idx + str(a)
                if command == 'clear':
                    if len(alarms) > 0:
                        mb2.cleanAlarms()
                        if args.mode == "db":
                            mb2db.delete_all_alarms(mb2db.cnxn, mb2.addr)
                        else:
                            self.devices_alarms[self.mibands.keys()[dev_id]] = []
                elif command == 'queue':
                    try:
                        hour, minute = map(lambda x: int(x), l[2].split(":"))
                        alarm_id = mb2.queueAlarm(hour, minute)
                        if args.mode == "db":
                            mb2db.set_alarm(mb2db.cnxn, mb2.addr, mb2.alarms[alarm_id], alarm_id)
                        else:
                            if len(alarms) > 0:
                                self.devices_alarms[self.mibands.keys()[dev_id]] += [{"enabled": True, "repetition": 128, "hour": hour, "minute": minute}]
                            else:
                                self.devices_alarms[self.mibands.keys()[dev_id]] = [{"enabled": True, "repetition": 128, "hour": hour, "minute": minute}]
                    except IndexError:
                        print "*** queue takes an hour parameter in format HH:MM"
                    except ValueError:
                        print "*** queue takes an hour parameter in format HH:MM"
                elif command == 'delete':
                    try:
                        alarm_id = int(l[2])
                        mb2.deleteAlarm(alarm_id)
                        if len(alarms) > 0:
                            if args.mode == "db":
                                mb2db.delete_alarm(mb2db.cnxn, mb2.addr, alarm_id)
                            else:
                                del self.devices_alarms[self.mibands.keys()[dev_id]][alarm_id]
                    except IndexError:
                        print "*** delete takes an alarm_id parameter"
                    except ValueError:
                        print "*** delete's alarm_id should be a number"
                elif command == 'toggle':
                    try:
                        alarm_id = int(l[2])
                        mb2.toggleAlarm(alarm_id)
                        if args.mode == "db":
                            mb2db.set_alarm(mb2db.cnxn, mb2.addr, mb2.alarms[alarm_id], alarm_id)
                        else:
                            self.devices_alarms[self.mibands.keys()[dev_id]][alarm_id]["enabled"] = mb2.alarms[alarm_id].enabled
                    except IndexError:
                        print "*** toggle takes an alarm_id parameter"
                    except ValueError:
                        print "*** toggle's alarm_id should be a number"
                elif command == 'toggleday':
                    try:
                        alarm_id = int(l[2])
                        day_id = int(l[3])
                        if day_id not in range(1,8):
                            print "*** day_id should be between 1 (Monday) and 7 (Sunday)"
                            return
                        else:
                            mb2.toggleAlarmDay(alarm_id, day_id-1)
                            if args.mode == "db":
                                mb2db.set_alarm(mb2db.cnxn, mb2.addr, mb2.alarms[alarm_id], alarm_id)
                            else:
                                self.devices_alarms[self.mibands.keys()[dev_id]][alarm_id]["repetition"] = mb2.alarms[alarm_id].repetitionMask

                    except IndexError:
                        print "*** toggleday takes an alarm_id parameter and a day_id parameter (1-7)"
                    except ValueError:
                        print "*** toggleday's alarm_id and day_id should be both numbers"
                elif command == "set":
                    try:
                        alarm_id = int(l[2])
                        hour, minute = map(lambda x: int(x), l[3].split(":"))
                        mb2.changeAlarmTime(alarm_id, hour, minute)
                        if args.mode == "db":
                            mb2db.set_alarm(mb2db.cnxn, mb2.addr, mb2.alarms[alarm_id], alarm_id)
                        else:
                            self.devices_alarms[self.mibands.keys()[dev_id]][alarm_id]["hour"] = mb2.alarms[alarm_id].hour
                            self.devices_alarms[self.mibands.keys()[dev_id]][alarm_id]["minute"] = mb2.alarms[alarm_id].minute
                    except IndexError:
                        print "*** set takes an alarm_id parameter and an hour parameter in format HH:MM"
                    except ValueError:
                        print "*** toggleday's alarm_id and hour (HH:MM) should be both numbers"
            else:
                print("MiBand2 should be connected before viewing/changing alarms")
        else:
            print("MiBand2 should be registered before viewing/changing alarms")

    def do_save(self, line):
        if args.mode == "json":
            print("Saving local data")
            save_local(self)
        else:
            print("This command is only available to local mode")


    def do_exit(self, line):
        print("Saving local data before exiting")
        save_local(self)
        return self.exit_safely()

    def do_EOF(self, line):
        print("Saving local data before exiting")
        save_local(self)
        return self.exit_safely()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MB2 Command Shell')
    parser.add_argument('-m', '--mode', default="json", choices=("json", "db"),
                    help='Storage mode')

    args = parser.parse_args()

    if args.mode == "db":
        if mb2db.cnxn:
            MiBand2CMD().cmdloop()
        else:
            print "Couldn't connect to DB, please check configuration and try again"
    elif args.mode == "json":
        mb2cmd = MiBand2CMD()
        mb2cmd.registered_devices = read_json(base_route + '/localdata/registered_devices.json', default="[]")
        mb2cmd.devices_last_sync = read_json(base_route + '/localdata/devices_last_sync.json')
        mb2cmd.devices_alarms = read_json(base_route + '/localdata/devices_alarms.json')
        mb2cmd.devices_keys = read_json(base_route + '/localdata/devices_keys.json')
        mb2cmd.cmdloop()
