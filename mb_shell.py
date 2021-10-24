#!/usr/bin/env python3

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
from queue import Queue, Empty
import configparser
import argparse
import os
import string
import random
import time
base_route = os.path.dirname(os.path.realpath(__file__))
sys.path.append(base_route + '/lib')
from mibandalarm import MiBandAlarm
from miband2 import MiBand2
from miband3 import MiBand3
import mibanddb as mbdb

ENV_CONFIG="development"
CONFIG_MODE="MB2"

config_route = base_route + "/configuration"
env_route = config_route + "/" + ENV_CONFIG

q = Queue()
max_connections = 2
# For automated download stablish a period in which we don't download data
# activity_fetch_cooldown = 6 * 60
connected_devices = {}
mibands = {}

try:
    env = configparser.ConfigParser()
    env.read_file(open(env_route + '/server.conf'))
except Exception as e:
    print(e)
    print(("unrecognised config mode [%s]" % ENV_CONFIG))
    sys.exit(-1)

config = configparser.ConfigParser()
config.read_file(open(config_route + '/mb_presets.conf'))

cnxn = {"server": env.get('DATABASE', "server"), "database": env.get('DATABASE', "database"),
        "username": env.get('DATABASE', "username"), "password": env.get('DATABASE', "password")}

cnxn_string = ('DRIVER={ODBC Driver 17 for SQL Server};Server='+cnxn["server"]+
                ';Database='+cnxn["database"]+';uid='+cnxn["username"]+
                ';pwd='+ cnxn["password"])

class MiBandScanDelegate(DefaultDelegate):
    def __init__(self, thresh):
        DefaultDelegate.__init__(self)
        self.tmp_devices = {}
        self.thresh = thresh

    def handleDiscovery(self, dev, isNewDev, isNewData):
        try:
            name = dev.getValue(9)
            serv = dev.getValueText(2)
            if serv == '0000fee0-0000-1000-8000-00805f9b34fb' and dev.addr and dev.rssi >= self.thresh:
                if name == 'MI Band 2':
                    self.tmp_devices[dev.addr] = {"device": dev, "name": name, "model": "mb2", "strikes": 0}
                elif name == 'Mi Band 3':
                    self.tmp_devices[dev.addr] = {"device": dev, "name": name, "model": "mb3", "strikes": 0}
        except Exception as e:
            print(e)
            print("ERROR")


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
    if args.mode == "local":
        with open(base_route + '/localdata/registered_devices.json', 'wb') as outfile:
            json.dump(cmd.registered_devices, outfile)
        with open(base_route + '/localdata/devices_last_sync.json', 'wb') as outfile:
            json.dump(cmd.devices_last_sync, outfile)
        with open(base_route + '/localdata/devices_alarms.json', 'wb') as outfile:
            json.dump(cmd.devices_alarms, outfile)
    with open(base_route + '/localdata/devices_keys.json', 'wb') as outfile:
        json.dump(cmd.devices_keys, outfile)

# Scanning process that checks for new devices and calculates reputation based on different parameters
# Note that a far away device won't disappear from the scanner devices list but will keep it's data static
# We check for nearby-ness and stilness of devices to recalculate reputation
# With very few reputation, device gets deleted, with enough reputation, activity gets fetched automatically
def scan_miband2(scanner,strikes,thresh):
    print("Scanning!")
    scanner.clear()
    scanner.start()
    t = threading.currentThread()
    while getattr(t, "do_scan", True):
        old_devices = copy.deepcopy(scanner.delegate.tmp_devices)
        scanner.process(1)
        for d in list(old_devices.keys()):
            if d in list(scanner.delegate.tmp_devices.keys()) and (d not in list(connected_devices.keys())):
                if ((old_devices[d]["device"].rssi >= scanner.delegate.tmp_devices[d]["device"].rssi)
                    or scanner.delegate.tmp_devices[d]["device"].rssi < thresh):
                    scanner.delegate.tmp_devices[d]["strikes"] += 1
                    if scanner.delegate.tmp_devices[d]["strikes"] >= strikes:
                        del scanner.delegate.tmp_devices[d]
    print("Stopped scanning...")
    scanner.stop()

