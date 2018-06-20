#!/usr/bin/env python

# Daemon to automatically and unattendedly fetch data from near MiBands 2
# Requires to previously register those very MiBands 2 within the System
# Use mb2shell.py to do so

# The background Scanning thread requires superuser privileges

import json
import threading
import binascii
from bluepy.btle import Scanner, DefaultDelegate, BTLEException
import re
import sys
import os
import struct
import Queue
import lockfile
import datetime
import logging
import logging.handlers

base_dir = os.getcwd()
sys.path.append(base_dir + '/lib')
from miband2 import MiBand2
from miband2time import MiBand2Time

LOG_FILENAME = "/var/log/miband2server.log"
LOG_LEVEL = logging.INFO

q = Queue.Queue()
max_connections = 5

activity_fetch_cooldown = 6 * 60
registered_devices = json.load(open(base_dir +'/storage/registered_devices.json'))
devices_last_sync = json.load(open(base_dir +'/storage/devices_last_sync.json'))

logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)
handler = logging.handlers.TimedRotatingFileHandler(LOG_FILENAME, when="midnight", backupCount=3)
formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

class MyLogger(object):
        def __init__(self, logger, level):
                """Needs a logger and a logger level."""
                self.logger = logger
                self.level = level

        def write(self, message):
                # Only log if there is a message (not just a new line)
                if message.rstrip() != "":
                        self.logger.log(self.level, message.rstrip())

class MiBand2ScanDelegate(DefaultDelegate):
    def __init__(self, scanner):
        DefaultDelegate.__init__(self)
        self.mibands = {}
        self.visible_devices = []
        self.scanner = scanner

    def handleDiscovery(self, dev, isNewDev, isNewData):
        try:
            name = dev.getValueText(9)
            serv = dev.getValueText(2)
            if name == 'MI Band 2' and serv == 'e0fe' and dev.addr in registered_devices:
                self.mibands[dev.addr] = dev
        except:
            print "ERROR"
        finally:
            for mb in self.mibands.keys():
                if mb not in self.visible_devices:
                    del self.mibands[mb]

def scan_miband2(scanner, delegate):
    print("Scanning!")
    scanner.clear()
    scanner.start()
    t = threading.currentThread()
    while getattr(t, "do_scan", True):
        scanner.process(5)
        delegate.visible_devices = map(lambda x: x.addr, scanner.getDevices())
    print("Stopped scanning...")
    scanner.stop()

def save_sync(sync):
    with open(base_dir + '/storage/devices_last_sync.json', 'wb') as outfile:
        json.dump(sync, outfile)

def worker():
    while True:
        item = q.get()
        lastDate = do_fetch_activity(item)
        if lastDate != None:
            devices_last_sync[item] = lastDate
        q.task_done()

def do_fetch_activity(item):
    print "Fetching MiBand2 [%s] activity!" % item
    try:
        mb2 = MiBand2(item, initialize=False)
        try:
            if item in devices_last_sync.keys():
                mb2.setLastSyncDate(devices_last_sync[item])
            mb2.send_alert(b'\x01')
            mb2.fetch_activity_data(base_dir + '/activity_log/')
            mb2.send_alert(b'\x01')
            print "Finished fetching MiBand2 [%s] activity!" % item
            lastDate = str(mb2.lastSyncDate)
            mb2.disconnect()
            return lastDate
        except BTLEException as e:
            print("There was a problem retrieving this MiBand2's activity, try again later")
            print e
    except BTLEException as e:
        print("There was a problem connecting this MiBand2, try again later")
        print e
    return None



def main():
    print ("Running Server!")
    sys.stdout = MyLogger(logger, logging.INFO)
    sys.stderr = MyLogger(logger, logging.ERROR)

    sc = Scanner()
    scd = MiBand2ScanDelegate(sc)
    sc.withDelegate(scd)

    scan_thread = threading.Thread(target=scan_miband2, args=(sc,scd,))
    scan_thread.start()

    for i in range(max_connections):
         t = threading.Thread(target=worker)
         t.daemon = True
         t.start()

    old_stats_registered = 0
    old_stats_visible = 0
    old_stats_outcd = 0
    old_stats_incd = 0

    while True:
        out_of_cd = []
        for mb in scd.mibands.keys():
            if mb in devices_last_sync.keys():
                m = re.search("(\d+)-(\d+)-(\d+)\s+(\d+):(\d+)", devices_last_sync[mb])
                if m.groups() != None:
                    date = list(map(lambda x: int(x), m.groups()))
                    ls = MiBand2Time(None, date[0], date[1], date[2], date[3], date[4])
                    if ls.minutesUntilNow() >= activity_fetch_cooldown:
                        out_of_cd += [mb]
            else:
                out_of_cd += [mb]

        stats_registered = len(registered_devices)
        stats_visible = len(scd.visible_devices)
        stats_outcd = len(out_of_cd)
        stats_incd = len(scd.mibands.keys())-len(out_of_cd)

        if (stats_registered != old_stats_registered or stats_visible != old_stats_visible or stats_outcd != old_stats_outcd or stats_incd != old_stats_incd):
            print("Registered: {0} // Visible: {1} // Out of cooldown: {2} // In Cooldown: {3}".format(
                len(registered_devices), len(scd.visible_devices),
                len(out_of_cd), len(scd.mibands.keys())-len(out_of_cd)))

        for item in out_of_cd:
            q.put(item)

        q.join()
        if len(out_of_cd) > 0:
            save_sync(devices_last_sync)

        old_stats_registered = stats_registered
        old_stats_visible = stats_visible
        old_stats_outcd = stats_outcd
        old_stats_incd = stats_incd

if __name__ == '__main__':
    main()
