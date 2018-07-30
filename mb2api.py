#!/usr/bin/env python

from flask import Flask, g, request, flash, url_for, redirect, render_template, abort, jsonify
import os
import logging
import cmd
import json
import threading
import binascii
from bluepy.btle import Scanner, DefaultDelegate, BTLEException
import re
import time
import sys
import copy
import struct
import jwt
import random
import string
import pyodbc
import datetime
import argparse
import Queue
import ConfigParser
from flask import Flask
base_route = os.path.dirname(os.path.realpath(__file__))
sys.path.append(base_route + '/lib')
from miband2 import MiBand2, MiBand2Alarm
import miband2db as mb2db

class SetQueue(Queue.Queue):
    def _init(self, maxsize):
        self.queue = set()
    def _put(self, item):
        self.queue.add(item)
    def _get(self):
        return self.queue.pop()

app = Flask(__name__)

parser = argparse.ArgumentParser(description='MiBand2 Server and API')
parser.add_argument('-e', '--env', default='development',
                    help='determine the enviroment config for the server')

args = parser.parse_args()

ENV_CONFIG = args.env
CONFIG_MODE="GERIATIC"
VERSION_STRING = "0.11"

DEFAULT_KEY = b'\x30\x31\x32\x33\x34\x35\x36\x37\x38\x39\x40\x41\x42\x43\x44\x45'

max_connections = 5
q = SetQueue()
# For automated download stablish a period in which we don't download data
# activity_fetch_cooldown = 6 * 60
connected_devices = {}
tmp_mibands = {}
mibands = {}
reputation = {}
rssithreshold = -75
autofetch_cooldown = 6*60*60 # 6 hours in seconds
pingtimer = 3

config_route = base_route + "/configuration"
env_route = config_route + "/" + ENV_CONFIG

config_presets = ConfigParser.ConfigParser()
config_presets.readfp(open(config_route + '/mb2_presets.conf'))
devices_keys = None

try:
    env = ConfigParser.ConfigParser()
    env.readfp(open(env_route + '/server.conf'))
except Exception as e:
    print e
    print "unrecognised config mode [%s]" % ENV_CONFIG
    sys.exit(-1)

cnxn = {"server": env.get('DATABASE', "server"), "database": env.get('DATABASE', "database"),
        "username": env.get('DATABASE', "username"), "password": env.get('DATABASE', "password")}

cnxn_string = ('DRIVER={ODBC Driver 17 for SQL Server};Server='+cnxn["server"]+
                ';Database='+cnxn["database"]+';uid='+cnxn["username"]+
                ';pwd='+ cnxn["password"])

try:
    pyodbc.connect(cnxn_string, timeout=3)
except pyodbc.OperationalError as e:
    print str(e[1])
    sys.exit(-1)


class MiBand2ScanDelegate(DefaultDelegate):
    def __init__(self, threshold):
        DefaultDelegate.__init__(self)
        self.threshold = threshold

    def handleDiscovery(self, dev, isNewDev, isNewData):
        try:
            name = dev.getValueText(9)
            serv = dev.getValueText(2)
            if name == 'MI Band 2' and serv == 'e0fe' and dev.addr and dev.rssi > self.threshold:
                if dev.addr.upper() not in tmp_mibands.keys():
                    tmp_mibands[dev.addr.upper()] = dev
                    reputation[dev.addr.upper()] = 50
        except:
            print "ERROR"

def random_key(length=16):
    return ''.join(random.choice(string.ascii_uppercase + string.digits + string.ascii_lowercase) for _ in range(length))

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

def save_keys(keys):
    with open(base_route + '/localdata/devices_keys.json', 'wb') as outfile:
        json.dump(keys, outfile)

def encode_auth_token(user_data):
    try:
        payload = {
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
            'iat': datetime.datetime.utcnow(),
            'sub': {"user_id": user_data.Id, "user_name": user_data.UserName,
                    "email": user_data.Email}
        }
        return jwt.encode(
            payload,
            env.get('SERVER', 'secret_key'),
            algorithm='HS256'
        )
    except Exception as e:
        return e