# Ping thread to check if devices are still alive, this doesn't work well (causes interferences)
def ping_connected(sleeptime):
    print("Pinging connected devices...")
    t = threading.currentThread()
    while getattr(t, "do_ping", True):
        for d in list(connected_devices.keys()):
            try:
                connected_devices[d].char_battery.read()
            except Exception as e:
                print(e)
                connected_devices[d].force_disconnect()
                del connected_devices[d]
        time.sleep(sleeptime)
    print("Stopped pinging...")

def random_key(length=16):
    return ''.join(random.choice(string.ascii_uppercase + string.digits + string.ascii_lowercase) for _ in range(length))

def get_device_name(device):
    return device.getValueText(9)

def get_device_model(device):
    return DEVICE_MODELS[get_device_name(device)]

def worker(cmd):
    while True:
        item = q.get()
        do_fetch_activity(item, cmd)
        q.task_done()

def do_fetch_activity(item, cmd):
    print(("Fetching MiBand [%s] activity!" % item))
    if item not in list(connected_devices.keys()):
        try:
            if not item in list(cmd.devices_keys.keys()):
                cmd.devices_keys[item] = random_key()
            model = self.models[item]
            if model.upper() == "MB2":
                mb = MiBand2(addr, self.devices_keys[addr], initialize=False)
            elif model.upper() == "MB3":
                mb = MiBand3(addr, self.devices_keys[addr], initialize=False)
            connected_devices[item] = mb
        except BTLEException as e:
            print("There was a problem connecting this MiBand, try again later")
            print(e)
    try:
        if args.mode == "db":
            last_sync = mbdb.get_device_last_sync(cnxn_string, item)
        else:
            last_sync = None
            if item in list(cmd.devices_last_sync.keys()):
                last_sync = cmd.devices_last_sync[item]
        if last_sync != None:
            connected_devices[item].setLastSyncDate(last_sync)
        connected_devices[item].send_alert(b'\x03')
        connected_devices[item].fetch_activity_data()
        connected_devices[item].send_alert(b'\x03')
        if len(connected_devices[item].getActivityDataBuffer()) > 0:
            print("Saving Data to DB...")
            if args.mode == "db":
                mbdb.write_activity_data(cnxn_string, connected_devices[item])
            else:
                connected_devices[item].store_activity_data_file(base_route + '/localdata/activity_log/')
        print(("Finished fetching MiBand [%s] activity!" % item))
    except BTLEException as e:
        print("There was a problem retrieving this MiBand's activity, try again later")
        print(e)

