#!/usr/bin/env python

import threading
import time
import os
import sys
import copy
import signal
from bluepy.btle import Scanner, DefaultDelegate, BTLEException
base_route = os.path.dirname(os.path.realpath(__file__))
config_route = base_route + "/configuration"
sys.path.append(base_route + '/lib')
from miband_generic import MiBand
from mibandalarm import MiBandAlarm

max_connections = 5
connected_devices = {}

class MiBand2ScanDelegate(DefaultDelegate):
    def __init__(self, scanthresh):
        DefaultDelegate.__init__(self)
        self.tmp_devices = {}
        self.scanthresh = scanthresh

    def handleDiscovery(self, dev, isNewDev, isNewData):
        try:
            name = dev.getValueText(9)
            serv = dev.getValueText(2)
            if serv == '0000fee0-0000-1000-8000-00805f9b34fb' and dev.addr:
                if dev.rssi >= self.scanthresh:
                    if dev.addr not in self.tmp_devices.keys():
                        self.tmp_devices[dev.addr] = {"device": dev, "reputation": 50}
        except Exception as e:
            print e
            print "ERROR"

def scan_miband2(scanner, scanthresh):
    print("Scanning!")
    scanner.clear()
    scanner.start()
    t = threading.currentThread()
    while getattr(t, "do_scan", True):
        old_devices = copy.deepcopy(scanner.delegate.tmp_devices)
        scanner.process(2)
        for d in old_devices.keys():
            if d in scanner.delegate.tmp_devices.keys():
                new_signal = scanner.delegate.tmp_devices[d]["device"].rssi
                signal_diff = (old_devices[d]["device"].rssi - scanner.delegate.tmp_devices[d]["device"].rssi)
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
                    scanner.delegate.tmp_devices[d]["reputation"] -= 10
                elif signal_diff in range(-5, 6):
                    # If there is little variation, reputation increases
                    scanner.delegate.tmp_devices[d]["reputation"] += 10*proximity_factor
                elif signal_diff in range (-10, -5):
                    # If there is a big negative variation, reputation decreases
                    scanner.delegate.tmp_devices[d]["reputation"] -= 5
                elif signal_diff < -10:
                    # If there is a VERY big negative variation, reputation decreases drastically
                    scanner.delegate.tmp_devices[d]["reputation"] -= 10
                elif signal_diff > 5:
                    # If there is a big positive variation, reputarion increases a bit
                    scanner.delegate.tmp_devices[d]["reputation"] += 5*proximity_factor

                if scanner.delegate.tmp_devices[d]["reputation"] >= 100:
                    scanner.delegate.tmp_devices[d]["reputation"] = 100

                if scanner.delegate.tmp_devices[d]["reputation"] <= 0:
                    scanner.delegate.tmp_devices[d]["reputation"] = 0

                if scanner.delegate.tmp_devices[d]["reputation"] >= 90:
                    print("Downloading from {0}".format(d))
                if scanner.delegate.tmp_devices[d]["reputation"] <= 10:
                    del scanner.delegate.tmp_devices[d]
    print("Stopped scanning...")
    scanner.stop()

def main():
    scanthresh = -200
    sc = Scanner()
    scd = MiBand2ScanDelegate(scanthresh)
    sc.withDelegate(scd)

    mibands = []

    scan_thread = threading.Thread(target=scan_miband2, args=(sc,scanthresh))
    scan_thread.start()

    while True:
        os.system('clear')
        mibands = copy.deepcopy(scd.tmp_devices)
        print "Mi Band Scanner"
        print "Near Mi Bands: \t{0}".format(len(mibands))
        print "------------------------------"
        for idx, mb in enumerate(mibands.values()):
            print "[{0}] {1} <{2}> ({3}dB) REP: {4}".format(idx, mb["device"].getValueText(9),
                mb["device"].addr, mb["device"].rssi, mb["reputation"])
        time.sleep(2)

    scan_thread.do_start = False



if __name__ == '__main__':
    main()