def decode_auth_token(auth_token):
    try:
        payload = jwt.decode(auth_token, env.get('SERVER', 'secret_key'))
        return {"success": True, "data":payload['sub']}
    except jwt.ExpiredSignatureError:
        return {"success": False, "data": "Token Expired"}
    except jwt.InvalidTokenError:
        return {"success": False, "data": "Token Error"}

def scan_miband2(scanner,scanthresh):
    print("Scanning!")
    scanner.clear()
    scanner.start()
    t = threading.currentThread()
    while getattr(t, "do_scan", True):
        old_mibands = copy.deepcopy(tmp_mibands)
        scanner.process(2)
        for d in old_mibands.keys():
            if d in connected_devices.keys():
                reputation[d.upper()] = 50
            if d in tmp_mibands.keys() and (d not in connected_devices.keys()):
                new_signal = tmp_mibands[d.upper()].rssi
                signal_diff = (old_mibands[d.upper()].rssi - tmp_mibands[d.upper()].rssi)
                proximity_factor = 1
                if new_signal < scanthresh:
                    # If the device is away positive reputation increases slowly
                    proximity_factor = 0.5
                elif new_signal > (scanthresh + 2*(scanthresh/3)):
                    # Pretty close
                    proximity_factor = 1.5
                elif new_signal > (scanthresh + (scanthresh/3)):
                    # Mid range
                    proximity_factor = 1.25
                elif new_signal > (scanthresh):
                    # Away but ok
                    proximity_factor = 1

                if signal_diff == 0:
                    # If stagnant, reputation decreases drastically
                    reputation[d.upper()] -= 10
                elif signal_diff in range(-5, 6):
                    # If there is little variation, reputation increases
                    reputation[d.upper()] += 10*proximity_factor
                elif signal_diff < -5:
                    # If there is a VERY big negative variation, reputation decreases drastically
                    reputation[d.upper()] -= 10
                elif signal_diff > 5:
                    # If there is a big positive variation, reputation increases a bit
                    reputation[d.upper()] += 5*proximity_factor

                if reputation[d.upper()] >= 100:
                    reputation[d.upper()] = 100
                if reputation[d.upper()] <= 0:
                    reputation[d.upper()] = 0

                if reputation[d.upper()] >= 90:
                    if (mb2db.is_device_registered(cnxn_string, d.upper())):
                        last_sync = mb2db.get_device_last_sync(cnxn_string, d.upper())
                        timediff = None
                        if last_sync != None:
                            timediff = (datetime.datetime.now() - last_sync)
                        if timediff == None or timediff.total_seconds() > autofetch_cooldown:
                            q.put((d.upper(),True,))
                if reputation[d.upper()] <= 10:
                    del tmp_mibands[d.upper()]
    q.join()
    print("Stopped scanning...")
    scanner.stop()

def ping_connected(sleeptime):
    print("Pinging connected devices...")
    t = threading.currentThread()
    while getattr(t, "do_ping", True):
        for d in connected_devices.keys():
            try:
                connected_devices[d.upper()].char_battery.read()
            except Exception as e:
                print e
                if d in connected_devices.keys():
                    connected_devices[d.upper()].force_disconnect()
                    del connected_devices[d.upper()]
        time.sleep(sleeptime)
    print("Stopped pinging...")

def worker():
    while True:
        item, silent_fetch = q.get()
        do_fetch_activity(item, silent_fetch)
        q.task_done()

