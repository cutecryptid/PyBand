#!/usr/bin/env python

import threading
import time
import os
import sys
import copy
from bluepy.btle import Scanner, DefaultDelegate, BTLEException
base_route = os.path.dirname(os.path.realpath(__file__))
config_route = base_route + "/configuration"
sys.path.append(base_route + '/lib')
from miband2 import MiBand2, MiBand2Alarm

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

def scan_miband2(scanner,strikes,thresh):
    print("Scanning!")
    scanner.clear()
    scanner.start()
    t = threading.currentThread()
    while getattr(t, "do_scan", True):
        old_devices = copy.deepcopy(scanner.delegate.tmp_devices)
        scanner.process(1)
        for d in old_devices.keys():
            if d in scanner.delegate.tmp_devices.keys():
                if ((old_devices[d]["device"].rssi == scanner.delegate.tmp_devices[d]["device"].rssi)
                    or scanner.delegate.tmp_devices[d]["device"].rssi < thresh):
                    scanner.delegate.tmp_devices[d]["strikes"] += 1
                    if scanner.delegate.tmp_devices[d]["strikes"] >= strikes:
                        del scanner.delegate.tmp_devices[d]
    print("Stopped scanning...")
    scanner.stop()

def main():
    strikes = 5
    thresh = -70
    sc = Scanner()
    scd = MiBand2ScanDelegate(thresh)
    sc.withDelegate(scd)

    mibands = []

    scan_thread = threading.Thread(target=scan_miband2, args=(sc,strikes,thresh,))
    scan_thread.start()

    while True:
        os.system('clear')
        mibands = copy.deepcopy(scd.tmp_devices)
        print "Mi Band 2 Scanner"
        print "Near Mi Bands 2: \t{0}".format(len(mibands))
        print "------------------------------"
        for idx, mb in enumerate(mibands.values()):
            print "[{0}] {1}-{2} <{3}> ({4}dB) {5}".format(idx, mb["device"].getValueText(9),
                mb["device"].getValueText(2), mb["device"].addr, mb["device"].rssi, "X"*mb["strikes"])
        time.sleep(2)

    scan_thread.do_start = False



if __name__ == '__main__':
    main()