class MiBandCMD(cmd.Cmd):
    """Command Processor for intercating with many MiBands at a time"""
    def __init__(self):
        cmd.Cmd.__init__(self)
        threshold = -70
        strikes = 5
        pingtimer = 1
        self.sc = Scanner()
        self.scd = MiBandScanDelegate(threshold)
        self.sc.withDelegate(self.scd)

        self.mibands = []

        self.scan_thread = threading.Thread(target=scan_miband2, args=(self.sc,strikes,threshold))
        self.scan_thread.start()

        #self.ping_thread = threading.Thread(target=ping_connected, args=(pingtimer,))
        #self.ping_thread.start()

        for i in range(max_connections):
             t = threading.Thread(target=worker, args=(self,))
             t.daemon = True
             t.start()

        self.prompt =  'MBS => '

    def exit_safely(self):
        self.scan_thread.do_scan = False
        #self.ping_thread.do_ping = False
        self.scan_thread.join()
        print(("Disconnecting from %s devices" % len(list(connected_devices.values()))))
        for con in list(connected_devices.values()):
            con.disconnect()
        return True

    def do_devices(self, line):
        tmp_mibands = copy.deepcopy(self.scd.tmp_devices)
        self.mibands = {k: v["device"] for k, v in list(tmp_mibands.items())}
        self.models = {k: v["model"] for k, v in list(tmp_mibands.items())}
        tmp_strikes = {k: v["strikes"] for k, v in list(tmp_mibands.items())}
        for idx,mb in enumerate(self.mibands.keys()):
            name = "Someone"
            uid = 0
            udata = None
            if args.mode == "db":
                devid = mbdb.get_device_id(cnxn_string, mb.upper())
                devuser = mbdb.get_device_user(cnxn_string, devid)
                if devuser != -1:
                    udata = mbdb.get_user_data(cnxn_string,devuser)
                else:
                    udata = None
            else:
                # TODO: User Data on local storage???
                pass
            if udata:
                name = udata["alias"]
                uid = udata["id"]
            model = self.models[list(self.mibands.keys())[idx]].upper()
            str = "[%s]%10s's %s <U:%05d> (%s) %sdB S:%s " % (idx, name, model, uid, mb, self.mibands[list(self.mibands.keys())[idx]].rssi, "X"*tmp_strikes[list(self.mibands.keys())[idx]])
            if (args.mode == "db" and mbdb.is_device_registered(cnxn_string, mb)) or (args.mode == "json" and mb in self.registered_devices):
                str += "[R]"
            if mb in connected_devices:
                mb_dev = connected_devices[mb]
                if args.mode == "db":
                    mbdb.update_battery(cnxn_string, mb_dev.addr, mb_dev.battery_info['level'])
                str += "[C] [B:{0:03d}%]".format(mb.battery_info["level"])
            print(str)

    def do_reboot(self, params):
        try:
           dev_id = int(params)
        except ValueError:
           print("*** arguments should be numbers")
           return
        except IndexError:
           print("*** alert takes at least one parameter")
           return
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if ((args.mode == "db" and mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]))
            or (args.mode == "json" and list(self.mibands.keys())[dev_id] in self.registered_devices)):
            if list(self.mibands.keys())[dev_id] in list(connected_devices.keys()):
                try:
                    mb = connected_devices[list(self.mibands.keys())[dev_id]]
                    mb.reboot()
                except BTLEException:
                    print("There was a problem rebooting this MiBand, try again later")
            else:
                print("That MiBand is not connected!")
        else:
            print("That MiBand is not registered")

    def do_alert(self, params):
        l = params.split()
        if len(l)!=2:
           print("*** invalid number of arguments")
           return
        try:
           l = [int(i) for i in l]
        except ValueError:
           print("*** arguments should be numbers")
           return
        except IndexError:
           print("*** alert takes at least one parameter")
           return
        dev_id = int(l[0])
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        alert_int = int(l[1])
        if ((args.mode == "db" and mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]))
            or args.mode == "json" and list(self.mibands.keys())[dev_id] in self.registered_devices):
            if list(self.mibands.keys())[dev_id] in list(connected_devices.keys()):
                try:
                    mb = connected_devices[list(self.mibands.keys())[dev_id]]
                    data = struct.pack('B', alert_int)
                    mb.send_alert(data)
                    print(("Sending Notification: " + binascii.hexlify(data)))
                except BTLEException:
                    print("There was a problem alerting this MiBand, try again later")
            else:
                print("That MiBand is not connected!")
        else:
            print("That MiBand is not registered")

    def do_configure(self, params):
        l = params.split()
        try:
           dev_id = int(l[0])
           command = ""
           if len(l) > 1:
               command = l[1]
        except ValueError:
           print("*** argument 1 should be number")
           return
        except IndexError:
           print("*** configure takes at least one parameter")
           return
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if command == "":
            print(("Using default configuration preset [%s]" % CONFIG_MODE))
            command = CONFIG_MODE
        if not config.has_section(command):
           print(("*** invalid configuration preset '%s'" % command))
           return
        self.configure_miband(dev_id, command)

    def configure_miband(self, dev_id, preset):
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if ((args.mode == "db" and mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]))
            or args.mode == "json" and list(self.mibands.keys())[dev_id] in self.registered_devices):
            if list(self.mibands.keys())[dev_id] in list(connected_devices.keys()):
                try:
                    mb = connected_devices[list(self.mibands.keys())[dev_id]]
                    print(("Configuring MiBand to [%s] presets" % preset))
                    if config.has_option(preset, "MonitorHRSleep"):
                        mb.monitorHeartRateSleep(config.getint(preset, "MonitorHRSleep"))
                    if config.has_option(preset, "MonitorHRInterval"):
                        mb.setMonitorHeartRateInterval(config.getint(preset, "MonitorHRInterval"))
                    if config.has_option(preset, "DisplayTimeFormat"):
                        mb.setDisplayTimeFormat(config.get(preset, "DisplayTimeFormat"))
                    if config.has_option(preset, "DisplayTimeHours"):
                        mb.setDisplayTimeHours(config.getint(preset, "DisplayTimeHours"))
                    if config.has_option(preset, "DistanceUnit"):
                        mb.setDistanceUnit(config.get(preset, "DistanceUnit"))
                    if config.has_option(preset, "LiftWristActivate"):
                        mb.setLiftWristToActivate(config.getint(preset, "LiftWristActivate"))
                    if config.has_option(preset, "RotateWristSwitch"):
                        mb.setRotateWristToSwitchInfo(config.getint(preset, "RotateWristSwitch"))
                    if config.has_option(preset, "DisplayItems"):
                        disp = [x.strip() for x in config.get(preset, 'DisplayItems').split(',')]
                        steps = True if 'steps' in disp else False
                        distance = True if 'distance' in disp else False
                        calories = True if 'calories' in disp else False
                        heartrate = True if 'heartrate' in disp else False
                        battery = True if 'battery' in disp else False
                        mb.setDisplayItems(steps=steps, distance=distance, calories=calories, heartrate=heartrate, battery=battery)
                    if config.has_option(preset, "DoNotDisturb"):
                        enableLift = config.getint(preset, "DoNotDisturbLift") if config.has_option(preset, "DoNotDisturbLift") else 1
                        mb.setDoNotDisturb(config.get(preset, "DoNotDisturb"), enableLift=enableLift)
                    if config.has_option(preset, "InactivityWarnings"):
                        start = config.getint(preset, "InactivityWarningsStart") if config.has_option(preset, "InactivityWarningsStart") else 8
                        end = config.getint(preset, "InactivityWarningsEnd") if config.has_option(preset, "InactivityWarningsEnd") else 19
                        threshold = config.getint(preset, "InactivityWarningsThresholdHours") if config.has_option(preset, "InactivityWarningsThresholdHours") else 1
                        mb.setInactivityWarnings(config.getint(preset, "InactivityWarnings"), threshold=threshold*60, start=(start, 0), end=(end, 0))
                    if config.has_option(preset, "DisplayCaller"):
                        mb.setDisplayCaller(config.getint(preset, "DisplayCaller"))

                except BTLEException as e:
                    print("There was a problem configuring this MiBand, try again later")
                    print(e)
            else:
                print("That MiBand is not connected, please connect it before configuring.")
        else:
            print("That MiBand is not registered, please register it before configuring.")

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
           print("*** argument should be number")
           return
        except IndexError:
           print("*** setuser takes at least one parameter")
           return
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if args.mode == "db":
            udata = mbdb.get_user_data(cnxn_string, user_id)
        if udata or args.mode == "json":
            if ((args.mode == "db" and mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]))
                or args.mode == "json" and list(self.mibands.keys())[dev_id] in self.registered_devices):
                if list(self.mibands.keys())[dev_id] in list(connected_devices.keys()):
                    mb = connected_devices[list(self.mibands.keys())[dev_id]]
                    if args.mode == "db":
                        if mbdb.set_device_user(cnxn_string, mb.addr, user_id, position[0]):
                            mb.setUserInfo(udata["alias"], udata["sex"], udata["height"], udata["weight"], udata["birth"])
                    else:
                        mb.setUserInfo(user_alias, user_gender, user_height, user_weight, (user_bd_year, user_bd_month, user_bd_day))
                    mb.setWearLocation(position[1])
                else:
                    print("MiBand should be connected before setting user data")
            else:
                print("MiBand should be registered before setting user data")
        else:
            print(("*** user with id %s doesn't exist" % user_id))

    def do_reluser(self, params):
        if args.mode == "db":
            try:
               l = params.split()
               dev_id = int(l[0])
               user_id = int(l[1])
            except ValueError:
               print("*** argument should be number")
               return
            except IndexError:
               print("*** reluser takes at least one parameter")
               return
            if dev_id >= len(list(self.mibands.keys())):
                print("*** device not in the device list")
                return
            udata = mbdb.get_user_data(cnxn_string, user_id)
            if udata:
                if mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]):
                    if list(self.mibands.keys())[dev_id] in list(connected_devices.keys()):
                        mb = connected_devices[list(self.mibands.keys())[dev_id]]
                        if mbdb.release_device_user(cnxn_string, mb.addr, user_id):
                            print("MiBand Released from user")
                        else:
                            print("There was a problem releasing this MiBand")
                    else:
                        print("MiBand should be connected before releasing user data")
                else:
                    print("MiBand should be registered before releasing user data")
            else:
                print(("*** user with id %s doesn't exist" % user_id))
        else:
            # TODO: If storage, release properly
            print("This operation is only available for DB mode")

    def do_connect(self, params):
        try:
           l = int(params)
        except ValueError:
           print("*** argument should be number")
           return
        except IndexError:
           print("*** connect takes at least one parameter")
           return
        dev_id = l
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if len(list(connected_devices.keys())) >= 5:
            print("Can't connect to more than 5 devices at the same time, disconnect some")
        else:
            if ((args.mode == "db" and mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]))
                or args.mode == "json" and list(self.mibands.keys())[dev_id] in self.registered_devices):
                if list(self.mibands.keys())[dev_id] in list(connected_devices.keys()):
                    print("That MiBand is already connected")
                else:
                    try:
                        addr = list(self.mibands.keys())[dev_id]
                        model = self.models[addr]
                        if not addr in list(self.devices_keys.keys()):
                            self.devices_keys[addr] = random_key()
                        if model.upper() == "MB2":
                            mb = MiBand2(addr, self.devices_keys[addr], initialize=False)
                        elif model.upper() == "MB3":
                            mb = MiBand3(addr, self.devices_keys[addr], initialize=False)
                        connected_devices[list(self.mibands.keys())[dev_id]] = mb
                        if args.mode == "db":
                            alarms = mbdb.get_device_alarms(cnxn_string, mb.addr)
                            mbdb.update_battery(cnxn_string, mb.addr, mb.battery_info['level'])
                        else:
                            if mb.addr in list(self.devices_alarms.keys()):
                                alarms = self.devices_alarms[mb.addr]
                            else:
                                alarms = []
                        for a in alarms:
                            mb.alarms += [MiBandAlarm(a["hour"], a["minute"], enabled=a["enabled"], repetitionMask=a["repetition"])]
                    except BTLEException as e:
                        print("There was a problem connecting to this MiBand, try again later")
                        print(e)
            else:
                print("You have to register the MiBand before connecting to it")

    def do_disconnect(self, params):
        try:
           l = int(params)
        except ValueError:
           print("*** argument should be number")
           return
        except IndexError:
           print("*** disconnect takes at least one parameter")
           return
        dev_id = l
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if list(self.mibands.keys())[dev_id] in list(connected_devices.keys()):
            try:
                mb = connected_devices[list(self.mibands.keys())[dev_id]]
                mb.disconnect()
                del connected_devices[list(self.mibands.keys())[dev_id]]
                del mb
                print("MiBand disconnected!")
            except BTLEException as e:
                print("There was a problem disconnecting this MiBand, try again later")
                print(e)
        else:
            print("That MiBand isn't connected!")

    def do_register(self, params):
        try:
           l = int(params)
        except ValueError:
           print("*** argument should be number")
           return
        except IndexError:
           print("*** register takes at least one parameter")
           return
        dev_id = l
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if ((args.mode == "db" and mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]))
            or args.mode == "json" and list(self.mibands.keys())[dev_id] in self.registered_devices):
            print("That MiBand is already registered")
        else:
            mb = None
            try:
                addr = list(self.mibands.keys())[dev_id]
                model = self.models[addr]
                if not addr in list(self.devices_keys.keys()):
                    self.devices_keys[addr] = random_key()
                if model.upper() == "MB2":
                    mb = MiBand2(addr, self.devices_keys[addr], initialize=False)
                elif model.upper() == "MB3":
                    mb = MiBand3(addr, self.devices_keys[addr], initialize=False)
                mb.cleanAlarms()
                if args.mode == "db":
                    dev_id = mbdb.get_device_id(cnxn_string, mb.addr)
                    mbdb.delete_all_alarms(cnxn_string, dev_id)
                    mbdb.register_device(cnxn_string, mb.addr)
                    mbdb.update_battery(cnxn_string, mb.addr, mb.battery_info['level'])
                else:
                    self.registered_devices += [mb.addr]
                # Device stays connected after initialize, but we don't want that
                mb.disconnect()
            except BTLEException as e:
                print("There was a problem registering this MiBand, try again later")
                print(e)
            except KeyError as e:
                print("Device was kicked out")
                print(e)

    def do_unregister(self, params):
        try:
           l = int(params)
        except ValueError:
           print("*** argument should be number")
           return
        except IndexError:
           print("*** unregister takes at least one parameter")
           return
        dev_id = l
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if ((args.mode == "db" and mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]))
            or args.mode == "json" and list(self.mibands.keys())[dev_id] in self.registered_devices):
            if not list(self.mibands.keys())[dev_id] in list(connected_devices.values()):
                try:
                    if args.mode == "db":
                        mbdb.unregister_device(cnxn_string, list(self.mibands.keys())[dev_id])
                        mbdb.delete_all_alarms(cnxn_string, list(self.mibands.keys())[dev_id])
                    else:
                        self.registered_devices.remove(list(self.mibands.keys())[dev_id])
                        del self.devices_keys[list(self.mibands.keys())[dev_id]]
                    print("MiBand unregistered!")
                except BTLEException:
                    print("There was a problem unregistering this MiBand, try again later")
            else:
                print("Disconnect the miBand2 first!")
        else:
            print("That MiBand is not registered")


    def do_activity(self, params):
        try:
           l = int(params)
        except ValueError:
            print("*** argument should be number")
            return
        except IndexError:
           print("*** activity takes at least one parameter")
           return
        dev_id = l
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if ((args.mode == "db" and mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]))
            or args.mode == "json" and list(self.mibands.keys())[dev_id] in self.registered_devices):
            if list(self.mibands.keys())[dev_id] in list(connected_devices.keys()):
                q.put(list(self.mibands.keys())[dev_id])
                q.join()
            else:
                print("MiBand should be connected before fetching activity data")
        else:
            print("MiBand should be registered before fetching activity data")

    def do_alarms(self, params):
        l = params.split()
        try:
           dev_id = int(l[0])
           command = "list"
           if len(l) > 1:
               command = l[1]
        except ValueError:
           print("*** argument 1 should be number")
           return
        except IndexError:
           print("*** alarms takes at least one parameter")
           return
        if command not in ['list', 'queue', 'set', 'toggle', 'toggleday', 'delete', 'clear']:
           print("*** invalid alarm command, see help")
           return
        if dev_id >= len(list(self.mibands.keys())):
            print("*** device not in the device list")
            return
        if ((args.mode == "db" and mbdb.is_device_registered(cnxn_string, list(self.mibands.keys())[dev_id]))
            or args.mode == "json" and list(self.mibands.keys())[dev_id] in self.registered_devices):
            if list(self.mibands.keys())[dev_id] in list(connected_devices.keys()):
                mb = connected_devices[list(self.mibands.keys())[dev_id]]
                if args.mode == "db":
                    alarms = mbdb.get_device_alarms(cnxn_string, list(self.mibands.keys())[dev_id])
                else:
                    if list(self.mibands.keys())[dev_id] in list(self.devices_alarms.keys()):
                        alarms = self.devices_alarms[list(self.mibands.keys())[dev_id]]
                    else:
                        alarms = []
                if command == 'list':
                    if len(alarms) > 0:
                        for idx,a in enumerate(mb.alarms):
                            print(("[%s]" % idx + str(a)))
                if command == 'clear':
                    if len(alarms) > 0:
                        mb.cleanAlarms()
                        if args.mode == "db":
                            mbdb.delete_all_alarms(cnxn_string, mb.addr)
                        else:
                            self.devices_alarms[list(self.mibands.keys())[dev_id]] = []
                elif command == 'queue':
                    try:
                        hour, minute = [int(x) for x in l[2].split(":")]
                        alarm_id = mb.queueAlarm(hour, minute)
                        if args.mode == "db":
                            mbdb.set_alarm(cnxn_string, mb.addr, mb.alarms[alarm_id], alarm_id)
                        else:
                            if len(alarms) > 0:
                                self.devices_alarms[list(self.mibands.keys())[dev_id]] += [{"enabled": True, "repetition": 128, "hour": hour, "minute": minute}]
                            else:
                                self.devices_alarms[list(self.mibands.keys())[dev_id]] = [{"enabled": True, "repetition": 128, "hour": hour, "minute": minute}]
                    except IndexError:
                        print("*** queue takes an hour parameter in format HH:MM")
                    except ValueError:
                        print("*** queue takes an hour parameter in format HH:MM")
                elif command == 'delete':
                    try:
                        alarm_id = int(l[2])
                        mb.deleteAlarm(alarm_id)
                        if len(alarms) > 0:
                            if args.mode == "db":
                                mbdb.delete_alarm(cnxn_string, mb.addr, alarm_id)
                            else:
                                del self.devices_alarms[list(self.mibands.keys())[dev_id]][alarm_id]
                    except IndexError:
                        print("*** delete takes an alarm_id parameter")
                    except ValueError:
                        print("*** delete's alarm_id should be a number")
                elif command == 'toggle':
                    try:
                        alarm_id = int(l[2])
                        mb.toggleAlarm(alarm_id)
                        if args.mode == "db":
                            mbdb.set_alarm(cnxn_string, mb.addr, mb.alarms[alarm_id], alarm_id)
                        else:
                            self.devices_alarms[list(self.mibands.keys())[dev_id]][alarm_id]["enabled"] = mb.alarms[alarm_id].enabled
                    except IndexError:
                        print("*** toggle takes an alarm_id parameter")
                    except ValueError:
                        print("*** toggle's alarm_id should be a number")
                elif command == 'toggleday':
                    try:
                        alarm_id = int(l[2])
                        day_id = int(l[3])
                        if day_id not in list(range(1,8)):
                            print("*** day_id should be between 1 (Monday) and 7 (Sunday)")
                            return
                        else:
                            mb.toggleAlarmDay(alarm_id, day_id-1)
                            if args.mode == "db":
                                mbdb.set_alarm(cnxn_string, mb.addr, mb.alarms[alarm_id], alarm_id)
                            else:
                                self.devices_alarms[list(self.mibands.keys())[dev_id]][alarm_id]["repetition"] = mb.alarms[alarm_id].repetitionMask

                    except IndexError:
                        print("*** toggleday takes an alarm_id parameter and a day_id parameter (1-7)")
                    except ValueError:
                        print("*** toggleday's alarm_id and day_id should be both numbers")
                elif command == "set":
                    try:
                        alarm_id = int(l[2])
                        hour, minute = [int(x) for x in l[3].split(":")]
                        mb.changeAlarmTime(alarm_id, hour, minute)
                        if args.mode == "db":
                            mbdb.set_alarm(cnxn_string, mb.addr, mb.alarms[alarm_id], alarm_id)
                        else:
                            self.devices_alarms[list(self.mibands.keys())[dev_id]][alarm_id]["hour"] = mb.alarms[alarm_id].hour
                            self.devices_alarms[list(self.mibands.keys())[dev_id]][alarm_id]["minute"] = mb.alarms[alarm_id].minute
                    except IndexError:
                        print("*** set takes an alarm_id parameter and an hour parameter in format HH:MM")
                    except ValueError:
                        print("*** toggleday's alarm_id and hour (HH:MM) should be both numbers")
            else:
                print("MiBand should be connected before viewing/changing alarms")
        else:
            print("MiBand should be registered before viewing/changing alarms")

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
    mb2cmd = MiBandCMD()
    if args.mode == "db":
        try:
            pyodbc.connect(cnxn_string, timeout=3)
        except pyodbc.OperationalError as e:
            print((str(e[1])))
            sys.exit(-1)
    elif args.mode == "json":
        mb2cmd.registered_devices = read_json(base_route + '/localdata/registered_devices.json', default="[]")
        mb2cmd.devices_last_sync = read_json(base_route + '/localdata/devices_last_sync.json')
        mb2cmd.devices_alarms = read_json(base_route + '/localdata/devices_alarms.json')

    mb2cmd.devices_keys = read_json(base_route + '/localdata/devices_keys.json')
    mb2cmd.cmdloop()
