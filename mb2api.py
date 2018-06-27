#!/usr/bin/env python

base_route = "/home/miband2server/scripts"

from flask import Flask, g, request, flash, url_for, redirect, render_template, abort, jsonify
import os
import logging
import cmd
import json
import threading
import binascii
from bluepy.btle import Scanner, DefaultDelegate, BTLEException
import re
import sys
import copy
import struct
import jwt
import pyodbc
import datetime
import argparse
import Queue
import ConfigParser
from flask import Flask
sys.path.append(base_route + '/lib')
from miband2 import MiBand2, MiBand2Alarm
import miband2db as mb2db

app = Flask(__name__)

parser = argparse.ArgumentParser(description='MiBand2 Server and API')
parser.add_argument('-e', '--env', default='development',
                    help='determine the enviroment config for the server')

args = parser.parse_args()

ENV_CONFIG = args.env
CONFIG_MODE="GERIATIC"
VERSION_STRING = "0.9"

q = Queue.Queue()
max_connections = 5
# For automated download stablish a period in which we don't download data
# activity_fetch_cooldown = 6 * 60
connected_devices = {}
tmp_mibands = {}
mibands = {}
strikes = {}
rssithreshold = -70
max_strikes = 20

config_route = base_route + "/configuration"
env_route = config_route + "/" + ENV_CONFIG

config_presets = ConfigParser.ConfigParser()
config_presets.readfp(open(config_route + '/mb2_presets.conf'))

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
                tmp_mibands[dev.addr] = dev
                strikes[dev.addr] = 0
        except:
            print "ERROR"

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

def scan_miband2(scanner,max_strikes,thresh):
    print("Scanning!")
    scanner.clear()
    scanner.start()
    t = threading.currentThread()
    while getattr(t, "do_scan", True):
        old_mibands = copy.deepcopy(tmp_mibands)
        scanner.process(2)
        for d in old_mibands.keys():
            if d in connected_devices.keys():
                strikes[d] = 0
            if d in tmp_mibands.keys() and (d not in connected_devices.keys()):
                if ((old_mibands[d].rssi == tmp_mibands[d].rssi)
                    or tmp_mibands[d].rssi < thresh):
                    strikes[d] += 1
                    if strikes[d] >= max_strikes:
                        del tmp_mibands[d]
                        strikes[d] = 0
    print("Stopped scanning...")
    scanner.stop()

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
        last_sync = mb2db.get_device_last_sync(cnxn_string, item)
        if last_sync != None:
            connected_devices[item].setLastSyncDate(last_sync)
        connected_devices[item].send_alert(b'\x03')
        connected_devices[item].fetch_activity_data()
        connected_devices[item].send_alert(b'\x03')
        if len(connected_devices[item].getActivityDataBuffer()) > 0:
            print "Saving Data to DB..."
            mb2db.write_activity_data(cnxn_string, connected_devices[item])
        print "Finished fetching MiBand2 [%s] activity!" % item
    except BTLEException as e:
        print("There was a problem retrieving this MiBand2's activity, try again later")
        print e


@app.before_request
def before_request():
    print str(request.form)
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
            dev_user = mb2db.get_device_user(cnxn_string, dev_id)
            device = mb2db.get_device_by_id(cnxn_string, dev_id)
            battery = -1
            if device:
                battery = device.bateria
            username = (dev_user.nombre + " " + dev_user.apellidos) if dev_user else "Unregistered"
            dev_dict = {"address":mb, "signal": mibands[mibands.keys()[idx]].rssi,
                        "registered": False, "connected": False, "dev_id": dev_id,
                        "user_name": username, "battery": battery}
            if mb2db.is_device_registered(cnxn_string, mb):
                dev_dict["registered"] = True
            if mb in connected_devices.keys():
                dev_dict["connected"] = True
            dev_list += [dev_dict]
        return json.dumps(dev_list)
    elif request.method == "POST":
        addr = request.form["address"]
        if mb2db.is_device_registered(cnxn_string, addr):
            abort(403)
        else:
            try:
                strikes[addr] = -9999
                mb2 = MiBand2(addr, initialize=True)
                mb2.cleanAlarms()
                dev_id = mb2db.register_device(cnxn_string, mb2.addr)
                mb2db.delete_all_alarms(cnxn_string, dev_id)
                mb2db.update_battery(cnxn_string, mb2.addr, mb2.battery_info['level'])
                # Device stays connected after initialize, but we don't want that
                mb2.disconnect()
                return json.dumps({"dev_id": dev_id, "registered": True})
            except BTLEException as e:
                print("There was a problem registering this MiBand2, try again later")
                print e
                abort(500)
            except BTLEException.DISCONNECTED as d:
                print("Device disconnected, removing from connected devices")
                del connected_devices[addr]
                del mb2
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
                dev_user = mb2db.get_device_user(cnxn_string, dev_id)
                username = (dev_user.nombre + " " + dev_user.apellidos) if dev_user else "Unregistered"
                detail_dict = {"dev_id": row.dispositivoId, "battery": row.bateria, "registered": row.registrado,
                                "address": row.mac, "connected": connected, "signal": signal, "visible": (signal < 0),
                                "user_name": username}
                return json.dumps(detail_dict)
        elif request.method == "PUT":
            if mb2db.is_device_registered(cnxn_string, row.mac):
                action = request.form.get("action")
                strikes[row.mac] = -9999
                if action == "connect" and row.mac not in connected_devices.keys():
                    try:
                        mb2 = MiBand2(row.mac, initialize=False)
                        connected_devices[row.mac] = mb2
                        alarms = mb2db.get_device_alarms(cnxn_string, mb2.addr)
                        mb2db.update_battery(cnxn_string, mb2.addr, mb2.battery_info['level'])
                        for a in alarms:
                            mb2.alarms += [MiBand2Alarm(a["hour"], a["minute"], enabled=a["enabled"], repetitionMask=a["repetition"])]
                        return json.dumps({"connected": True, "dev_id": row.dispositivoId}), 200
                    except BTLEException as e:
                        print("There was a problem (dis)connecting to this MiBand2, try again later")
                        print e
                        abort(500)
                    except BTLEException.DISCONNECTED as d:
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
        elif request.method == "DELETE":
            # Just Unregister MiBand2
            if mb2db.is_device_registered(cnxn_string, row.mac):
                if not row.mac in connected_devices.keys():
                    try:
                        dev_id = mb2db.get_device_id(cnxn_string, row.mac)
                        mb2db.unregister_device(cnxn_string, dev_id)
                        mb2db.delete_all_alarms(cnxn_string, dev_id)
                        print("MiBand2 unregistered!")
                        return json.dumps({"registered": False, "dev_id": row.dispositivoId}), 200
                    except BTLEException as e:
                        print("There was a problem unregistering this MiBand2, try again later")
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
                q.put(row.mac)
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
            start = datetime.datetime.strptime(request.args.get('since'), '%Y-%m-%d %H:%M')
        if request.args.get('until'):
            end = datetime.datetime.strptime(request.args.get('until'), '%Y-%m-%d %H:%M')
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

sc = Scanner()
scd = MiBand2ScanDelegate(rssithreshold)
sc.withDelegate(scd)

scan_thread = threading.Thread(target=scan_miband2, args=(sc,max_strikes,rssithreshold))
scan_thread.start()

for i in range(max_connections):
     t = threading.Thread(target=worker)
     t.daemon = True
     t.start()

app.run(debug=env.getboolean('SERVER', 'debug'), host=env.get('SERVER', 'host'))