def do_fetch_activity(item, silent_fetch):
    print "Fetching MiBand2 [%s] activity!" % item
    disconnect_after = False
    if item not in connected_devices.keys():
        try:
            disconnect_after = True
            if not item in devices_keys.keys():
                key = DEFAULT_KEY
            else:
                key = devices_keys[item.upper()]
            mb2 = MiBand2(item, key, initialize=False)
            connected_devices[item] = mb2
        except BTLEException as e:
            print("There was a problem connecting this MiBand2, try again later")
            print e
            if item in connected_devices.keys():
                connected_devices[item].force_disconnect()
                del connected_devices[item]
    if item in connected_devices.keys():
        try:
            last_sync = mb2db.get_device_last_sync(cnxn_string, item)
            if last_sync != None:
                connected_devices[item].setLastSyncDate(last_sync)
            if not silent_fetch:
                connected_devices[item].send_alert(b'\x03')
            connected_devices[item].fetch_activity_data()
            if not silent_fetch:
                connected_devices[item].send_alert(b'\x03')
            if len(connected_devices[item].getActivityDataBuffer()) > 0:
                print "Saving Data to DB..."
                mb2db.write_activity_data(cnxn_string, connected_devices[item])
            print "Finished fetching MiBand2 [%s] activity!" % item
            if disconnect_after:
                connected_devices[item].disconnect()
                del connected_devices[item]
        except BTLEException as e:
            print("There was a problem retrieving this MiBand2's activity, try again later")
            print e
            if item in connected_devices.keys():
                connected_devices[item].force_disconnect()
                del connected_devices[item]


@app.before_request
def before_request():
    if request.endpoint != 'api_authenticate' and request.endpoint != 'index':
        token = request.form.get('token') or request.args.get('token') or request.headers.get('token')
        if not token:
            return json.dumps({"success": False, "data": "Please provide an auth token"}), 403
        else:
            data = decode_auth_token(token)
            if not data["success"]:
                return json.dumps(data), 403
            else:
                request.token = token
                request.data = data

@app.route('/', methods=["GET"])
def index():
    if request.method == "GET":
        return json.dumps({"env": ENV_CONFIG, "api_version": "v"+VERSION_STRING, "app": "MiBand2 Server API"})

@app.route('/', methods=["DELETE"])
def reboot():
    if request.method == "DELETE":
        if request.form["reboot_key"] == env.get('SERVER', "reboot_key"):
            print("Rebooting API Server...")
            scan_thread.do_scan = False
            #ping_thread.do_ping = False
            for d in connected_devices.values():
                d.disconnect()
            os.system('reboot')
        else:
            abort(403)

@app.route('/authenticate/', methods=["POST"])
def api_authenticate():
    if request.method == "POST":
        udata = mb2db.get_aspuser_by_email(cnxn_string, request.form.get('email'))
        if udata:
            valid_pass = mb2db.compare_password(cnxn_string, udata.Id, request.form.get('pwd_hash'))
            if not valid_pass:
                abort(403)
            else:
                token = encode_auth_token(udata)
                return json.dumps({"token": token, "aspuser_id": udata.Id}), 200
        else:
            abort(404)
    abort(405)


@app.route('/devices/', methods= ["GET", "POST"])
def devices():
    if request.method == "GET":
        dev_list = []
        mibands = copy.deepcopy(tmp_mibands)
        for idx,mb in enumerate(mibands.keys()):
            dev_id = mb2db.get_device_id(cnxn_string, mb)
            dev_user_id = mb2db.get_device_user(cnxn_string, dev_id)
            dev_user = mb2db.get_user_data(cnxn_string, dev_user_id)
            device = mb2db.get_device_by_id(cnxn_string, dev_id)
            battery = -1
            if device:
                battery = device.bateria
            username = (dev_user.nombre + " " + dev_user.apellidos) if dev_user else "Unregistered"
            dev_dict = {"address":mb, "signal": mibands[mibands.keys()[idx]].rssi,
                        "registered": False, "connected": False, "dev_id": dev_id,
                        "user_name": username, "battery": battery, "reputation": reputation[mibands[mibands.keys()[idx]].addr.upper()]}
            if mb2db.is_device_registered(cnxn_string, mb):
                dev_dict["registered"] = True
            if mb in connected_devices.keys():
                dev_dict["connected"] = True
            dev_list += [dev_dict]
        return json.dumps(dev_list)
    elif request.method == "POST":
        addr = request.form["address"].upper()
        if mb2db.is_device_registered(cnxn_string, addr):
            abort(403)
        else:
            try:
                reputation[addr] = 100
                if not addr in devices_keys.keys():
                    devices_keys[addr] = random_key()
                mb2 = MiBand2(addr, devices_keys[addr], initialize=False)
                devices_keys[addr] = mb2.key
                connected_devices[addr] = mb2
                save_keys(devices_keys)
                mb2.cleanAlarms()
                dev_id = mb2db.register_device(cnxn_string, mb2.addr)
                mb2db.delete_all_alarms(cnxn_string, dev_id)
                mb2db.update_battery(cnxn_string, mb2.addr, mb2.battery_info['level'])
                # Device stays connected after initialize, but we don't want that
                del connected_devices[addr]
                mb2.disconnect()
                reputation[addr] = 50
                return json.dumps({"dev_id": dev_id, "registered": True})
            except BTLEException as e:
                print("There was a problem registering this MiBand2, try again later")
                print e
                if addr in connected_devices.keys():
                    connected_devices[addr].force_disconnect()
                    del connected_devices[addr]
                abort(500)
            except BTLEException.DISCONNECTED as d:
                print("Device disconnected, removing from connected devices")
                print e
                if addr in connected_devices.keys():
                    connected_devices[addr].force_disconnect()
                    del connected_devices[addr]
                abort(500)

@app.route('/devices/<int:dev_id>/', methods = ["GET", "PUT", "DELETE"])
def device(dev_id):
    row = mb2db.get_device_by_id(cnxn_string, dev_id)
    if row:
        if request.method == "GET":
                connected = True if row.mac in connected_devices else False
                signal = 0
                mibands = copy.deepcopy(tmp_mibands)
                if row.mac in mibands.keys():
                    signal = mibands[row.mac].rssi
                dev_user_id = mb2db.get_device_user(cnxn_string, dev_id)
                dev_user = mb2db.get_user_data(cnxn_string, dev_user_id)
                username = (dev_user.nombre + " " + dev_user.apellidos) if dev_user else "Unregistered"
                detail_dict = {"dev_id": row.dispositivoId, "battery": row.bateria, "registered": row.registrado,
                                "address": row.mac, "connected": connected, "signal": signal, "visible": (signal < 0),
                                "user_name": username, "reputation": reputation[row.mac.upper()]}
                return json.dumps(detail_dict)
        elif request.method == "PUT":
            if mb2db.is_device_registered(cnxn_string, row.mac):
                action = request.form.get("action")
                if action == "connect" and row.mac not in connected_devices.keys():
                    try:
                        reputation[row.mac.upper()] = 100
                        if not row.mac in devices_keys.keys():
                            key = DEFAULT_KEY
                        else:
                            key = devices_keys[row.mac.upper()]
                        mb2 = MiBand2(row.mac.upper(), key, initialize=False)
                        connected_devices[row.mac] = mb2
                        alarms = mb2db.get_device_alarms(cnxn_string, mb2.addr)
                        mb2db.update_battery(cnxn_string, mb2.addr, mb2.battery_info['level'])
                        for a in alarms:
                            mb2.alarms += [MiBand2Alarm(a["hour"], a["minute"], enabled=a["enabled"], repetitionMask=a["repetition"])]
                        reputation[row.mac.upper()] = 50
                        return json.dumps({"connected": True, "dev_id": row.dispositivoId}), 200
                    except BTLEException as e:
                        reputation[row.mac.upper()] = 50
                        print("There was a problem (dis)connecting to this MiBand2, try again later")
                        print e
                        abort(500)
                    except BTLEException.DISCONNECTED as d:
                        reputation[row.mac.upper()] = 50
                        print("Device disconnected, removing from connected devices")
                        del connected_devices[row.mac]
                        del mb2
                        abort(500)
                elif action == "disconnect" and row.mac in connected_devices.keys():
                    try:
                        mb2 = connected_devices[row.mac]
                        mb2.disconnect()
                        del connected_devices[row.mac]
                        del mb2
                        print ("MiBand2 disconnected!")
                        return json.dumps({"connected": False, "dev_id": row.dispositivoId}), 200
                    except BTLEException as e:
                        print("There was a problem disconnecting this MiBand2, try again later")
                        print e
                        abort(500)
                    except BTLEException.DISCONNECTED as d:
                        print("Device disconnected, removing from connected devices")
                        del connected_devices[row.mac]
                        del mb2
                        abort(500)
                elif action == "alert" and row.mac in connected_devices.keys():
                    try:
                        print ("Alerting MB2 " + row.mac)
                        mb2 = connected_devices[row.mac]
                        if request.args.get('notification') == "message":
                            mb2.send_alert(b'\x01')
                        elif request.args.get('notification') == "call":
                            mb2.send_alert(b'\x02')
                        elif request.args.get('notification') == "vibrate":
                            mb2.send_alert(b'\x03')
                        elif request.args.get('notification') == "stop":
                            mb2.send_alert(b'\x00')
                        else:
                            mb2.send_alert(b'\x03')
                        return json.dumps({"alerting": True, "dev_id": row.dispositivoId}), 200
                    except BTLEException as e:
                        print("There was a problem alerting this MiBand2, try again later")
                        del connected_devices[row.mac]
                        print e
                        abort(500)
                    except BTLEException.DISCONNECTED as d:
                        print("Device disconnected, removing from connected devices")
                        del connected_devices[row.mac]
                        del mb2
                        abort(500)
        elif request.method == "DELETE":
            # Just Unregister MiBand2
            if mb2db.is_device_registered(cnxn_string, row.mac):
                if not row.mac in connected_devices.keys():
                    try:
                        dev_id = mb2db.get_device_id(cnxn_string, row.mac)
                        mb2db.unregister_device(cnxn_string, dev_id)
                        mb2db.delete_all_alarms(cnxn_string, dev_id)
                        del devices_keys[row.mac.upper()]
                        print("MiBand2 unregistered!")
                        save_keys()
                        return json.dumps({"registered": False, "dev_id": row.dispositivoId}), 200
                    except BTLEException as e:
                        print("There was a problem unregistering this MiBand2, try again later")
                        print e
                        abort(500)
                    except BTLEException.DISCONNECTED as d:
                        print("Device disconnected, removing from connected devices")
                        if row.mac in connected_devices.keys():
                            connected_devices[row.mac].force_disconnect()
                            del connected_devices[row.mac]
                        abort(500)
        abort(403)
    else:
        abort(404)

@app.route('/devices/<int:dev_id>/alarms/', methods = ["GET", "POST", "DELETE"])
def alarms(dev_id):
    row = mb2db.get_device_by_id(cnxn_string, dev_id)
    if row:
        if request.method == "GET":
            alarms = mb2db.get_device_alarms_by_id(cnxn_string, dev_id)
            al_list = []
            for al in alarms:
                al_list.append({"id": al.alarmaId, "dev_id": al.dispositivoId,
                            "index": al.indiceAlarma, "hour": al.hora, "minute": al.minuto,
                            "enabled": al.activada, "repetition": al.repeticion})
            return json.dumps(al_list)
        if row.mac in connected_devices.keys():
            mb2 = connected_devices[row.mac]
            try:
                if request.method == "POST":
                    hour = int(request.form["hour"])
                    minute = int(request.form["minute"])
                    enabled = int(request.form.get("enabled")) if request.form.get("enabled") else 1
                    repetition_mask = int(request.form.get("repetition")) if request.form.get("repetition") else 128
                    alarm_id = mb2.queueAlarm(hour, minute, enableAlarm = enabled, repetitionMask = repetition_mask)
                    db_alarm = mb2db.set_alarm(cnxn_string, dev_id, mb2.alarms[alarm_id], alarm_id)
                    al = mb2.alarms[alarm_id]
                    return json.dumps({"dev_id": dev_id, "id": db_alarm.alarmaId, "index": alarm_id,
                                        "hour": al.hour, "minute": al.minute, "enabled": al.enabled,
                                        "repetition": al.repetitionMask})
                if request.method == "DELETE":
                    mb2.cleanAlarms()
                    mb2db.delete_all_alarms(cnxn_string, dev_id)
                    return json.dumps({"alarms_deleted": True, "dev_id": row.dispositivoId}), 200
            except BTLEException as e:
                print("There was a problem handling the alarms, try again later")
                print e
                abort(500)
            except BTLEException.DISCONNECTED as d:
                print("Device disconnected, removing from connected devices")
                del connected_devices[row.mac]
                del mb2
                abort(500)
        else:
            abort(403)
    else:
        abort(404)

@app.route('/devices/<int:dev_id>/alarms/<int:alarm_index>/', methods = ["GET", "PUT", "DELETE"])
def alarm(dev_id, alarm_index):
        row = mb2db.get_device_by_id(cnxn_string, dev_id)
        if row:
            alarms = mb2db.get_device_alarms_by_id(cnxn_string, dev_id)
            try:
                al = alarms[alarm_index]
            except IndexError as e:
                abort(404)
            if request.method == "GET":
                return json.dumps({"dev_id": dev_id, "alarm_id": al.alarmaId, "alarm_index": al.indiceAlarma,
                                    "hour": al.hora, "minute": al.minuto, "enabled": al.activada,
                                    "repetition": al.repeticion})
            if row.mac in connected_devices.keys():
                try:
                    mb2 = connected_devices[row.mac]
                    if request.method == "PUT":
                        hour = int(request.form.get("hour")) if request.form.get("hour") else al.hora
                        minute = int(request.form.get("minute")) if request.form.get("minute") else al.minuto
                        enabled = bool(int(request.form.get("enabled"))) if request.form.get("enabled") else al.activada
                        repetition_mask = int(request.form.get("repetition")) if request.form.get("repetition") else al.repeticion
                        if repetition_mask == 0:
                            repetition_mask = 128
                        mb2.setAlarm(alarm_index, hour, minute, repetition_mask, enabled)
                        al = mb2db.set_alarm(cnxn_string, dev_id, mb2.alarms[alarm_index], alarm_index)
                        return json.dumps({"dev_id": dev_id, "alarm_id": al.alarmaId, "alarm_index": al.indiceAlarma,
                                            "hour": al.hora, "minute": al.minuto, "enabled": al.activada,
                                            "repetition": al.repeticion})
                    if request.method == "DELETE":
                        mb2.deleteAlarm(alarm_index)
                        mb2db.delete_alarm(cnxn_string, dev_id, alarm_index)
                        return json.dumps({"alarm_deleted": True, "dev_id": row.dispositivoId}), 200
                except BTLEException as e:
                    print("There was a problem handling the alarm, try again later")
                    print e
                    abort(500)
                except BTLEException.DISCONNECTED as d:
                    print("Device disconnected, removing from connected devices")
                    del connected_devices[row.mac]
                    del mb2
                    abort(500)
            else:
                abort(403)
        else:
            abort(404)

@app.route('/devices/<int:dev_id>/config/', methods = ["GET", "PUT", "PATCH"])
def config(dev_id):
    row = mb2db.get_device_by_id(cnxn_string, dev_id)
    if row:
        if request.method == "GET":
            return json.dumps(config_presets.sections())
        if row.mac in connected_devices.keys():
            try:
                mb2 = connected_devices[row.mac]
                if request.method == "PUT":
                    preset = request.form.get("preset")
                    if not config_presets.has_section(request.form.get("preset")):
                        abort(400)
                    mb2 = connected_devices[row.mac]
                    print("Configuring MiBand to [%s] presets" % preset)
                    if config_presets.has_option(preset, "MonitorHRSleep"):
                        mb2.monitorHeartRateSleep(config_presets.getint(preset, "MonitorHRSleep"))
                    if config_presets.has_option(preset, "MonitorHRInterval"):
                        mb2.setMonitorHeartRateInterval(config_presets.getint(preset, "MonitorHRInterval"))
                    if config_presets.has_option(preset, "DisplayTimeFormat"):
                        mb2.setDisplayTimeFormat(config_presets.get(preset, "DisplayTimeFormat"))
                    if config_presets.has_option(preset, "DisplayTimeHours"):
                        mb2.setDisplayTimeHours(config_presets.getint(preset, "DisplayTimeHours"))
                    if config_presets.has_option(preset, "DistanceUnit"):
                        mb2.setDistanceUnit(config_presets.get(preset, "DistanceUnit"))
                    if config_presets.has_option(preset, "LiftWristActivate"):
                        mb2.setLiftWristToActivate(config_presets.getint(preset, "LiftWristActivate"))
                    if config_presets.has_option(preset, "RotateWristSwitch"):
                        mb2.setRotateWristToSwitchInfo(config_presets.getint(preset, "RotateWristSwitch"))
                    if config_presets.has_option(preset, "DisplayItems"):
                        disp = [x.strip() for x in config_presets.get(preset, 'DisplayItems').split(',')]
                        steps = True if 'steps' in disp else False
                        distance = True if 'distance' in disp else False
                        calories = True if 'calories' in disp else False
                        heartrate = True if 'heartrate' in disp else False
                        battery = True if 'battery' in disp else False
                        mb2.setDisplayItems(steps=steps, distance=distance, calories=calories, heartrate=heartrate, battery=battery)
                    if config_presets.has_option(preset, "DoNotDisturb"):
                        enableLift = config_presets.getint(preset, "DoNotDisturbLift") if config_presets.has_option(preset, "DoNotDisturbLift") else 1
                        mb2.setDoNotDisturb(config_presets.get(preset, "DoNotDisturb"), enableLift=enableLift)
                    if config_presets.has_option(preset, "InactivityWarnings"):
                        start = config_presets.getint(preset, "InactivityWarningsStart") if config_presets.has_option(preset, "InactivityWarningsStart") else 8
                        end = config_presets.getint(preset, "InactivityWarningsEnd") if config_presets.has_option(preset, "InactivityWarningsEnd") else 19
                        threshold = config_presets.getint(preset, "InactivityWarningsThresholdHours") if config_presets.has_option(preset, "InactivityWarningsThresholdHours") else 1
                        mb2.setInactivityWarnings(config_presets.getint(preset, "InactivityWarnings"), threshold=threshold*60, start=(start, 0), end=(end, 0))
                    if config_presets.has_option(preset, "DisplayCaller"):
                        mb2.setDisplayCaller(config_presets.getint(preset, "DisplayCaller"))
                    return json.dumps({"configured": True, "dev_id": dev_id, "preset": preset}), 200
                if request.method == "PATCH":
                    print("Rebooting MiBand2")
                    mb2.reboot()
                    return json.dumps({"rebooted": True, "dev_id": dev_id}), 200
            except BTLEException as e:
                print("There was a problem configuring this MiBand2, try again later")
                print e
                abort(500)
            except BTLEException.DISCONNECTED as d:
                print("Device disconnected, removing from connected devices")
                del connected_devices[row.mac]
                del mb2
                abort(500)
        else:
            abort(403)
    else:
        abort(404)

@app.route('/devices/<int:dev_id>/activity/', methods = ["GET"])
def activity(dev_id):
    row = mb2db.get_device_by_id(cnxn_string, dev_id)
    if row:
        try:
            if request.args.get('fetch') == "1":
                q.put((row.mac, False,))
                q.join()
        except BTLEException as e:
            print("There was a problem fetching activity of this MiBand2, try again later")
            print e
            abort(500)
        except BTLEException.DISCONNECTED as d:
            print("Device disconnected, removing from connected devices")
            del connected_devices[row.mac]
            del mb2
            abort(500)
        start = datetime.datetime.strptime('1984-01-01 00:00', '%Y-%m-%d %H:%M')
        end = datetime.datetime.now()
        if request.args.get('since'):
            try:
                start = datetime.datetime.strptime(request.args.get('since'), '%Y-%m-%d %H:%M')
            except ValueError as e:
                start = datetime.datetime.strptime(request.args.get('since'), '%Y/%m/%d %H:%M:%S')
        if request.args.get('until'):
            try:
                end = datetime.datetime.strptime(request.args.get('until'), '%Y-%m-%d %H:%M')
            except ValueError as e:
                end = datetime.datetime.strptime(request.args.get('until'), '%Y/%m/%d %H:%M:%S')
        frames = mb2db.get_activity_data(cnxn_string, dev_id, start, end)
        f_list = []
        for f in frames:
            date = f.fechaInicial.strftime('%Y-%m-%d %H:%M')
            f_list.append({"date": date, "type": f.categoria, "steps": f.pasos,
                            "intensity": f.intensidad, "heartrate": f.pulsaciones,
                            "dev_id": dev_id, "user_id": f.usuarioId})
        return json.dumps(f_list)
    else:
        abort(404)

@app.route('/devices/<int:dev_id>/user/', methods = ["GET", "POST", "DELETE"])
def device_user(dev_id):
    row = mb2db.get_device_by_id(cnxn_string, dev_id)
    if row:
        if request.method == "GET":
            u = mb2db.get_device_user(cnxn_string, dev_id)
            if u:
                return json.dumps({"id": u.usuarioId, "name": u.nombre,
                    "surname": u.apellidos, "email": u.correo, "weight": u.peso,
                    "height": u.altura, "center": u.centroId, "dev_id": dev_id,
                    "alias": mb2db.get_alias(u.nombre, u.apellidos, u.dni)}), 200
            else:
                return json.dumps({}), 200
        if row.mac in connected_devices.keys():
            try:
                mb2 = connected_devices[row.mac]
                if request.method == "POST":
                    user_id = request.form.get('user_id')
                    position = request.form.get('position')
                    if not position and not user_id:
                        abort(400)
                    if position not in ["left", "right"]:
                        abort(400)
                    else:
                        pos_bit = 0 if (position == "left") else 0
                    udata = mb2db.get_user_data(cnxn_string, user_id)
                    if udata:
                        try:
                            mb2.setUserInfo(udata["alias"], udata["sex"], udata["height"], udata["weight"], udata["birth"])
                            mb2.setWearLocation(position)
                        except Exception as e:
                            print(e)
                        else:
                            if mb2db.set_device_user(cnxn_string, dev_id, user_id, pos_bit):
                                return json.dumps({"linked": True, "dev_id": dev_id, "user_id": user_id, "position": position}), 200
                    abort(403)
                if request.method == "DELETE":
                    if mb2db.release_device_user(cnxn_string, dev_id):
                        return json.dumps({"linked": False, "dev_id": dev_id}), 200
                    else:
                        abort(403)
            except BTLEException as e:
                print("There was a problem handling the user of this MiBand2, try again later")
                print e
                abort(500)
            except BTLEException.DISCONNECTED as d:
                print("Device disconnected, removing from connected devices")
                del connected_devices[row.mac]
                del mb2
                abort(500)
        abort(403)
    else:
        abort(404)

devices_keys = read_json(base_route + '/localdata/devices_keys.json')

sc = Scanner()
scd = MiBand2ScanDelegate(rssithreshold)
sc.withDelegate(scd)

scan_thread = threading.Thread(target=scan_miband2, args=(sc,rssithreshold,))
scan_thread.start()

#ping_thread = threading.Thread(target=ping_connected, args=(pingtimer,))
#ping_thread.start()

for i in range(max_connections):
     t = threading.Thread(target=worker)
     t.daemon = True
     t.start()

app.run(debug=env.getboolean('SERVER', 'debug'), host=env.get('SERVER', 'host'))
